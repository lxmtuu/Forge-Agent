"""LSP diagnostics — sau khi agent ghi/sửa file code, hỏi language server.

Kiểu Claude Code "code intelligence": server chạy trên PATH (không tự cài),
mỗi (workspace, ngôn ngữ) một session; sau didOpen/didChange chờ
textDocument/publishDiagnostics rồi trả về danh sách lỗi cho LLM tự sửa ngay
trong lượt (self-correcting edits).

Hỗ trợ (auto-detect trên PATH, ưu tiên theo thứ tự):
  python     → pylsp · pyright-langserver --stdio
  ts/js/tsx  → typescript-language-server --stdio

Tắt bằng config "lsp_enabled": false hoặc env FORGE_LSP=0.
Lỗi LSP KHÔNG BAO GIỜ làm hỏng tool call (toàn bộ được bọc try/except).
"""
import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from . import config

SERVER_DEFS: dict[str, list[list[str]]] = {
    "python": [["pylsp"], ["pyright-langserver", "--stdio"]],
    "typescript": [["typescript-language-server", "--stdio"]],
}
EXT_LANG = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
}
MAX_DIAGS = 12
MAX_MSG = 200
DIAG_TIMEOUT = 10.0  # giây — bao gồm cold-start của server

_sessions: dict[tuple[str, str], "LspSession"] = {}
_failed: set[tuple[str, str]] = set()  # (workspace, lang) đã thử và thất bại


def lang_for(path: Path) -> str | None:
    return EXT_LANG.get(Path(path).suffix.lower())


def available_for(path: Path) -> bool:
    """Có language server trên PATH cho file này không (và tính năng đang bật)."""
    if not config.load_config().get("lsp_enabled", True):
        return False
    if str(os.environ.get("FORGE_LSP", "")).strip() == "0":
        return False
    lang = lang_for(path)
    if lang is None:
        return False
    key = (str(Path(path).resolve().parent), lang)
    return key not in _failed


def server_cmd(lang: str) -> list[str] | None:
    for cmd in SERVER_DEFS.get(lang, []):
        if shutil.which(cmd[0]):
            return cmd
    return None


class LspSession:
    """1 language server process cho 1 (workspace, lang)."""

    def __init__(self, workspace: Path, lang: str, cmd: list[str]):
        self.workspace = workspace
        self.lang = lang
        self.cmd = cmd
        self.proc: asyncio.subprocess.Process | None = None
        self.diags: dict[str, list[dict]] = {}     # uri → diagnostics thô
        self.diag_ts: dict[str, float] = {}        # uri → lúc nhận gói cuối
        self.opened: set[str] = set()
        self._ver: dict[str, int] = {}
        self._rid = 0
        self._wbuf = b""
        self._wlock = asyncio.Lock()
        self._reader_task: asyncio.Task | None = None
        self._init_ok = False
        self._init_resp = 0

    # ---- framing Content-Length ------------------------------------------
    async def _send(self, obj: dict) -> None:
        assert self.proc and self.proc.stdin
        body = json.dumps(obj).encode()
        async with self._wlock:
            self.proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            await self.proc.stdin.drain()

    def _handle_server_request(self, msg: dict) -> None:
        """Server hỏi lại client (workspace/configuration, registerCapability…)
        → trả kết quả rỗng để server không treo chờ."""
        method = msg.get("method", "")
        if method == "workspace/configuration":
            items = ((msg.get("params") or {}).get("items") or [])
            result = [{} for _ in items]
        else:
            result = None
        try:
            asyncio.get_event_loop().create_task(self._send(
                {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}))
        except Exception:
            pass

    def _on_message(self, msg: dict) -> None:
        if msg.get("method") == "textDocument/publishDiagnostics":
            params = msg.get("params") or {}
            uri = params.get("uri", "")
            self.diags[uri] = params.get("diagnostics") or []
            self.diag_ts[uri] = time.time()
        elif msg.get("method") and msg.get("id") is not None:
            self._handle_server_request(msg)
        elif msg.get("id") is not None:
            # response cho request của ta (vd initialize)
            self._init_resp = msg.get("id")

    async def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        buf = b""
        try:
            while True:
                chunk = await self.proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    head = buf.find(b"\r\n\r\n")
                    if head == -1:
                        break
                    headers = buf[:head].decode("utf-8", "replace")
                    length = 0
                    for h in headers.split("\r\n"):
                        if h.lower().startswith("content-length:"):
                            length = int(h.split(":", 1)[1].strip() or 0)
                    if length == 0 or len(buf) < head + 4 + length:
                        break
                    payload = buf[head + 4:head + 4 + length]
                    buf = buf[head + 4 + length:]
                    try:
                        self._on_message(json.loads(payload))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

    # ---- lifecycle ---------------------------------------------------------
    async def start(self) -> bool:
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self.cmd,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self.workspace),
            )
            self._reader_task = asyncio.get_event_loop().create_task(self._reader())
            self._rid += 1
            await self._send({
                "jsonrpc": "2.0", "id": self._rid, "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": self.workspace.as_uri(),
                    "capabilities": {"textDocument": {"synchronization": {"didSave": True}}},
                    "clientInfo": {"name": "forge-agent", "version": "0.9.0"},
                },
            })
            deadline = time.time() + 15
            rid = self._rid
            while time.time() < deadline:
                if self.proc.returncode is not None:
                    return False
                # initialize response đi qua _on_message? — không: response là msg có id==rid
                # ta kiểm tra qua cờ: reader đánh dấu
                if getattr(self, "_init_resp", None) == rid:
                    break
                await asyncio.sleep(0.05)
            else:
                return False
            await self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            self._init_ok = True
            return True
        except Exception:
            return False

    async def stop_quiet(self) -> None:
        try:
            if self._reader_task:
                self._reader_task.cancel()
            if self.proc:
                self.proc.kill()
        except Exception:
            pass
        self.proc = None

    # ---- API ---------------------------------------------------------------
    async def refresh_file(self, path: Path, text: str) -> None:
        uri = path.as_uri()
        self._ver[uri] = self._ver.get(uri, 0) + 1
        ver = self._ver[uri]
        if uri in self.opened:
            await self._send({
                "jsonrpc": "2.0", "method": "textDocument/didChange",
                "params": {"textDocument": {"uri": uri, "version": ver},
                           "contentChanges": [{"text": text}]},
            })
        else:
            self.opened.add(uri)
            await self._send({
                "jsonrpc": "2.0", "method": "textDocument/didOpen",
                "params": {"textDocument": {"uri": uri, "languageId": self.lang,
                                            "version": ver, "text": text}},
            })

    def normalized(self, uri: str) -> list[dict]:
        sev = {1: "error", 2: "warning", 3: "info", 4: "hint"}
        out = []
        for d in self.diags.get(uri, [])[:MAX_DIAGS]:
            rng = d.get("range", {}).get("start", {})
            out.append({
                "line": int(rng.get("line", 0)) + 1,
                "severity": sev.get(d.get("severity"), "info"),
                "message": str(d.get("message", ""))[:MAX_MSG],
                "source": d.get("source") or self.lang,
            })
        return out


async def _get_session(workspace: Path, lang: str) -> LspSession | None:
    key = (str(workspace), lang)
    if key in _failed:
        return None
    sess = _sessions.get(key)
    if sess and sess.proc and sess.proc.returncode is None and sess._init_ok:
        return sess
    cmd = server_cmd(lang)
    if not cmd:
        _failed.add(key)
        return None
    sess = LspSession(workspace, lang, cmd)
    if not await sess.start():
        await sess.stop_quiet()
        _failed.add(key)
        return None
    _sessions[key] = sess
    return sess


async def diagnostics_for(workspace: Path, path: Path) -> list[dict]:
    """Đẩy nội dung file vào language server, chờ diagnostics, trả danh sách đã chuẩn hóa."""
    workspace = Path(workspace)
    path = Path(path)
    lang = lang_for(path)
    if lang is None:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    sess = await _get_session(workspace, lang)
    if sess is None:
        return []
    uri = path.as_uri()
    ts = time.time()
    try:
        await sess.refresh_file(path, text)
    except Exception:
        return []
    # Chờ diagnostics: server hay publish gói rỗng trước rồi gói lỗi sau →
    # coi "xong" khi 0.4s trôi qua không có gói mới (debounce).
    last_update = 0.0
    deadline = time.time() + DIAG_TIMEOUT
    while time.time() < deadline:
        latest = sess.diag_ts.get(uri, 0)
        if latest > ts:
            if last_update == 0.0 or latest > last_update:
                last_update = latest
            if time.time() - last_update > 0.4:
                break
        await asyncio.sleep(0.1)
    return sess.normalized(uri)


def format_diags(diags: list[dict]) -> str:
    """Chuỗi ngắn gọn cho LLM thấy ngay sau khi sửa file (Claude-Code-style)."""
    if not diags:
        return ""
    errs = [d for d in diags if d["severity"] == "error"]
    warns = [d for d in diags if d["severity"] == "warning"]
    head = f"LSP: {len(errs)} lỗi, {len(warns)} cảnh báo sau khi ghi file — SỬA NGAY trong lượt này:"
    lines = [head]
    for d in diags[:MAX_DIAGS]:
        icon = {"error": "⛔", "warning": "⚠", "info": "ℹ", "hint": "💡"}.get(d["severity"], "•")
        lines.append(f"  {icon} dòng {d['line']} [{d['source']}] {d['message']}")
    return "\n".join(lines)


async def shutdown_all() -> None:
    for sess in list(_sessions.values()):
        await sess.stop_quiet()
    _sessions.clear()
