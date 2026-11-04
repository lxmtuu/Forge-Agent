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
        self.capabilities: dict = {}
        self._init_ok = False
        self._pending: dict[int, asyncio.Future] = {}  # id → future (response)

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
        mid = msg.get("id")
        if mid is not None and mid in self._pending:
            fut = self._pending.pop(mid)
            if not fut.done():
                fut.set_result(msg.get("result"))
            return
        if msg.get("method") == "textDocument/publishDiagnostics":
            params = msg.get("params") or {}
            uri = params.get("uri", "")
            self.diags[uri] = params.get("diagnostics") or []
            self.diag_ts[uri] = time.time()
        elif msg.get("method") and mid is not None:
            self._handle_server_request(msg)

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

    async def _request(self, method: str, params: dict, timeout: float = 15.0):
        """Gửi request và chờ response (future được reader set)."""
        self._rid += 1
        rid = self._rid
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)

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
            result = await self._request("initialize", {
                "processId": None,
                "rootUri": self.workspace.as_uri(),
                "capabilities": {"textDocument": {"synchronization": {"didSave": True}}},
                "clientInfo": {"name": "forge-agent", "version": "0.12.0"},
            }, timeout=15)
            if result is None:
                return False
            self.capabilities = (result or {}).get("capabilities") or {}
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

    SYMBOL_KIND = {1: "File", 2: "Module", 3: "Namespace", 4: "Package", 5: "Class",
                   6: "Method", 7: "Property", 8: "Field", 9: "Constructor", 10: "Enum",
                   11: "Interface", 12: "Function", 13: "Variable", 14: "Constant",
                   15: "String", 16: "Number", 17: "Boolean", 18: "Array", 22: "Struct",
                   23: "Event", 24: "Operator", 25: "TypeParameter"}

    async def symbols(self, path: Path, timeout: float = 10.0) -> list[dict]:
        """documentSymbol → danh sách phẳng {name, kind, line, depth}."""
        uri = path.as_uri()
        if uri not in self.opened:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                await self.refresh_file(path, text)
            except OSError:
                return []
        result = await self._request("textDocument/documentSymbol",
                                     {"textDocument": {"uri": uri}}, timeout=timeout)
        out: list[dict] = []

        def walk(items, depth):
            for it in items or []:
                if not isinstance(it, dict):
                    continue
                if "location" in it:  # DocumentSymbol flat
                    line = it["location"]["range"]["start"]["line"] + 1
                    children = []
                else:
                    line = (it.get("range", {}).get("start", {}).get("line", 0)) + 1
                    children = it.get("children") or []
                out.append({"name": it.get("name", "?"),
                            "kind": self.SYMBOL_KIND.get(it.get("kind"), "Symbol"),
                            "line": line, "depth": depth})
                walk(children, depth + 1)

        try:
            walk(result if isinstance(result, list) else [], 0)
        except Exception:
            pass
        return out[:200]

    async def _ensure_open(self, path: Path) -> str | None:
        uri = path.as_uri()
        if uri not in self.opened:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            await self.refresh_file(path, text)
            await asyncio.sleep(0.35)  # server cần thời gian phân tích trước khi hỏi vị trí
        return uri

    async def definition(self, path: Path, line: int, character: int = 1,
                         timeout: float = 10.0) -> list[dict]:
        """textDocument/definition → [{file, line}] (line 1-based)."""
        uri = await self._ensure_open(path)
        if not uri:
            return []
        pos = {"textDocument": {"uri": uri},
               "position": {"line": max(0, line - 1), "character": max(0, character - 1)}}
        result = await self._request("textDocument/definition", pos, timeout=timeout)
        locs = self._locs(result)
        if not locs:  # server chưa index xong cross-file → thử lại
            await asyncio.sleep(0.8)
            locs = self._locs(await self._request("textDocument/definition", pos, timeout=timeout))
        return locs

    async def references(self, path: Path, line: int, character: int = 1,
                         timeout: float = 12.0) -> list[dict]:
        """textDocument/references → [{file, line}] (bao gồm cả khai báo)."""
        uri = await self._ensure_open(path)
        if not uri:
            return []
        pos = {"textDocument": {"uri": uri},
               "position": {"line": max(0, line - 1), "character": max(0, character - 1)},
               "context": {"includeDeclaration": True}}
        result = await self._request("textDocument/references", pos, timeout=timeout)
        locs = self._locs(result)
        if not locs:  # retry sau khi server kịp index
            await asyncio.sleep(0.8)
            locs = self._locs(await self._request("textDocument/references", pos, timeout=timeout))
        return locs

    async def workspace_symbols(self, query: str, timeout: float = 12.0) -> list[dict]:
        """workspace/symbol → [{name, kind, file, line}] (tìm toàn workspace)."""
        result = await self._request("workspace/symbol", {"query": query or ""}, timeout=timeout)
        out = []
        for it in (result if isinstance(result, list) else [])[:60]:
            if not isinstance(it, dict):
                continue
            loc = it.get("location") or {}
            out.append({
                "name": it.get("name", "?"),
                "kind": self.SYMBOL_KIND.get(it.get("kind"), "Symbol"),
                "file": self._uri_to_path(loc.get("uri", "")),
                "line": ((loc.get("range") or {}).get("start") or {}).get("line", 0) + 1,
            })
        return out

    @staticmethod
    def _uri_to_path(uri: str) -> str:
        if uri.startswith("file://"):
            from urllib.parse import unquote, urlparse
            return unquote(urlparse(uri).path)
        return uri

    def _locs(self, result) -> list[dict]:
        items = result if isinstance(result, list) else ([result] if result else [])
        out = []
        for it in items[:40]:
            if not isinstance(it, dict):
                continue
            uri = it.get("uri") or (it.get("targetUri") or "")
            rng = (it.get("range") or it.get("targetSelectionRange") or {}).get("start") or {}
            out.append({"file": self._uri_to_path(uri),
                        "line": int(rng.get("line", 0)) + 1,
                        "character": int(rng.get("character", 0)) + 1})
        return out

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
