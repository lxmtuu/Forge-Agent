"""Forge TUI — full-screen terminal app (opencode-style): chat + sessions + files + status."""
from __future__ import annotations

import json
import time
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, ListView, ListItem, Markdown, Static, Tree

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
                          "/usage /files /quit · Gõ @file.py để đính kèm file · "
                          "Custom: .forge/commands/<tên>.md → gõ /<tên> [args]",
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
    async def run_turn(self, text: str) -> None:
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
        source = send_demo(self.agent, text) if demo else self.agent.send(text, chat_mode=self.chat_mode)
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
                    self.refresh_files()
                elif t == "approval_request":
                    self.app.push_screen(ApprovalModal(ev["id"], ev["command"],
                                                       ev["level"], ev["reasons"]))
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
