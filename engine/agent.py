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
    """Đọc quy tắc dự án từ AGENTS.md (chuẩn Claude Code/Codex/OpenCode)."""
    for name in ("AGENTS.md", "AGENTS.txt"):
        p = workspace / name
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")[:4000]
                if text.strip():
                    return f"\n=== PROJECT INSTRUCTIONS ({name}) — follow strictly ===\n{text}\n"
            except Exception:
                pass
    return ""


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

    async def send(self, user_text: str, chat_mode: str = "agent"):
        """Run one full user turn; async-generator of events.

        chat_mode: "agent" (full loop) | "direct" (no tools) | "plan" (read-only).
        """
        s = self.session
        s.messages.append({"role": "user", "content": user_text})
        if s.title == "New session":
            s.title = user_text.strip().replace("\n", " ")[:60] or "New session"
        self.store.save(s)

        if chat_mode not in CHAT_MODES:
            chat_mode = "agent"
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
                    yield {"type": "tool_result", "id": tc["id"], "name": name,
                           "args": args, "ok": result["ok"], "output": result["output"]}
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
