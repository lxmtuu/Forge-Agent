"""Forge TUI — full-screen terminal app (opencode-style): chat + sessions + files + status."""
from __future__ import annotations

import asyncio
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, ListView, ListItem, Markdown, Static, Tree
from rich.text import Text as RichText

from engine import approvals, config, tools
from engine.agent import Agent, compact_session, init_agents_md, send_demo
from engine.session import SessionStore

store = SessionStore()


def _walk_tree(node, path, depth=0):
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except Exception:
        return
    for e in entries:
        if e.name in tools.SKIP_DIRS or e.name.startswith("."):
            continue
        if e.is_dir():
            if depth < 3:
                branch = node.add(f"📁 {e.name}/", expand=False)
                _walk_tree(branch, e, depth + 1)
        else:
            node.add_leaf(f"📄 {e.name}")


def _diff_rich(diff: str, max_lines: int = 40) -> RichText:
    """Unified diff → rich Text màu (+ xanh, - đỏ, @@ cyan)."""
    out = RichText()
    lines = diff.split("\n")
    for i, ln in enumerate(lines[:max_lines]):
        if ln.startswith("+++") or ln.startswith("---"):
            out.append(ln + "\n", style="dim")
        elif ln.startswith("@@"):
            out.append(ln + "\n", style="cyan")
        elif ln.startswith("+"):
            out.append(ln + "\n", style="green")
        elif ln.startswith("-"):
            out.append(ln + "\n", style="red")
        else:
            out.append(ln + "\n", style="grey50")
    if len(lines) > max_lines:
        out.append(f"… còn {len(lines) - max_lines} dòng (mở web để xem đầy đủ)\n",
                   style="italic grey50")
    return out


class ApprovalModal(ModalScreen[None]):
    """Xin phê duyệt lệnh shell — 3 lựa chọn."""
    BINDINGS = [("escape", "deny", "Từ chối")]

    def __init__(self, approval_id: str, command: str, level: str, reasons: list[str]):
        super().__init__()
        self.approval_id = approval_id
        self.command = command
        self.level = level
        self.reasons = reasons

    def compose(self) -> ComposeResult:
        with Vertical(id="appr-box"):
            yield Static(f"🔔 Cần phê duyệt lệnh shell  [b][{self.level}][/b]", id="appr-title")
            yield Static(self.command, id="appr-cmd")
            yield Static("Lý do: " + (", ".join(self.reasons) or "—"), id="appr-reasons")
            with Horizontal(id="appr-actions"):
                yield Button("✓ Chấp nhận", id="approve", variant="success")
                yield Button("✓✓ Luôn cho phép", id="approve_always", variant="primary")
                yield Button("✕ Từ chối", id="deny", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        approvals.resolve(self.approval_id, event.button.id or "deny")
        self.app.pop_screen()

    def action_deny(self) -> None:
        approvals.resolve(self.approval_id, "deny")
        self.app.pop_screen()


class ElicitModal(ModalScreen[None]):
    """Hộp thoại trả lời elicitation MCP: accept (form) / decline / cancel."""

    BINDINGS = [("escape", "cancel_elicit", "Đóng (cancel)")]

    def __init__(self, eid: str, server: str, message: str, schema: dict | None, url: str | None):
        super().__init__()
        self.eid = eid
        self.server = server
        self.message = message
        self.schema = schema or {}
        self.url = url
        self.inputs: dict[str, Input] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="elic-box"):
            yield Static(f"🔔 [b]{self.server}[/b] cần thông tin (elicitation)", id="elic-title")
            yield Static(self.message or "—", id="elic-msg")
            if self.url:
                yield Static(f"URL (không tự mở): {self.url}", id="elic-url")
            for name, prop in (self.schema.get("properties") or {}).items():
                lbl = f"{prop.get('description') or name} ({name})"
                if name in (self.schema.get("required") or []):
                    lbl += " *"
                yield Static(lbl, classes="elic-lbl")
                inp = Input(placeholder=str(prop.get("type", "string")), id=f"elic-{name}")
                self.inputs[name] = inp
                yield inp
            with Horizontal(id="elic-actions"):
                yield Button("✓ Gửi", id="elic-accept", variant="success")
                yield Button("✕ Từ chối", id="elic-decline", variant="error")
                yield Button("Đóng", id="elic-cancel")

    def _content(self) -> dict:
        from engine.elicitations import SECRET_HINTS  # noqa: F401  (chỉ để đối chiếu UI)
        content = {}
        for name, prop in (self.schema.get("properties") or {}).items():
            raw = self.inputs[name].value.strip()
            t = prop.get("type", "string")
            if t == "number":
                try:
                    content[name] = float(raw) if raw else 0
                except ValueError:
                    content[name] = 0
            elif t == "boolean":
                content[name] = raw.lower() in ("y", "yes", "true", "1", "co", "có")
            else:
                content[name] = raw
        return content

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from engine import elicitations
        bid = event.button.id or "elic-cancel"
        if bid == "elic-accept":
            elicitations.resolve(self.eid, "accept", self._content())
        elif bid == "elic-decline":
            elicitations.resolve(self.eid, "decline")
        else:
            elicitations.resolve(self.eid, "cancel")
        self.app.pop_screen()

    def action_cancel_elicit(self) -> None:
        from engine import elicitations
        elicitations.resolve(self.eid, "cancel")
        self.app.pop_screen()


class ForgeTUI(App):
    TITLE = "⚡ Forge Agent"
    SUB_TITLE = "AI coding agent · TUI"

    CSS = """
    #main { height: 1fr; }
    #sessions { width: 30; border-right: heavy #2a2b33; background: #191a1e; }
    #sessions > .--item { padding: 0 1; }
    #files { width: 32; border-left: heavy #2a2b33; background: #191a1e; }
    #center { width: 1fr; background: #131316; }
    #chat { height: 1fr; padding: 1 2; }
    #status { height: 1; padding: 0 2; color: #9b99a3; background: #191a1e; }
    .user-msg { border: round #2a2b33; margin: 1 0; padding: 0 1; }
    .sys-line { color: #6d6b76; }
    .tool-line { color: #5cb8c9; }
    .tool-ok { color: #71c290; }
    .tool-bad { color: #e5534b; }
    .reasoning { color: #6d6b76; text-style: italic; }
    Markdown { margin: 0 0 1 0; }
    #appr-box { width: 72; margin: 1 2; padding: 1 2; border: heavy #d9a757; background: #212228; }
    #appr-title { color: #d9a757; margin-bottom: 1; }
    #appr-cmd { color: #f0c9a8; margin-bottom: 1; }
    #appr-reasons { color: #9b99a3; margin-bottom: 1; }
    #appr-actions { height: 3; align: center middle; }
    #appr-actions Button { margin: 0 1; }
    #elic-box { width: 76; margin: 1 2; padding: 1 2; border: heavy #d9a757; background: #212228; }
    #elic-title { color: #d9a757; margin-bottom: 1; }
    #elic-msg { color: #e9e7e2; margin-bottom: 1; }
    #elic-url { color: #5cb8c9; margin-bottom: 1; }
    .elic-lbl { color: #9b99a3; }
    #elic-actions { height: 3; align: center middle; margin-top: 1; }
    #elic-actions Button { margin: 0 1; }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Thoát"),
        ("ctrl+n", "new_session", "Phiên mới"),
        ("ctrl+r", "refresh_files", "Refresh files"),
        ("ctrl+m", "switch_mode", "Đổi mode"),
    ]
    AUTO_FOCUS = "#prompt"

    def __init__(self):
        super().__init__()
        self.sid: str | None = None
        self.agent: Agent | None = None
        self.session_ids: list[str] = []
        self._md_widget = None
        self._md_text = ""
        self._reasoning_widget = None
        self._reasoning_text = ""
        self._tool_widgets: dict[str, Static] = {}
        self.busy = False
        self.chat_mode = "agent"

    # ---------------------------------------------------------------- UI
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            yield ListView(id="sessions")
            with Vertical(id="center"):
                yield VerticalScroll(id="chat")
                yield Input(placeholder="Nhập nhiệm vụ…  (/help = danh sách lệnh)", id="prompt")
                yield Static("", id="status")
            yield Tree("WORKSPACE", id="files")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_sessions(select_latest=True)
        self.query_one("#prompt", Input).focus()

    # --------------------------------------------------------- sessions
    def refresh_sessions(self, select_latest: bool = False) -> None:
        lv = self.query_one("#sessions", ListView)
        lv.clear()
        self.session_ids = []
        for meta in store.list()[:30]:
            self.session_ids.append(meta["id"])
            lv.append(ListItem(Label(f"{meta['title'][:26]}", classes="--item"),
                               name=meta["id"]))
        if select_latest:
            rows = store.list()
            if rows:
                self.select_session(rows[0]["id"])
            else:
                self.new_session()

    def select_session(self, sid: str) -> None:
        self.sid = sid
        self.agent = Agent(store, sid)
        self.render_history()
        self.refresh_files()
        self.update_status()

    def new_session(self) -> None:
        s = store.create()
        self.refresh_sessions(select_latest=False)
        self.select_session(s.id)
        lv = self.query_one("#sessions", ListView)
        lv.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        try:
            idx = event.list_view.index
            if idx is not None and 0 <= idx < len(self.session_ids):
                self.select_session(self.session_ids[idx])
        except Exception:
            pass

    # ----------------------------------------------------------- render
    def _scroll_chat(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    def add_user(self, text: str) -> None:
        w = Static(f"▌ {text}", classes="user-msg")
        self.query_one("#chat", VerticalScroll).mount(w)
        self._scroll_chat()

    def add_line(self, text: str, cls: str = "sys-line") -> Static:
        w = Static(text, classes=cls)
        self.query_one("#chat", VerticalScroll).mount(w)
        self._scroll_chat()
        return w

    def begin_assistant(self) -> None:
        self._md_widget = Markdown("")
        self._md_text = ""
        self.query_one("#chat", VerticalScroll).mount(self._md_widget)

    def render_history(self) -> None:
        self.query_one("#chat", VerticalScroll).remove_children()
        self._md_widget = None
        self._reasoning_widget = None
        self._tool_widgets = {}
        s = store.get(self.sid)
        if not s:
            return
        for m in s.messages:
            role = m.get("role")
            if role == "user":
                self.add_user(m.get("content") or "")
            elif role == "assistant":
                if m.get("content"):
                    w = Markdown(m["content"])
                    self.query_one("#chat", VerticalScroll).mount(w)
                for tc in m.get("tool_calls") or []:
                    name = tc["function"]["name"]
                    self.add_line(f"⚙ {name}", cls="tool-line")
            elif role == "tool":
                out = (m.get("content") or "").replace("\n", " ")[:110]
                cls = "tool-ok" if not (m.get("content") or "").startswith(("Error", "BLOCKED")) else "tool-bad"
                self.add_line(f"   {out}", cls=cls)
        self._scroll_chat()

    def refresh_files(self) -> None:
        tree = self.query_one("#files", Tree)
        tree.clear()
        if self.agent and self.agent.workspace.exists():
            _walk_tree(tree.root, self.agent.workspace)
            tree.root.expand()

    def update_status(self) -> None:
        s = store.get(self.sid) if self.sid else None
        key = config.get_api_key()
        model = (s.model if s and s.model else config.get_model())
        toks = (s.usage or {}).get("total_tokens", 0) if s else 0
        mode = config.load_config().get("approval_mode", "guarded")
        state = "DEMO" if not key else f"key ✓ {config.mask_key(key)}"
        mode_ico = {"direct": "💬", "agent": "🤖", "plan": "📋"}.get(self.chat_mode, "")
        self.query_one("#status", Static).update(
            f"{mode_ico} {self.chat_mode} · {model} · {state} · duyệt {mode} · tokens {toks}"
            + (" · đang chạy…" if self.busy else ""))

    # ------------------------------------------------------------- input
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.query_one("#prompt", Input).value = ""
        if not text:
            return
        if text.startswith("/"):
            await self.handle_command(text)
            return
        if self.busy:
            self.add_line("⏳ Đang xử lý — chờ xong đã!", cls="sys-line")
            return
        self.run_turn(text)

    async def handle_command(self, text: str) -> None:
        cmd, _, arg = text.partition(" ")
        arg = arg.strip()
        if cmd == "/help":
            self.add_line("Lệnh: /new /key <api> /model <m> /perm guarded|ask|auto "
                          "/plan /agent /direct /undo /compact [gợi ý] /init /fork /export [file] "
                          "/profile [tên] /context /memory [clear] /doctor /agents /run <tên> <task> "
                          "/usage /files /review [file|A...B] /diff [file] /quit · "
                          "@file.py đính file · «# ghi nhớ» → MEMORY.md · "
                          "custom: .forge/commands + .forge/agents → /<tên> hoặc /run <tên>",
                          cls="sys-line")
        elif cmd == "/new":
            self.new_session()
        elif cmd == "/key":
            config.save_config({"api_key": arg})
            self.add_line(f"✅ Đã lưu key {config.mask_key(arg)}", cls="tool-ok")
        elif cmd == "/model":
            config.save_config({"model": arg})
            self.add_line(f"✅ Model → {arg}", cls="tool-ok")
        elif cmd == "/mode" or cmd == "/perm":
            if arg in ("guarded", "ask", "auto"):
                config.save_config({"approval_mode": arg})
                self.add_line(f"✅ Chế độ duyệt → {arg}", cls="tool-ok")
            else:
                self.add_line("Dùng: /perm guarded|ask|auto", cls="sys-line")
        elif cmd in ("/plan", "/agent", "/direct"):
            if self.busy:
                self.add_line("⏳ Đang chạy — không đổi mode bây giờ.", cls="sys-line")
            else:
                self.chat_mode = cmd[1:]
                icons = {"direct": "💬", "agent": "🤖", "plan": "📋"}
                self.add_line(icons[self.chat_mode] + f" Chế độ chat → {self.chat_mode}", cls="tool-ok")
        elif cmd == "/profile":
            from engine import config as _cfg
            if not arg:
                profs = ", ".join(sorted(_cfg.list_profiles().keys())) or "(chưa định nghĩa)"
                cur = _cfg.load_config().get("active_profile") or "(mặc định)"
                self.add_line(f"Profile hiện tại: {cur} · có sẵn: {profs} · "
                              "định nghĩa trong data/config.json → \"profiles\"", cls="sys-line")
            elif _cfg.set_profile(arg):
                eff = _cfg.load_config()
                self.add_line(f"✅ Profile → {arg} (model {eff.get('model', '?')}, "
                              f"duyệt {eff.get('approval_mode', 'guarded')})", cls="tool-ok")
            else:
                self.add_line(f"⚠ Không có profile «{arg}» — xem /profile", cls="tool-bad")
        elif cmd == "/undo":
            await self._cmd_undo()
        elif cmd == "/compact":
            await self._cmd_compact(arg)
        elif cmd == "/init":
            await self._cmd_init()
        elif cmd == "/usage":
            s = store.get(self.sid) if self.sid else None
            u = (s.usage if s else {}) or {}
            self.add_line(f"🔢 Tokens phiên này: {u.get('total_tokens', 0)} "
                          f"(↑{u.get('prompt_tokens', 0)} ↓{u.get('completion_tokens', 0)})", cls="sys-line")
        elif cmd == "/files":
            self.refresh_files()
        elif cmd in ("/quit", "/exit"):
            self.exit()
        elif cmd == "/context":
            if self.agent:
                ctx = self.agent.context_stats()
                pct = f"{ctx['percent']}%" if ctx["percent"] is not None else "∞"
                lim = f"{ctx['limit']:,}" if ctx["limit"] else "không giới hạn"
                self.add_line(f"🧠 Context: {pct} ({ctx['chars']:,} ký tự ≈ {ctx['est_tokens']:,} "
                              f"tokens / {lim}) · {ctx['messages']} tin · "
                              f"memory {'✓' if ctx['memory'] else '—'}", cls="sys-line")
        elif cmd == "/memory":
            from engine import memory as fmem
            ws = self.agent.workspace if self.agent else (
                store.workspace(self.sid) if self.sid else Path.cwd())
            if arg == "clear":
                self.add_line(fmem.clear_memory(ws), cls="sys-line")
            else:
                self.add_line(fmem.memory_overview(ws), cls="sys-line")
        elif cmd == "/review":
            if self.busy:
                self.add_line("⏳ Đang chạy — chờ xong đã.", cls="sys-line")
            else:
                from engine import review as freview
                if not self.sid:
                    self.new_session()
                ws = store.workspace(self.sid)
                try:
                    diff_text, label = await freview.collect_diff(ws, self.sid, arg)
                except ValueError as e:
                    self.add_line(f"🔍 {e}", cls="tool-bad")
                else:
                    self.add_line(f"🔍 Review ({label}) — chế độ đọc-only…", cls="sys-line")
                    await self.run_turn(freview.build_prompt(diff_text, arg, label),
                                        mode="plan")
        elif cmd == "/diff":
            from engine import review as freview
            if not self.sid:
                self.new_session()
            ws = store.workspace(self.sid)
            try:
                diff_text, label = await freview.collect_diff(ws, self.sid, arg)
            except ValueError as e:
                self.add_line(f"📄 {e}", cls="sys-line")
            else:
                self.add_line(f"📄 Diff — {label}:", cls="sys-line")
                self.add_line(_diff_rich(diff_text, max_lines=60))
        elif cmd == "/doctor":
            from engine.diagnostics import doctor
            self.add_line("🩺 Đang chẩn đoán…", cls="sys-line")

            async def _doctor() -> None:
                rep = await doctor(store)
                for c in rep["checks"]:
                    self.add_line(("✓ " if c["ok"] else "✗ ") + f"{c['name']} — {c['detail']}",
                                  cls="tool-ok" if c["ok"] else "tool-bad")
                self.add_line(rep["summary"], cls="sys-line")
            asyncio.create_task(_doctor())
        elif cmd == "/agents":
            from engine import agents as fagents
            ws = self.agent.workspace if self.agent else Path.cwd()
            rows = fagents.list_agents(ws)
            if not rows:
                self.add_line("(chưa có custom agent — tạo .forge/agents/<tên>.md)", cls="sys-line")
            for r in rows:
                self.add_line(f"🤖 {r['name']} — {r['description'] or '(không mô tả)'}", cls="sys-line")
        elif cmd.startswith("/run ") or cmd == "/run":
            if self.busy:
                self.add_line("⏳ Đang chạy — chờ xong đã.", cls="sys-line")
            else:
                self.run_turn(text)
        elif cmd == "/fork":
            if self._require_idle():
                ns = store.fork(self.sid)
                if ns:
                    self.refresh_sessions(select_latest=False)
                    self.select_session(ns.id)
                    self.add_line(f"🍴 Đã fork → phiên mới {ns.id}", cls="tool-ok")
        elif cmd == "/export":
            from engine.export import to_markdown
            s = store.get(self.sid)
            path = Path(arg or f"forge-{self.sid}.md")
            if s and not path.is_absolute():
                path = Path.cwd() / path
            try:
                path.write_text(to_markdown(s), encoding="utf-8")
                self.add_line(f"⤓ Đã xuất hội thoại → {path}", cls="tool-ok")
            except OSError as e:
                self.add_line(f"⚠ Không ghi được file: {e}", cls="tool-bad")
        else:
            from engine import commands as fcmd
            ws = self.agent.workspace if self.agent else Path.cwd()
            expanded = fcmd.expand(text, ws)
            if expanded is not None:
                self.add_line(f"⌨ Lệnh custom: {cmd} → chạy", cls="sys-line")
                self.run_turn(expanded)
            else:
                self.add_line(f"Lệnh không rõ: {cmd} — /help (custom: .forge/commands/{cmd[1:]}.md)",
                              cls="sys-line")
        self.update_status()

    # ------------------------------------------------------- comfort cmds
    def _require_idle(self) -> bool:
        if self.busy or not self.sid:
            self.add_line("⏳ Chờ lượt chạy hiện tại xong đã.", cls="sys-line")
            return False
        return True

    async def _cmd_undo(self) -> None:
        if not self._require_idle() or not self.agent:
            return
        from engine import checkpoints as _ck
        res = await _ck.undo(_ck.key_for(self.agent.workspace), self.agent.workspace)
        ok, msg = bool(res.get("ok")), str(res.get("message", ""))
        self.add_line(("↩ " if ok else "⚠ ") + msg, cls="tool-ok" if ok else "tool-bad")
        if ok:
            self.render_history()
            self.refresh_files()

    async def _cmd_compact(self, instructions: str = "") -> None:
        if not self._require_idle() or not self.agent:
            return
        s = store.get(self.sid)
        n = len(s.messages) if s else 0
        self.add_line(f"🧹 Đang nén {n} tin nhắn…", cls="sys-line")
        res = await compact_session(self.agent, instructions)
        if res.get("ok"):
            self.add_line(f"✅ Đã nén {res.get('before')} → {res.get('after')} tin nhắn "
                          f"(context nhẹ hơn hẳn)", cls="tool-ok")
            self.render_history()
        else:
            self.add_line("⚠ " + (res.get("message") or "Không nén được."), cls="tool-bad")

    async def _cmd_init(self) -> None:
        if not self._require_idle() or not self.agent:
            return
        self.add_line("🚀 Đang phân tích workspace để sinh AGENTS.md…", cls="sys-line")
        res = await init_agents_md(self.agent)
        if res.get("ok"):
            self.add_line(f"✅ Đã tạo {res.get('path')}", cls="tool-ok")
            self.refresh_files()
        else:
            self.add_line("⚠ " + (res.get("message") or "Không tạo được AGENTS.md."), cls="tool-bad")

    # ------------------------------------------------------- agent loop
    @work(exclusive=True)
    async def run_turn(self, text: str, mode: str | None = None) -> None:
        if not self.sid:
            self.new_session()
        self.busy = True
        self.update_status()
        self.agent = Agent(store, self.sid)
        # @file references → đính kèm nội dung file
        from engine import atfiles
        text, attached = atfiles.expand_at_refs(text, self.agent.workspace)
        if attached:
            self.add_line(f"📎 Đã đính kèm: {', '.join('@' + a for a in attached)}", cls="sys-line")
        self.add_user(text.split("\n\n---\n")[0])
        demo = config.get_api_key() is None
        source = send_demo(self.agent, text) if demo else self.agent.send(
            text, chat_mode=mode or self.chat_mode)
        self._md_widget = None
        self._reasoning_widget = None
        self._tool_widgets = {}

        try:
            async for ev in source:
                t = ev["type"]
                if t == "reasoning_delta":
                    if self._reasoning_widget is None:
                        self._reasoning_widget = self.add_line("💭 ", cls="reasoning")
                        self._reasoning_text = ""
                    self._reasoning_text += ev["text"]
                    self._reasoning_widget.update("💭 " + self._reasoning_text[-400:])
                elif t == "assistant_delta":
                    if self._reasoning_widget is not None:
                        self._reasoning_widget = None
                    if self._md_widget is None:
                        self.begin_assistant()
                    self._md_text += ev["text"]
                    await self._md_widget.update(self._md_text)
                    self._scroll_chat()
                elif t == "assistant_message":
                    self._md_widget = None
                elif t == "tool_start":
                    self._md_widget = None
                    w = self.add_line(f"⚙ {ev['name']} — đang chạy…", cls="tool-line")
                    self._tool_widgets[ev["id"]] = w
                elif t == "tool_result":
                    w = self._tool_widgets.get(ev["id"])
                    out = ev["output"].replace("\n", " ")[:110]
                    cls = "tool-ok" if ev["ok"] else "tool-bad"
                    mark = "✓" if ev["ok"] else "✗"
                    if w:
                        w.remove_class("tool-line")
                        w.add_class(cls)
                        w.update(f"{mark} {ev['name']} — {out}")
                    if ev.get("diff"):
                        self.add_line("", cls="sys-line").update(
                            _diff_rich(ev["diff"]))
                    self.refresh_files()
                elif t == "approval_request":
                    self.app.push_screen(ApprovalModal(ev["id"], ev["command"],
                                                       ev["level"], ev["reasons"]))
                elif t == "model_fallback":
                    self.add_line(f"🔁 Model lỗi — chuyển từ {ev['from']} → {ev['to']}",
                                  cls="sys-line")
                elif t == "subagent_started":
                    self.add_line(f"🧩 Sub-agent bắt đầu: {ev['task'][:80]}", cls="tool-line")
                elif t == "subagent_progress":
                    self.add_line(f"   ⚙ sub-agent đã chạy {ev['tools']} tool"
                                  + (f" (gần nhất: {ev.get('last_tool')})" if ev.get("last_tool") else ""),
                                  cls="sys-line")
                elif t == "subagent_done":
                    self.add_line(f"🧩 Sub-agent xong ({ev['tools']} tools) — phiên {ev['session_id']}",
                                  cls="tool-ok")
                elif t == "elicitation_request":
                    self.app.push_screen(ElicitModal(
                        ev["id"], ev.get("server") or "?", ev.get("message") or "",
                        ev.get("schema"), ev.get("url")))
                elif t == "error":
                    self.add_line(f"⚠ {ev['message']}", cls="tool-bad")
                elif t == "turn_end":
                    su = ev.get("session_usage") or {}
                    if su.get("total_tokens"):
                        self.add_line(f"🔢 lượt này: {ev.get('usage', {}).get('total_tokens', '?')} tokens · "
                                      f"phiên: {su.get('total_tokens', 0)}", cls="sys-line")
        except Exception as e:
            self.add_line(f"⚠ Lỗi: {e}", cls="tool-bad")
        finally:
            self.busy = False
            self._md_widget = None
            self.refresh_sessions(select_latest=False)
            self.refresh_files()
            self.update_status()

    # --------------------------------------------------------- bindings
    def action_new_session(self) -> None:
        if not self.busy:
            self.new_session()

    def action_refresh_files(self) -> None:
        self.refresh_files()

    def action_switch_mode(self) -> None:
        if self.busy:
            return
        order = ["agent", "plan", "direct"]
        self.chat_mode = order[(order.index(self.chat_mode) + 1) % len(order)]
        icons = {"direct": "💬", "agent": "🤖", "plan": "📋"}
        self.add_line(icons[self.chat_mode] + f" Chế độ chat → {self.chat_mode} (Ctrl+M để đổi tiếp)",
                      cls="tool-ok")
        self.update_status()


def run() -> None:
    ForgeTUI().run()
