"""The agent loop: user msg -> LLM (stream) -> tool calls -> results -> ... -> final answer.

Emits UI-friendly events consumed by both the CLI and the web server:
  reasoning_delta, assistant_delta, tool_start, tool_result,
  assistant_message, turn_end, error
"""
import datetime
import platform
import traceback
from pathlib import Path

from . import config, guard, llm, tools
from .llm import LLMError
from .mcp import manager as mcp_manager
from .session import SessionStore

MAX_ITERATIONS = 30

SYSTEM_PROMPT = """You are Forge, an expert AI coding agent running inside the user's \
workspace (similar to Claude Code / Codex CLI). Today is {date}. Platform: {platform}.
Workspace directory: {workspace}

OS command rules (CRITICAL - read carefully):
- If the OS is Windows: commands run in cmd.exe, NOT bash. Use `python` (NEVER `python3` - \
it does not exist there), `dir` / `type` instead of ls / cat, `findstr` instead of grep, \
there is no pwd/tail/head. Prefer writing small Python scripts over shell tricks.
- If the OS is Linux/macOS: use standard POSIX shell commands.
- NEVER repeat a failing command unchanged. Read the error, fix the cause, change approach.

You operate on files in the current workspace using these tools:
- list_dir / read_file / write_file / edit_file / search_files
- run_command: execute shell commands in the workspace (builds, tests, git, scripts)

Additional tools prefixed with "mcp_" come from external MCP servers connected by the
user - prefer them when the user's task matches their descriptions. A shell command may
be BLOCKED by the safety guard; if so, tell the user instead of retrying it.

Git rules: git is available. Commit only when the user asks. Stage only files you changed \
(`git add <paths>`, never blanket `git add -A` unless asked). Write concise conventional \
commit messages. NEVER force-push, rewrite history, or push to main without explicit \
instruction.

Working style:
1. EXPLORE before you change: list/read relevant files first, understand context.
2. PLAN briefly: for non-trivial tasks state a short plan, then execute step by step.
3. ACT with tools: prefer write_file/edit_file over printing code in chat; verify your \
work by running tests or the code when possible.
4. Be concise in prose. Let the tools do the talking. Never invent file contents - read them.
5. If a command fails, read the error, fix, and retry ONCE with a changed approach.
6. Finish with a short summary of what changed and how to run it.
{agents_md}
"""

PLAN_ADDENDUM = """

=== PLAN MODE (READ-ONLY) ===
You are in PLAN mode: you may ONLY explore (list_dir, read_file, search_files).
Do NOT create, modify, or delete anything. Do NOT run mutating commands.
Explore the workspace, then produce: (1) a short understanding of the current state,
(2) a numbered step-by-step implementation plan with files to touch, (3) risks/unknowns,
(4) how to verify. The user will review this plan and switch to Agent mode to execute.
"""

READ_ONLY_TOOLS = {"list_dir", "read_file", "search_files"}
CHAT_MODES = ("direct", "agent", "plan")


def _agents_md_block(workspace: Path) -> str:
    """Đọc quy tắc dự án: AGENTS.md > AGENTS.txt > CLAUDE.md (chuẩn Codex/OpenCode/Claude Code)."""
    blocks = []
    for name in ("AGENTS.md", "AGENTS.txt", "CLAUDE.md"):
        p = workspace / name
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")[:4000]
                if text.strip():
                    blocks.append(f"=== PROJECT INSTRUCTIONS ({name}) — follow strictly ===\n{text}")
                    break  # chỉ 1 file quy tắc cấp dự án (ưu tiên cao nhất)
            except Exception:
                pass
    # quy tắc toàn cục của người dùng (nếu có)
    try:
        g = config.DATA_DIR / "AGENTS.md"
        if g.is_file():
            text = g.read_text(encoding="utf-8", errors="replace")[:2000]
            if text.strip():
                blocks.append(f"=== GLOBAL USER RULES (data/AGENTS.md) ===\n{text}")
    except Exception:
        pass
    if not blocks:
        return ""
    return "\n" + "\n\n".join(blocks) + "\n"


class Agent:
    def __init__(self, store: SessionStore, session_id: str, model: str | None = None):
        self.store = store
        self.session = store.get(session_id)
        if self.session is None:
            raise ValueError(f"Session {session_id} not found")
        if model:
            self.session.model = model
        self.model = self.session.model or config.get_model()
        self.workspace: Path = store.workspace(session_id)

    def _system_message(self) -> dict:
        return {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                date=datetime.date.today().isoformat(),
                platform=f"{platform.system()} {platform.release()} ({platform.machine()}) / Python {platform.python_version()}",
                workspace=str(self.workspace),
                agents_md=_agents_md_block(self.workspace),
            ),
        }

    async def send(self, user_text: str, chat_mode: str = "agent", content=None):
        """Run one full user turn; async-generator of events.

        chat_mode: "agent" (full loop) | "direct" (no tools) | "plan" (read-only).
        content: payload lưu vào session — mặc định là user_text; truyền list
        content-parts (multimodal: text + image_url) khi có ảnh đính kèm.
        """
        s = self.session
        s.messages.append({"role": "user",
                           "content": content if content is not None else user_text})
        if s.title == "New session":
            s.title = user_text.strip().replace("\n", " ")[:60] or "New session"
        self.store.save(s)

        if chat_mode not in CHAT_MODES:
            chat_mode = "agent"
        # --- auto-compact: chống tràn context ở phiên dài ---
        acc = config.get_auto_compact_chars()
        if acc and len(s.messages) > 8 and _conversation_chars(s.messages) > acc:
            yield {"type": "compacting", "chars": _conversation_chars(s.messages)}
            cres = await compact_session(self)
            yield {"type": "compacted", "ok": cres.get("ok"),
                   "before": cres.get("before"), "after": cres.get("after")}
        sys_msg = self._system_message()
        if chat_mode == "plan":
            sys_msg["content"] += PLAN_ADDENDUM
        messages = [sys_msg] + s.messages
        total_usage = None
        mcp_specs: list[dict] = []
        mcp_routing: dict = {}
        if chat_mode != "direct":
            try:
                mcp_specs, mcp_routing = await mcp_manager.get_tool_specs()
                if mcp_routing:
                    yield {"type": "mcp_ready", "tools": list(mcp_routing.keys())}
            except Exception as e:
                yield {"type": "error", "message": f"MCP: {e}"}
        all_specs = tools.TOOL_SPECS + mcp_specs
        if chat_mode == "direct":
            active_specs: list[dict] | None = None
        elif chat_mode == "plan":
            active_specs = [sp for sp in all_specs if sp["function"]["name"] in READ_ONLY_TOOLS]
        else:
            active_specs = all_specs

        try:
            for _ in range(MAX_ITERATIONS):
                content_parts: list[str] = []
                tool_calls: list[dict] | None = None
                usage = None

                async for ev in llm.stream_chat(messages, tools=active_specs, model=self.model):
                    et = ev["type"]
                    if et == "delta":
                        content_parts.append(ev["text"])
                        yield {"type": "assistant_delta", "text": ev["text"]}
                    elif et == "reasoning":
                        yield {"type": "reasoning_delta", "text": ev["text"]}
                    elif et == "tool_calls":
                        tool_calls = ev["tool_calls"]
                    elif et == "usage":
                        usage = ev["usage"]

                content = "".join(content_parts)
                assistant_msg = llm.build_assistant_message(content, tool_calls)
                s.messages.append(assistant_msg)
                messages.append(assistant_msg)
                yield {"type": "assistant_message", "content": content or None,
                       "tool_calls": tool_calls}
                if usage:
                    total_usage = usage

                if not tool_calls:
                    break

                for tc in tool_calls:
                    name = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments") or "{}"
                    import json as _json
                    try:
                        args = _json.loads(raw_args) if raw_args.strip() else {}
                    except _json.JSONDecodeError:
                        args = {"_raw": raw_args}
                    yield {"type": "tool_start", "id": tc["id"], "name": name, "args": args}

                    # ---- interactive approval ("ask" mode) ----
                    override = False
                    if name == "run_command":
                        from . import approvals
                        mode = config.load_config().get("approval_mode", "guarded")
                        cmd = str(args.get("command", ""))
                        verdict = guard.assess_command(cmd)
                        if (mode == "ask" and verdict["level"] in ("warn", "danger")
                                and cmd not in self.session.allowed_commands):
                            aid = approvals.create(cmd, verdict["level"], verdict["reasons"])
                            yield {"type": "approval_request", "id": aid, "command": cmd,
                                   "level": verdict["level"], "reasons": verdict["reasons"]}
                            decision = await approvals.wait(aid)
                            yield {"type": "approval_decision", "id": aid, "decision": decision}
                            if decision == "deny":
                                result = {"ok": False, "output": (
                                    "User DENIED this command. Do not retry it unchanged; "
                                    "explain and propose a different approach.")}
                                result_args = args
                                # skip execution — jump to emitting result
                                yield {"type": "tool_result", "id": tc["id"], "name": name,
                                       "args": result_args, "ok": False, "output": result["output"]}
                                self.session.messages.append({
                                    "role": "tool", "tool_call_id": tc["id"],
                                    "content": result["output"]})
                                messages.append(self.session.messages[-1])
                                continue
                            override = True
                            if decision == "approve_always":
                                self.session.allowed_commands.append(cmd)

                    if name in mcp_routing:
                        result = await mcp_manager.call_namespaced(mcp_routing, name, args)
                    else:
                        result = await tools.execute_tool(name, args, self.workspace, override=override)
                    ev = {"type": "tool_result", "id": tc["id"], "name": name,
                          "args": args, "ok": result["ok"], "output": result["output"]}
                    if result.get("diff"):
                        ev["diff"] = result["diff"]
                    if result.get("path"):
                        ev["path"] = result["path"]
                    yield ev
                    s.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result["output"],
                    })
                    messages.append(s.messages[-1])
                self.store.save(s)
        except LLMError as e:
            self.store.save(s)
            yield {"type": "error", "message": str(e)}
            return
        except Exception as e:
            self.store.save(s)
            traceback.print_exc()
            yield {"type": "error", "message": f"Lỗi engine: {e}"}
            return

        s.usage = _accumulate(s.usage, total_usage)
        self.store.save(s)
        yield {"type": "turn_end", "usage": total_usage, "session_usage": s.usage,
               "message_count": len(s.messages)}


def _accumulate(session_usage: dict, turn_usage: dict | None) -> dict:
    if not turn_usage:
        return session_usage
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        session_usage[k] = session_usage.get(k, 0) + (turn_usage.get(k) or 0)
    session_usage["cost"] = round(
        session_usage.get("cost", 0.0) + (turn_usage.get("cost") or 0.0), 6)
    return session_usage


# ---------------------------------------------------------------------------
# Context compaction (/compact + auto)
# ---------------------------------------------------------------------------
COMPACT_SYSTEM = (
    "You are a conversation compactor for an AI coding agent. Summarize the "
    "conversation transcript faithfully. Keep: task goals, key decisions, files "
    "created/modified (paths), important code/commands, current state and next "
    "steps. Be factual, no opinions. Write in the SAME LANGUAGE as the "
    "conversation. Max ~400 words. Output ONLY the summary."
)

KEEP_RECENT_MESSAGES = 4


def _msg_text(content) -> str:
    """Content có thể là str hoặc list content-parts (multimodal)."""
    if isinstance(content, list):
        return " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return str(content or "")


def _conversation_chars(messages: list[dict]) -> int:
    return sum(len(_msg_text(m.get("content"))) + len(str(m.get("tool_calls") or "")) for m in messages)


def _transcript(messages: list[dict], per_msg_cap: int = 1200) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "?").upper()
        c = _msg_text(m.get("content"))
        if m.get("tool_calls"):
            calls = ", ".join(tc["function"]["name"] for tc in m["tool_calls"])
            c = (c or "") + f" [tool_calls: {calls}]"
        if not c.strip():
            continue
        if len(c) > per_msg_cap:
            c = c[:per_msg_cap] + " …"
        lines.append(f"{role}: {c}")
    return "\n".join(lines)


async def compact_session(agent: "Agent", instructions: str = "") -> dict:
    """Tóm tắt hội thoại bằng LLM, thay messages bằng summary + vài tin nhắn cuối."""
    from . import llm
    s = agent.session
    if not s.messages:
        return {"ok": False, "message": "Phiên trống — không có gì để nén"}
    before = len(s.messages)
    transcript = _transcript(s.messages)
    prompt = ("Summarize the following agent conversation transcript.\n\n"
              + (f"User focus instructions: {instructions}\n" if instructions else "")
              + f"\n=== TRANSCRIPT ===\n{transcript}")
    parts: list[str] = []
    try:
        async for ev in llm.stream_chat(
                [{"role": "system", "content": COMPACT_SYSTEM},
                 {"role": "user", "content": prompt}],
                tools=None, model=agent.model, temperature=0.2):
            if ev["type"] == "delta":
                parts.append(ev["text"])
    except llm.LLMError as e:
        return {"ok": False, "message": f"Không nén được: {e}"}
    summary = "".join(parts).strip()
    if not summary:
        return {"ok": False, "message": "LLM không trả về tóm tắt — thử lại"}
    header = f"[TÓM TẮT HỘI THOẠI TRƯỚC ĐÓ — {before} tin nhắn được nén]"
    if instructions:
        header += f"\n[Trọng tâm theo yêu cầu: {instructions}]"
    keep = s.messages[-KEEP_RECENT_MESSAGES:]
    s.messages = [{"role": "user", "content": f"{header}\n\n{summary}"}] + keep
    agent.store.save(s)
    return {"ok": True, "summary": summary, "before": before, "after": len(s.messages)}


async def init_agents_md(agent: "Agent") -> dict:
    """Phân tích workspace → sinh AGENTS.md (kiểu /init của Claude Code/OpenCode)."""
    from . import llm, tools as _tools

    ws = agent.workspace
    overview_parts = [await _tools.execute_tool("list_dir", {"path": "."}, ws)]
    sample = []
    code_exts = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".md",
                 ".json", ".toml", ".yaml", ".yml", ".html", ".css")
    try:
        for f in _tools._iter_files(ws):
            if f.suffix.lower() in code_exts and f.stat().st_size < 60_000:
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    head = "\n".join(text.splitlines()[:50])
                    sample.append(f"--- {f.relative_to(ws)} ---\n{head}")
                except Exception:
                    pass
            if len(sample) >= 8:
                break
    except Exception:
        pass
    overview = overview_parts[0]["output"][:2500] + "\n\n" + "\n\n".join(sample)[:8000]

    demo = config.get_api_key() is None
    if demo:
        content = (f"# AGENTS.md — quy tắc dự án\n\n"
                   f"(Sinh ở DEMO MODE — chưa có API key. Nhập key rồi chạy /init lại "
                   f"để có bản phân tích thật.)\n\n"
                   f"## Cấu trúc\n- Workspace: {ws.name}\n\n"
                   f"## Quy tắc\n- Viết code rõ ràng, có chú thích\n")
    else:
        prompt = (
            "Analyze this project workspace and write its AGENTS.md — the rule file "
            "an AI coding agent reads every session (same convention as Codex/OpenCode). "
            "Include: 1) project overview (2-3 sentences), 2) structure notes, "
            "3) setup/run/test commands, 4) code conventions and rules the agent must "
            "follow. Max 60 lines. Output ONLY the markdown file content, no commentary."
            f"\n\n=== WORKSPACE OVERVIEW ===\n{overview}")
        parts = []
        try:
            async for ev in llm.stream_chat(
                    [{"role": "system", "content": "You write concise, high-signal AGENTS.md files."},
                     {"role": "user", "content": prompt}],
                    tools=None, model=agent.model, temperature=0.3):
                if ev["type"] == "delta":
                    parts.append(ev["text"])
        except llm.LLMError as e:
            return {"ok": False, "message": f"Không sinh được AGENTS.md: {e}"}
        content = "".join(parts).strip()
        if not content:
            return {"ok": False, "message": "LLM không trả về nội dung — thử lại"}
    target = ws / "AGENTS.md"
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target), "content": content}


async def run_batch(store: SessionStore, tasks: list[dict], demo: bool = False):
    """Parallel sub-agents. tasks: [{prompt, model?, title?}] (tối đa 5).

    Yields: task_created, task_event {index, event}, batch_done {tasks}.
    """
    import asyncio as _aio

    tasks = [t for t in tasks if (t.get("prompt") or "").strip()][:5]
    created = []
    for i, t in enumerate(tasks):
        prompt = t["prompt"].strip()
        model = (t.get("model") or "").strip()
        title = t.get("title") or f"Task {i + 1}: {prompt[:40]}"
        s = store.create(model=model, title=title)
        created.append((i, s, prompt, model))
        yield {"type": "task_created", "index": i, "session_id": s.id,
               "title": s.title, "model": model}

    queue: _aio.Queue = _aio.Queue()

    async def pump(i: int, sid: str, prompt: str, model: str) -> None:
        try:
            ag = Agent(store, sid, model=model or None)
            src = send_demo(ag, prompt) if demo else ag.send(prompt)
            async for ev in src:
                await queue.put((i, ev))
        except Exception as e:
            await queue.put((i, {"type": "error", "message": str(e)}))
        finally:
            await queue.put((i, {"type": "task_done", "index": i, "session_id": sid}))

    runners = [_aio.create_task(pump(i, s.id, p, m)) for i, s, p, m in created]
    remaining = len(runners)
    while remaining:
        i, ev = await queue.get()
        if ev["type"] == "task_done":
            remaining -= 1
        yield {"type": "task_event", "index": i, "event": ev}
    for r in runners:
        r.cancel()
    yield {"type": "batch_done",
           "tasks": [{"index": i, "session_id": s.id, "title": s.title, "model": m}
                     for i, s, p, m in created]}


async def run_battle(store: SessionStore, prompt: str, models: list[str],
                     demo: bool = False):
    """⚔ Battle: cùng 1 prompt chạy trên nhiều model song song (mỗi model 1 session + workspace)."""
    models = [m.strip() for m in models if m.strip()][:4]
    if not models:
        models = [config.get_model()]
    tasks = [{"prompt": prompt, "model": m,
              "title": f"⚔ {m.split('/')[-1]}: {prompt[:36]}"} for m in models]
    async for ev in run_batch(store, tasks, demo=demo):
        yield ev


# ---------------------------------------------------------------------------
# Demo mode — scripted events used when no API key is configured.
# It REALLY executes the tools so the file tree populates.
# ---------------------------------------------------------------------------
async def send_demo(agent: Agent, user_text: str):
    import asyncio as _aio
    import json as _json

    s = agent.session
    s.messages.append({"role": "user", "content": user_text})
    if s.title == "New session":
        s.title = user_text.strip().replace("\n", " ")[:60] or "New session"
    agent.store.save(s)

    yield {"type": "reasoning_delta",
           "text": "Demo mode: chưa có API key. Tôi sẽ chạy một kịch bản mẫu để bạn "
                   "thấy cách agent làm việc: ghi file → chạy lệnh → tổng kết."}
    await _aio.sleep(0.4)
    demo_text = (
        f"Đây là **chế độ Demo** (chưa cấu hình API key OpenRouter) — nhưng mọi thứ "
        f"bạn thấy đều chạy thật trong workspace `{agent.workspace.name}`.\n\n"
        "Tôi sẽ tạo một script Python nhỏ rồi chạy nó để minh họa vòng lặp agent:"
    )
    yield {"type": "assistant_delta", "text": demo_text}
    yield {"type": "assistant_message", "content": demo_text, "tool_calls": None}
    s.messages.append({"role": "assistant", "content": demo_text})

    args1 = {"path": "hello_forge.py",
             "content": ("# Created by Forge Agent (demo mode)\n"
                         "import platform\n\n"
                         "print('Hello from Forge Agent!')\n"
                         "print('Python:', platform.python_version())\n"
                         "for i in range(1, 4):\n"
                         "    print(f'  count {i}')\n")}
    tc1 = {"id": "demo-1", "type": "function",
           "function": {"name": "write_file",
                        "arguments": _json.dumps({"path": args1["path"]})}}
    s.messages.append({"role": "assistant", "content": None, "tool_calls": [tc1]})
    yield {"type": "tool_start", "id": tc1["id"], "name": "write_file", "args": args1}
    result = await tools.execute_tool("write_file", args1, agent.workspace)
    yield {"type": "tool_result", "id": tc1["id"], "name": "write_file",
           "args": args1, "ok": result["ok"], "output": result["output"]}
    s.messages.append({"role": "tool", "tool_call_id": tc1["id"], "content": result["output"]})
    await _aio.sleep(0.3)

    import sys as _sys
    args2 = {"command": f'"{_sys.executable}" hello_forge.py'}
    tc2 = {"id": "demo-2", "type": "function",
           "function": {"name": "run_command",
                        "arguments": _json.dumps({"command": args2["command"]})}}
    s.messages.append({"role": "assistant", "content": None, "tool_calls": [tc2]})
    yield {"type": "tool_start", "id": tc2["id"], "name": "run_command", "args": args2}
    result = await tools.execute_tool("run_command", args2, agent.workspace)
    yield {"type": "tool_result", "id": tc2["id"], "name": "run_command",
           "args": args2, "ok": result["ok"], "output": result["output"]}
    s.messages.append({"role": "tool", "tool_call_id": tc2["id"], "content": result["output"]})
    await _aio.sleep(0.3)

    final = ("Xong! ✅ Trong 1 lượt việc, tôi đã:\n\n"
             "1. `write_file` → tạo `hello_forge.py`\n"
             "2. `run_command` → chạy script, thấy output thật\n\n"
             "Bạn có thể mở tab **Files** bên phải để xem file vừa tạo. "
             "Để dùng agent thật, vào **⚙ Settings** và nhập API key của "
             "[OpenRouter](https://openrouter.ai/keys) — sau đó mọi prompt của bạn "
             "sẽ được xử lý bởi model thật (Claude, GPT, Gemini, DeepSeek…).")
    for ch in [final[i:i + 8] for i in range(0, len(final), 8)]:
        yield {"type": "assistant_delta", "text": ch}
        await _aio.sleep(0.02)
    yield {"type": "assistant_message", "content": final, "tool_calls": None}
    s.messages.append({"role": "assistant", "content": final})
    agent.store.save(s)
    yield {"type": "turn_end", "usage": None, "message_count": len(s.messages)}
