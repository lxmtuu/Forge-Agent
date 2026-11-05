"""The agent loop: user msg -> LLM (stream) -> tool calls -> results -> ... -> final answer.

Emits UI-friendly events consumed by both the CLI and the web server:
  reasoning_delta, assistant_delta, tool_start, tool_result,
  assistant_message, turn_end, error
"""
import datetime
import platform
import time
import traceback
from pathlib import Path

from . import config, guard, llm, tools
from .auditlog import log_tool, monotonic_ms
from .llm import LLMError
from .mcp import manager as mcp_manager
from .session import Session, SessionStore

MAX_ITERATIONS = 30
MAX_SUBAGENTS_PER_TURN = 6   # chống phình (Anthropic: lead từng spawn 50 subagent vô ích)
MAX_PARALLEL_SUBAGENTS = 3   # fan-out song song tối đa cùng lúc

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

ARCHITECT_PLAN_PROMPT = (
    "Hãy lập KẾ HOẠCH triển khai ngắn gọn (tối đa ~200 từ): mục tiêu 1 dòng, "
    "các bước đánh số (kể cả file sẽ tạo/sửa), rủi ro nếu có. "
    "KHÔNG viết code, KHÔNG dùng tool — chỉ kế hoạch."
)
ARCHITECT_EXEC_PROMPT = (
    "Thực hiện NGAY kế hoạch trên theo từng bước, dùng tool khi cần. "
    "Không hỏi lại, không lập kế hoạch mới — nếu gặp chướng ngại nhỏ thì tự quyết và đi tiếp."
)
READ_ONLY_TOOLS = {"list_dir", "read_file", "search_files", "lsp_diagnostics", "lsp_symbols",
                   "lsp_definition", "lsp_references", "lsp_search_symbols",
                   "fetch_url", "check_background"}
CHAT_MODES = ("direct", "agent", "plan", "architect")


def _agents_md_block(workspace: Path) -> str:
    """Đọc quy tắc dự án: AGENTS.md > AGENTS.txt > CLAUDE.md (chuẩn Codex/OpenCode/Claude Code)."""
    from .context_files import load_with_imports
    blocks = []
    for name in ("AGENTS.md", "AGENTS.txt", "CLAUDE.md"):
        p = workspace / name
        if p.is_file():
            try:
                text = load_with_imports(p)[:4000]
                if text.strip():
                    blocks.append(f"=== PROJECT INSTRUCTIONS ({name}) — follow strictly ===\n{text}")
                    break  # chỉ 1 file quy tắc cấp dự án (ưu tiên cao nhất)
            except Exception:  # noqa: S110, BLE001 — tệp quy tắc hỏng không được làm sập chat
                pass
    # quy tắc toàn cục của người dùng (nếu có)
    try:
        g = config.DATA_DIR / "AGENTS.md"
        if g.is_file():
            text = load_with_imports(g)[:2000]
            if text.strip():
                blocks.append(f"=== GLOBAL USER RULES (data/AGENTS.md) ===\n{text}")
    except Exception:  # noqa: S110, BLE001 — biên never-raise như auditlog
        pass
    if not blocks:
        return ""
    return "\n" + "\n\n".join(blocks) + "\n"


class Agent:
    def __init__(self, store: SessionStore, session_id: str, model: str | None = None,
                 depth: int = 0):
        self.depth = depth
        self.store = store
        s0 = store.get(session_id)
        if s0 is None:
            raise ValueError(f"Session {session_id} not found")
        self.session: Session = s0  # narrow cho mypy: sau raise trên, luôn khác None
        if model:
            self.session.model = model
        self.model = self.session.model or config.get_model()
        self.workspace: Path = store.workspace(session_id)

    async def _llm_with_fallback(self, messages, tools, model):
        """stream_chat + availability fallback: 402/429/5xx → model dự phòng 1 lần.

        Chỉ fallback khi stream CHƯA yield gì (tránh nhân đôi nội dung nếu model
        chết giữa chừng sau vài delta — khi đó raise cho vòng lặp xử lý lỗi)."""
        cur = llm.resolve_model(model)
        fb = None
        reason = ""
        yielded_any = False
        try:
            async for ev in llm.stream_chat(messages, tools=tools, model=model):
                yielded_any = True
                yield ev
            return
        except llm.LLMError as e:
            if yielded_any:
                raise
            fb = llm.pick_fallback(cur, e)
            if not fb:
                raise
            reason = str(e)[:200]
        yield {"type": "model_fallback", "from": cur, "to": fb, "reason": reason}
        async for ev in llm.stream_chat(messages, tools=tools, model=fb):
            yield ev

    async def _run_subagent(self, tc_id: str, task: str, sub_model: str | None,
                            isolation: str = "shared"):
        """Chạy sub-agent: phiên mới + context hoàn toàn riêng.

        isolation="worktree": sub làm việc trong bản sao git-worktree từ checkpoint
        của cha (B2) — sửa/xoá không đụng workspace cha; báo cáo kèm hướng gộp/bỏ.
        """
        sub_sid = self.store.create(model=sub_model or "", title=f"\U0001F9E9 {task[:46]}").id
        iso_note = ""
        if isolation == "worktree":
            from . import worktree as fwt
            wt = await fwt.make(self.session.id, sub_sid)
            if wt:
                try:
                    ptr = config.WORKSPACES_DIR / f"{sub_sid}.path"
                    ptr.write_text(wt, encoding="utf-8")
                except OSError:
                    pass
                iso_note = wt
            else:
                iso_note = ""  # không có checkpoint → fallback chia sẻ (an toàn hơn fail)
                yield {"type": "subagent_started", "id": tc_id, "session_id": sub_sid,
                       "task": task[:200], "model": sub_model or "inherit"}
                yield {"type": "subagent_progress", "id": tc_id, "tools": 0,
                       "last_tool": "(worktree không khả dụng — dùng workspace chung)"}
        if iso_note == "" and isolation != "worktree":
            try:
                ptr = config.WORKSPACES_DIR / f"{sub_sid}.path"
                ptr.write_text(str(self.workspace), encoding="utf-8")
            except OSError:
                pass
        yield {"type": "subagent_started", "id": tc_id, "session_id": sub_sid,
               "task": task[:200], "model": sub_model or "inherit"}
        sub = Agent(self.store, sub_sid, model=sub_model or None, depth=self.depth + 1)
        texts: list[str] = []
        n_tools = 0
        error: str | None = None
        try:
            async for ev in sub.send(task):
                t = ev["type"]
                if t == "assistant_message" and ev.get("content"):
                    texts.append(ev["content"])
                elif t == "tool_result":
                    n_tools += 1
                    yield {"type": "subagent_progress", "id": tc_id, "tools": n_tools,
                           "last_tool": ev.get("name")}
                elif t == "error":
                    error = ev.get("message")
        except Exception as e:  # noqa: BLE001
            error = str(e)
        summary = "\n\n".join(t for t in texts if t).strip()[-4000:] or "(subagent không trả lời)"
        if error:
            summary = f"(subagent lỗi: {error})\n" + summary
        if isolation == "worktree" and iso_note:
            from . import worktree as fwt
            stat = await fwt.diff_stat(sub_sid, self.session.id, iso_note)
            tail = (f"\n\n📁 Cô lập worktree: {iso_note}\n{('Diff:\n' + stat) if stat else '(không khác gì điểm rẽ nhánh)'}\n"
                    f"Gộp về đây: /worktree merge {sub_sid} · Bỏ: /worktree discard {sub_sid}")
            summary = summary[:4200] + tail
        yield {"type": "subagent_done", "id": tc_id, "session_id": sub_sid,
               "tools": n_tools, "summary": summary[:300]}
        out = f"KẾT QUẢ SUB-AGENT (phiên {sub_sid}, {n_tools} tool calls):\n\n{summary}"
        yield {"type": "subagent_output", "id": tc_id, "output": out}

    async def _handle_parallel_spawns(self, s, messages, spawn_tcs, turn_state):
        """Chạy đồng thời (tối đa MAX_PARALLEL_SUBAGENTS) các spawn_subagent trong cùng
        một lượt tool_calls — pattern Fan-Out. Tự yield tool_start/progress/tool_result
        và ghi tool messages theo thứ tự gốc."""
        import asyncio as _aio
        import json as _json

        batch = []  # (tc, args, task, resolved_model)
        for tc in spawn_tcs:
            try:
                args = _json.loads(tc["function"].get("arguments") or "{}")
            except _json.JSONDecodeError:
                args = {}
            yield {"type": "tool_start", "id": tc["id"], "name": "spawn_subagent", "args": args}
            task = str(args.get("task", "")).strip()
            if turn_state["spawns"] >= MAX_SUBAGENTS_PER_TURN:
                log_tool(s.id, "spawn_subagent", args, False, source="subagent",
                         note="vượt giới hạn lượt")
                yield {"type": "tool_result", "id": tc["id"], "name": "spawn_subagent",
                       "args": args, "ok": False,
                       "output": f"Đã đạt giới hạn {MAX_SUBAGENTS_PER_TURN} sub-agent "
                                 "trong một lượt — hãy tự hoàn thiện phần còn lại."}
                s.messages.append({"role": "tool", "tool_call_id": tc["id"],
                                   "content": "Đã đạt giới hạn sub-agent trong lượt này."})
                messages.append(s.messages[-1])
            elif not task:
                log_tool(s.id, "spawn_subagent", args, False, source="subagent",
                         note="thiếu task")
                yield {"type": "tool_result", "id": tc["id"], "name": "spawn_subagent",
                       "args": args, "ok": False, "output": "Error: thiếu task cho sub-agent"}
                s.messages.append({"role": "tool", "tool_call_id": tc["id"],
                                   "content": "Error: thiếu task cho sub-agent"})
                messages.append(s.messages[-1])
            else:
                blocked = False
                try:
                    from . import hooks as _hooks
                    pre = await _hooks.pre_tool_use(self.workspace, s.id, "spawn_subagent", args)
                    if pre and pre.get("blocked"):
                        blocked = True
                        reason = pre.get("reason")
                except Exception:
                    pass
                if blocked:
                    log_tool(s.id, "spawn_subagent", args, False, source="hook",
                             note="blocked bởi pre_tool_use")
                    yield {"type": "tool_result", "id": tc["id"], "name": "spawn_subagent",
                           "args": args, "ok": False,
                           "output": f"BLOCKED by hook pre_tool_use: {reason}"}
                    s.messages.append({"role": "tool", "tool_call_id": tc["id"],
                                       "content": f"BLOCKED by hook pre_tool_use: {reason}"})
                    messages.append(s.messages[-1])
                    continue
                turn_state["spawns"] += 1
                resolved = llm.resolve_sub_model(str(args.get("model") or ""), self.model)
                batch.append((tc, args, task, resolved))
        self.store.save(s)

        async def _pump(tc_id: str, task_: str, model_: str | None, q):
            try:
                iso_ = str((_args or {}).get("isolation") or "shared")
                async for ev in self._run_subagent(tc_id, task_, model_, iso_):
                    await q.put(ev)
            except Exception as e:  # noqa: BLE001
                await q.put({"type": "subagent_output", "id": tc_id,
                             "output": f"(subagent lỗi: {e})"})
            finally:
                await q.put(None)

        outputs: dict[str, str] = {}
        for i in range(0, len(batch), MAX_PARALLEL_SUBAGENTS):
            chunk = batch[i:i + MAX_PARALLEL_SUBAGENTS]
            queues: dict[str, _aio.Queue] = {}
            pumps = {}
            for tc, _args, task_, model_ in chunk:
                tc_id_ = tc["id"]
                queues[tc_id_] = _aio.Queue()
                pumps[_aio.create_task(_pump(tc_id_, task_, model_, queues[tc_id_]))] = tc_id_
            pending = set(pumps)
            while pending:
                done, pending = await _aio.wait(pending, return_when=_aio.FIRST_COMPLETED)
                for pmp in done:
                    tcid = pumps[pmp]
                    out = None
                    while True:
                        ev = await queues[tcid].get()
                        if ev is None:
                            break
                        if ev["type"] == "subagent_output":
                            out = ev["output"]
                        else:
                            yield ev
                    outputs[tcid] = out or "(sub-agent không trả kết quả)"
        # tool_result + messages theo thứ tự gốc của batch
        for tc, args, _task, _model in batch:
            out = outputs.get(tc["id"], "(sub-agent không trả kết quả)")
            log_tool(s.id, "spawn_subagent", args,
                     bool(out and "subagent lỗi" not in out[:20]), source="subagent")
            yield {"type": "tool_result", "id": tc["id"], "name": "spawn_subagent",
                   "args": args, "ok": bool(out and "subagent lỗi" not in out[:20]),
                   "output": out}
            s.messages.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
            messages.append(s.messages[-1])
        self.store.save(s)

    def _memory_block(self) -> str:
        """MEMORY.md (workspace + global) — kiến thức các phiên trước, auto-memory."""
        blocks = []
        for label, path, cap in (
            ("WORKSPACE MEMORY (workspace/MEMORY.md)", self.workspace / "MEMORY.md", 2000),
            ("GLOBAL MEMORY (data/MEMORY.md)", config.DATA_DIR / "MEMORY.md", 1000),
        ):
            try:
                if path.is_file():
                    from .context_files import load_with_imports
                    t = load_with_imports(path).strip()
                    if t:
                        blocks.append(f"=== {label} ===\n{t[:cap]}")
            except Exception:
                pass
        if not blocks:
            return ""
        return ("\n\n=== LONG-TERM MEMORY — bài học các phiên trước (tool memory_save "
                "để ghi thêm) ===\n" + "\n\n".join(blocks) + "\n")

    def context_stats(self) -> dict:
        """Mức dùng context hiện tại (cho /context)."""
        chars = len(self._system_message()["content"]) + _conversation_chars(self.session.messages)
        limit = config.get_auto_compact_chars()
        return {
            "messages": len(self.session.messages),
            "chars": chars,
            "est_tokens": chars // 4,
            "limit": limit,
            "percent": (min(100, round(chars * 100 / limit)) if limit else None),
            "memory": (self.workspace / "MEMORY.md").exists()
                      or (config.DATA_DIR / "MEMORY.md").exists(),
        }

    def _skills_block(self) -> str:
        from .skills import skills_block
        return skills_block(self.workspace)

    def _system_message(self, session_extra: str = "") -> dict:
        return {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                date=datetime.date.today().isoformat(),
                platform=f"{platform.system()} {platform.release()} ({platform.machine()}) / Python {platform.python_version()}",
                workspace=str(self.workspace),
                agents_md=_agents_md_block(self.workspace),
            ) + self._memory_block() + self._skills_block() + (session_extra or ""),
        }

    async def send(self, user_text: str, chat_mode: str = "agent", content=None,
                   append_user: bool = True):
        """Run one full user turn; async-generator of events.

        chat_mode: "agent" (full loop) | "direct" (no tools) | "plan" (read-only)
                 | "architect" (model mạnh lập kế hoạch → model rẻ thực thi).
        content: payload lưu vào session — mặc định là user_text; truyền list
        content-parts (multimodal: text + image_url) khi có ảnh đính kèm.
        append_user=False: tin user ĐÃ nằm trong session (flow chỉnh-sửa-chạy-lại
        E5) — không append nữa, không đổi title.
        """
        s = self.session
        if append_user:
            s.messages.append({"role": "user",
                               "content": content if content is not None else user_text})
            if s.title == "New session":
                s.title = user_text.strip().replace("\n", " ")[:60] or "New session"
            self.store.save(s)

        # '# <nội dung>' → quick-memory (chuẩn Claude Code): ghi MEMORY.md, không tốn LLM
        if user_text.startswith("# ") and len(user_text.strip()) > 2:
            from .memory import quick_memory
            yield {"type": "assistant_message",
                   "content": quick_memory(self.workspace, user_text.strip()[2:].strip())}
            yield {"type": "turn_end", "usage": None, "message_count": len(s.messages)}
            return

        if chat_mode not in CHAT_MODES:
            chat_mode = "agent"
        # --- auto-compact: chống tràn context ở phiên dài ---
        acc = config.get_auto_compact_chars()
        if acc and len(s.messages) > 8 and _conversation_chars(s.messages) > acc:
            yield {"type": "compacting", "chars": _conversation_chars(s.messages)}
            cres = await compact_session(self)
            yield {"type": "compacted", "ok": cres.get("ok"),
                   "before": cres.get("before"), "after": cres.get("after")}
        # hooks: session_start — context bổ sung (chạy 1 lần mỗi phiên mỗi tiến trình)
        try:
            from . import hooks as _hooks
            ss_extra = await _hooks.session_start_cache(self.workspace, s.id)
        except Exception as _e:
            print(f"[hooks] session_start lỗi (bỏ qua): {_e}")
            ss_extra = ""
        sys_msg = self._system_message(ss_extra)
        try:
            from . import bus as fbus
            _n = fbus.unread_count(s.id)
            if _n:
                sys_msg["content"] += (f"\n\n=== INBOX: {_n} tin nhắn từ phiên khác — "
                                       "gọi tool check_inbox để đọc ===")
        except Exception as _be:  # noqa: BLE001 — hộp thư hỏng không được làm sập chat
            print(f"[bus] bỏ qua: {_be}")
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

        turn_model = self.model
        if chat_mode == "architect":
            strong = llm.resolve_model("strong")
            yield {"type": "phase", "phase": "plan", "model": strong}
            plan_parts: list[str] = []
            p_usage = None
            async for ev in self._llm_with_fallback(
                    messages + [{"role": "user", "content": ARCHITECT_PLAN_PROMPT}],
                    None, strong):
                if ev["type"] == "delta":
                    plan_parts.append(ev["text"])
                    yield {"type": "assistant_delta", "text": ev["text"]}
                elif ev["type"] == "usage":
                    p_usage = ev["usage"]
                elif ev["type"] == "model_fallback":
                    yield ev
            plan_text = "".join(plan_parts).strip() or "(không có kế hoạch)"
            s.messages.append({"role": "assistant", "content": plan_text})
            messages.append(s.messages[-1])
            messages.append({"role": "user", "content": ARCHITECT_EXEC_PROMPT})
            turn_model = llm.resolve_model("cheap")
            self.store.save(s)
            yield {"type": "phase", "phase": "execute", "model": turn_model,
                   "plan_chars": len(plan_text), "usage": p_usage}

        turn_state = {"spawns": 0}  # số sub-agent đã dùng trong LƯỢT này (mọi vòng lặp)
        try:
            for _ in range(MAX_ITERATIONS):
                content_parts: list[str] = []
                tool_calls: list[dict] | None = None
                usage = None

                async for ev in self._llm_with_fallback(messages, active_specs, turn_model):
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
                    elif et == "model_fallback":
                        yield ev

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

                # ---- fan-out: nhiều spawn_subagent trong CÙNG lượt → chạy song song ----
                handled_ids: set[str] = set()
                spawn_tcs = [tc for tc in tool_calls
                             if tc.get("function", {}).get("name") == "spawn_subagent"] \
                    if chat_mode == "agent" else []
                if len(spawn_tcs) >= 2:
                    handled_ids = {tc["id"] for tc in spawn_tcs}
                    async for _pev in self._handle_parallel_spawns(
                            s, messages, spawn_tcs, turn_state):
                        yield _pev

                for tc in tool_calls:
                    if tc["id"] in handled_ids:
                        continue
                    name = tc["function"]["name"]
                    name = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments") or "{}"
                    import json as _json
                    try:
                        args = _json.loads(raw_args) if raw_args.strip() else {}
                    except _json.JSONDecodeError:
                        args = {"_raw": raw_args}
                    yield {"type": "tool_start", "id": tc["id"], "name": name, "args": args}
                    _t0 = time.monotonic()

                    # ---- hooks: pre_tool_use (exit 2 = chặn, chuẩn Claude Code) ----
                    try:
                        from . import hooks as _hooks
                        pre = await _hooks.pre_tool_use(self.workspace, s.id, name, args)
                        if pre and pre.get("blocked"):
                            result = {"ok": False,
                                      "output": f"BLOCKED by hook pre_tool_use: {pre.get('reason')}"}
                            log_tool(s.id, name, args, False, source="hook", note="blocked bởi pre_tool_use")
                            yield {"type": "tool_result", "id": tc["id"], "name": name,
                                   "args": args, "ok": False, "output": result["output"]}
                            s.messages.append({"role": "tool", "tool_call_id": tc["id"],
                                               "content": result["output"]})
                            messages.append(s.messages[-1])
                            self.store.save(s)
                            continue
                    except Exception as _he:
                        print(f"[hooks] pre_tool_use lỗi (bỏ qua): {_he}")

                    # ---- sub-agent delegation (context riêng, workspace chung) ----
                    if name == "spawn_subagent" and chat_mode == "agent":
                        sub_task = str(args.get("task", "")).strip()
                        if turn_state["spawns"] >= MAX_SUBAGENTS_PER_TURN:
                            result = {"ok": False,
                                      "output": f"Đã đạt giới hạn {MAX_SUBAGENTS_PER_TURN} "
                                                "sub-agent trong một lượt — hãy tự hoàn thiện "
                                                "phần còn lại thay vì giao tiếp."}
                        elif not sub_task:
                            result = {"ok": False, "output": "Error: thiếu task cho sub-agent"}
                        else:
                            turn_state["spawns"] += 1
                            resolved = llm.resolve_sub_model(str(args.get("model") or ""),
                                                             self.model)
                            result = {"ok": False, "output": "sub-agent không trả kết quả"}
                            async for _sev in self._run_subagent(tc["id"], sub_task, resolved):
                                if _sev["type"] == "subagent_output":
                                    result = {"ok": True, "output": _sev["output"]}
                                else:
                                    yield _sev
                        log_tool(s.id, name, args, bool(result.get("ok", False)),
                                 monotonic_ms(_t0),
                                 "mcp" if name in mcp_routing else "internal")
                        ev = {"type": "tool_result", "id": tc["id"], "name": name,
                              "args": args, "ok": result.get("ok", False),
                              "output": result.get("output", "")}
                        yield ev
                        s.messages.append({"role": "tool", "tool_call_id": tc["id"],
                                           "content": result.get("output", "")})
                        messages.append(s.messages[-1])
                        self.store.save(s)
                        continue

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
                                log_tool(s.id, name, args, False, source="denied",
                                         note="người dùng từ chối (guard)")
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
                        # ---- v0.17: tool MCP chưa allowlist phải được duyệt ----
                        _srv, _tool = mcp_routing[name]
                        from . import approvals as _ap
                        from . import connectors as _conn
                        _mode = config.load_config().get("approval_mode", "guarded")
                        _decision = "approve"
                        if (not _conn.tool_allowed(_srv.name, _tool)) and _mode != "auto":
                            _disp = f"mcp:{_srv.name}:{_tool}"
                            aid = _ap.create(_disp, "warn",
                                             ["Tool MCP — hành động thật trên dịch vụ ngoài"])
                            yield {"type": "approval_request", "id": aid, "command": _disp,
                                   "level": "warn",
                                   "reasons": [f"Tool MCP chưa allowlist — "
                                               f"/connectors allow {_srv.name} {_tool} để bỏ duyệt"]}
                            _decision = await _ap.wait(aid)
                            yield {"type": "approval_decision", "id": aid, "decision": _decision}
                        if _decision == "approve_always":
                            _conn.allow(_srv.name, _tool)
                        if _decision == "deny":
                            log_tool(s.id, name, args, False, source="denied",
                                     note="người dùng từ chối (MCP)")
                            result = {"ok": False, "output": (
                                "User DENIED this MCP tool call. Do not retry it unchanged; "
                                "explain and offer to allow it via /connectors allow.")}
                        else:
                            # tool MCP có thể kích hoạt elicitation/create giữa chừng —
                            # vừa chờ kết quả vừa đẩy event elicitation_request ra UI
                            import asyncio as _aio2

                            from . import elicitations as _el
                            seen: set[str] = set()
                            base = set(_el.PENDING.keys())
                            task = _aio2.create_task(
                                mcp_manager.call_namespaced(mcp_routing, name, args))
                            while not task.done():
                                fresh = [e for e in _el.PENDING if e not in base and e not in seen]
                                for eid in fresh:
                                    seen.add(eid)
                                    ent = _el.PENDING.get(eid) or {}
                                    yield {"type": "elicitation_request", "id": eid,
                                           "server": ent.get("server"), "message": ent.get("message"),
                                           "schema": ent.get("schema"), "url": ent.get("url")}
                                await _aio2.sleep(0.12)
                            result = task.result()
                            if seen:
                                self.store.save(s)
                    elif name in ("send_message", "check_inbox"):
                        # F2 cross-session messaging — cần store/own sid nên xử lý ở agent
                        from . import bus as fbus
                        if name == "send_message":
                            to_sid = str(args.get("to_session", "")).strip()
                            text = str(args.get("text", "")).strip()
                            if not to_sid or not text:
                                result = {"ok": False,
                                          "output": "Error: cần 'to_session' (id phiên đích) và 'text'."}
                            elif to_sid == s.id:
                                result = {"ok": False, "output": "Error: không gửi cho chính mình."}
                            elif self.store.get(to_sid) is None:
                                result = {"ok": False,
                                          "output": f"Error: không có phiên '{to_sid}'."}
                            else:
                                fbus.send(to_sid, s.id, text)
                                result = {"ok": True,
                                          "output": f"Đã gửi tới {to_sid} — phiên đích sẽ thấy ở lượt kế tiếp."}
                        else:
                            rows = fbus.inbox(s.id)
                            if rows:
                                out = "\n\n".join(
                                    f"[{str(r['ts'])[11:16]} từ {r['from']}] {r['text']}"
                                    for r in rows)
                                result = {"ok": True, "output": f"📥 {len(rows)} tin:\n{out}"}
                            else:
                                result = {"ok": True, "output": "(hộp thư trống)"}
                    else:
                        result = await tools.execute_tool(name, args, self.workspace, override=override)
                    # hooks: post_tool_use — nối nhận xét hook vào output cho LLM
                    try:
                        from . import hooks as _hooks
                        extra = await _hooks.post_tool_use(self.workspace, s.id, name, args,
                                                           str(result.get("output", "")))
                        if extra:
                            result["output"] = str(result.get("output", "")) + "\n" + extra
                    except Exception as _he:
                        print(f"[hooks] post_tool_use lỗi (bỏ qua): {_he}")
                    # todo_write → phát event checklist cho 3 UI render tiến độ
                    if name == "todo_write":
                        try:
                            import json as _jtodo
                            _tp = self.workspace / ".forge" / "todo.json"
                            yield {"type": "todo_update",
                                   "items": _jtodo.loads(_tp.read_text(encoding="utf-8"))}
                        except Exception:
                            pass
                    log_tool(s.id, name, args, bool(result["ok"]), monotonic_ms(_t0),
                             "mcp" if name in mcp_routing else "internal")
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
        # chi phí $ ước lượng (giá OpenRouter) — lỗi/ thiếu giá → None, không chạm chat
        cost_usd = None
        if total_usage:
            try:
                from . import cost as _cost
                cost_usd = await _cost.estimate(self.model, total_usage)
            except Exception:
                cost_usd = None
            if cost_usd is not None:
                try:
                    s.usage = dict(s.usage or {})
                    s.usage["cost_usd"] = round(float(s.usage.get("cost_usd") or 0) + cost_usd, 6)
                except Exception:
                    pass
        self.store.save(s)
        yield {"type": "turn_end", "usage": total_usage, "session_usage": s.usage,
               "cost_usd": cost_usd, "message_count": len(s.messages)}


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
    from . import llm
    from . import tools as _tools

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

    # '# <nội dung>' → quick-memory cũng chạy được ở demo mode
    if user_text.startswith("# ") and len(user_text.strip()) > 2:
        from .memory import quick_memory
        yield {"type": "assistant_message",
               "content": quick_memory(agent.workspace, user_text.strip()[2:].strip())}
        yield {"type": "turn_end", "usage": None, "message_count": len(s.messages)}
        return

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
    log_tool(agent.session.id, "write_file", args1, result["ok"],
             source="demo")
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
    log_tool(agent.session.id, "run_command", args2, result["ok"],
             source="demo")
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
