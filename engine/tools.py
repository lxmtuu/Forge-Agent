"""Built-in agent tools: file operations + shell, confined to a session workspace."""
import asyncio
import os
from pathlib import Path

MAX_READ = 60_000          # chars returned to the model
MAX_CMD_OUTPUT = 12_000    # chars returned to the model
MAX_SEARCH_MATCHES = 100
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache",
             "dist", "build", ".next", ".mypy_cache", ".pytest_cache", "target"}

# ---------------------------------------------------------------------------
# OpenAI-style tool schema (sent to the LLM)
# ---------------------------------------------------------------------------
TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "Giao việc cho MỘT sub-agent có ngữ cảnh hoàn toàn riêng "
                           "(workspace vẫn dùng chung với bạn) rồi nhận báo cáo tóm tắt. "
                           "Dùng cho: tìm kiếm/đọc hiểu diện rộng, review một vùng code, "
                           "làm nhiệm vụ phụ để giữ context chính gọn. Nhiệm vụ phải tự chứa "
                           "(mục tiêu + tiêu chí xong + format kết quả). Chọn model theo việc: "
                           "ĐỌC/TÌM KIẾM/TÓM TẮT → model 'cheap' · CODE THÔNG THƯỜNG → bỏ trống "
                           "(inherit) · KIẾN TRÚC/AUDIT RỦI RO CAO → 'strong'. Nhiều việc ĐỘC "
                           "LẬP → gọi nhiều spawn_subagent trong cùng một lượt để chạy song song "
                           "(tối đa 6 sub-agent/lượt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Nhiệm vụ tự chứa cho sub-agent"},
                    "isolation": {"type": "string", "enum": ["shared", "worktree"],
                                  "description": "worktree = sub-agent làm việc trong BẢN SAO "
                                                 "git-worktree tách từ checkpoint — sửa/xoá KHÔNG "
                                                 "ảnh hưởng workspace của bạn; gộp về bằng "
                                                 "/worktree merge, bỏ bằng /worktree discard"},
                    "model": {"type": "string",
                              "description": "Model cho sub-agent. Alias: 'inherit' (mặc định, "
                                             "dùng model hiện tại) · 'cheap' (model rẻ/miễn phí — "
                                             "đọc/tìm kiếm/tóm tắt) · 'strong' (model mạnh nhất — "
                                             "kiến trúc, audit rủi ro cao) · hoặc ID đầy đủ kiểu "
                                             "'vendor/model-name'."},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_save",
            "description": "Lưu kiến thức dài hạn vào MEMORY.md của workspace (TỰ ĐỘNG nạp "
                           "vào các phiên sau). Dùng ngay khi phát hiện: quyết định kiến trúc, "
                           "sở thích/lưu ý của người dùng, lỗi đã gặp và cách khắc phục, "
                           "lệnh build/test chạy được. Ngắn gọn, một dòng một ý.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Ý cần nhớ (≤500 ký tự, markdown)"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_diagnostics",
            "description": "Kiểm tra lỗi (LSP diagnostics: type, undefined name, cú pháp…) "
                           "của MỘT file code bất kỳ — read-only. Dùng sau khi sửa nhiều file "
                           "liên quan hoặc trước khi báo hoàn thành.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Đường dẫn file (relative)"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_symbols",
            "description": "Liệt kê cấu trúc file code qua LSP (documentSymbol): hàm, lớp, "
                           "phương thức kèm số dòng — read-only. Dùng để định vị nhanh trước "
                           "khi edit thay vì đọc cả file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Đường dẫn file (relative)"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_definition",
            "description": "Tìm nơi ĐỊNH NGHĨA một symbol qua LSP — chính xác tuyệt đối "
                           "(khác grep). Cần path + dòng chứa cách gọi của symbol (1-based). "
                           "Read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "number", "description": "Dòng có symbol (1-based)"},
                    "character": {"type": "number", "description": "Cột (1-based, mặc định 1)"},
                },
                "required": ["path", "line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_references",
            "description": "Tìm TẤT CẢ nơi dùng một symbol qua LSP (kể cả khai báo) — dùng "
                           "TRƯỚC khi đổi signature/rename để biết mọi call site. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"},
                },
                "required": ["path", "line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_search_symbols",
            "description": "Tìm class/hàm/biến theo tên trong TOÀN workspace qua LSP "
                           "(workspace/symbol) — nhanh và chính xác hơn grep khi tìm định nghĩa.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Tên symbol, vd 'UserService'"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and folders in the workspace. Use it to explore "
                           "the project before reading files. Paths are relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative dir path, default '.'"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full text content of a file in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Gửi tin nhắn sang MỘT phiên khác (vd phiên /loop đang chạy nền, "
                           "phiên fork). Phiên đích sẽ thấy gợi ý INBOX ở lượt kế tiếp của nó "
                           "và đọc bằng check_inbox. Dùng để điều phối: báo kết quả, đổi nhiệm "
                           "vụ, cảnh báo. Không gửi cho chính phiên hiện tại.",
            "parameters": {"type": "object",
                           "properties": {
                               "to_session": {"type": "string",
                                              "description": "ID phiên đích (vd 20261105-ab12cd34)"},
                               "text": {"type": "string", "description": "Nội dung (≤4000 ký tự)"},
                           },
                           "required": ["to_session", "text"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_inbox",
            "description": "Đọc tin nhắn CHƯA ĐỌC từ phiên khác gửi tới (tự đánh dấu đã đọc). "
                           "Gọi khi system prompt báo INBOX có tin.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or fully overwrite an existing one. "
                           "Parent folders are created automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact snippet inside an existing file. "
                           "old_text must match exactly (including whitespace).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence (default false)"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Grep-like text search across all text files in the workspace "
                           "(case-insensitive). Returns path:line matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "description": "Optional sub-path to limit search"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Tải nội dung 1 URL (docs, API reference, trang web) về dạng CHỮ "
                           "để bạn đọc. Chỉ http/https, tự strip HTML, cap 20KB. "
                           "Bị chặn với host nội bộ/localhost (chống SSRF).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL đầy đủ bắt đầu bằng http(s)://"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_background",
            "description": "Chạy lệnh shell trong NỀN (dev server, test suite dài, build) — "
                           "KHÔNG block phiên: bạn làm việc khác tiếp, dùng check_background "
                           "để xem output mới và kill_background để dừng.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Lệnh cần chạy nền"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_background",
            "description": "Xem trạng thái + OUTPUT MỚI của tác vụ nền (từ lần xem trước). "
                           "Bỏ trống id → liệt kê tất cả tác vụ nền. Gọi định kỳ để theo dõi "
                           "tiến độ, lệnh xong sẽ có exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "(tuỳ chọn) task id, vd bg-a1b2c3"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kill_background",
            "description": "Dừng (kill) một tác vụ nền đang chạy theo task id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "task id, vd bg-a1b2c3"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "GHI LẠI danh sách việc của nhiệm vụ hiện tại (checklist người dùng "
                           "nhìn thấy tiến độ realtime). Gọi ĐẦU nhiệm vụ để lập kế hoạch, rồi "
                           "cập nhật mỗi khi trạng thái 1 việc đổi (pending → doing → done). "
                           "Luôn gửi DANH SÁCH ĐẦY ĐỦ (mục cũ + mới), tối đa 50 mục.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Danh sách đầy đủ; mỗi mục {'text', 'status'} với "
                                       "status: pending|doing|done",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "status": {"type": "string",
                                           "enum": ["pending", "doing", "done"]},
                            },
                            "required": ["text"],
                        },
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command (bash) inside the workspace and return "
                           "combined stdout/stderr plus exit code. Use for builds, tests, "
                           "git, running scripts, installing deps, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_sec": {"type": "integer", "description": "Max seconds (default 30, max 120)"},
                },
                "required": ["command"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve(workspace: Path, rel: str) -> Path:
    """Resolve a user/LLM path and ensure it stays inside the workspace."""
    rel = (rel or ".").strip()
    p = (workspace / rel).resolve()
    root = workspace.resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"Path '{rel}' is outside the workspace")
    return p


def _memory_save(workspace: Path, args: dict) -> str:
    """Append một ý ghi nhớ vào <ws>/MEMORY.md (cap 8KB — cắt phần cũ)."""
    from .memory import append_entry
    return append_entry(workspace, str(args.get("content", "")))


def _iter_files(base: Path):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRS and not d.startswith(".")]
        for f in sorted(filenames):
            if f.startswith("."):
                continue
            yield Path(dirpath) / f


# ---------------------------------------------------------------------------
# Tool implementations (all sync + one async for shell)
# ---------------------------------------------------------------------------
def _list_dir(workspace: Path, args: dict) -> str:
    base = _resolve(workspace, args.get("path", "."))
    if not base.exists():
        return f"Error: path not found: {args.get('path')}"
    if base.is_file():
        return f"{args.get('path')} (file)"
    lines: list[str] = []
    count = 0
    for f in _iter_files(base):
        rel = f.relative_to(base)
        depth = len(rel.parts) - 1
        if depth > 3:
            continue
        lines.append("  " * depth + ("📄 " if True else "") + str(rel))
        count += 1
        if count >= 400:
            lines.append("… (truncated at 400 entries)")
            break
    if not lines:
        return "(empty workspace)"
    return "\n".join(lines)


def _read_file(workspace: Path, args: dict) -> str:
    p = _resolve(workspace, args["path"])
    if not p.exists() or not p.is_file():
        return f"Error: file not found: {args['path']}"
    raw = p.read_bytes()
    if b"\x00" in raw[:2000]:
        return f"Error: '{args['path']}' looks binary; cannot display."
    text = raw.decode("utf-8", "replace")
    if len(text) > MAX_READ:
        return text[:MAX_READ] + f"\n… (truncated, {len(text) - MAX_READ} more chars)"
    return text if text else "(empty file)"


def _make_diff(path: str, old: str, new: str) -> str | None:
    import difflib
    if old == new:
        return None
    d = list(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}"))
    text = "".join(d)
    if len(text) > 8000:
        text = text[:8000] + "\n… (diff quá dài, đã cắt bớt)"
    return text


def _write_file(workspace: Path, args: dict):
    p = _resolve(workspace, args["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    old = p.read_text(encoding="utf-8", errors="replace") if existed else ""
    p.write_text(args.get("content", ""), encoding="utf-8")
    diff = _make_diff(args["path"], old, args.get("content", "")) if existed else None
    note = f"Wrote {len(args.get('content', ''))} chars to {args['path']}"
    if not existed:
        note += " (file mới)"
    return {"output": note, "diff": diff, "path": args["path"]}


def _edit_file(workspace: Path, args: dict):
    p = _resolve(workspace, args["path"])
    if not p.exists() or not p.is_file():
        return f"Error: file not found: {args['path']}"
    text = p.read_text(encoding="utf-8", errors="replace")
    old, new = args["old_text"], args["new_text"]
    n = text.count(old)
    if n == 0:
        return ("Error: old_text not found in file. Make sure it matches exactly "
                "(whitespace/newlines). Read the file again first.")
    if args.get("replace_all"):
        text2 = text.replace(old, new)
        count = n
    else:
        text2 = text.replace(old, new, 1)
        count = 1
    p.write_text(text2, encoding="utf-8")
    diff = _make_diff(args["path"], text, text2)
    return {"output": f"Edited {args['path']} ({count} occurrence replaced)",
            "diff": diff, "path": args["path"]}


def _search_files(workspace: Path, args: dict) -> str:
    query = args["query"].lower()
    base = _resolve(workspace, args.get("path", "."))
    matches: list[str] = []
    for f in _iter_files(base if base.is_dir() else base.parent):
        try:
            if f.stat().st_size > 1_000_000:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if query in line.lower():
                    rel = f.relative_to(workspace)
                    matches.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        matches.append(f"… (stopped at {MAX_SEARCH_MATCHES} matches)")
                        return "\n".join(matches)
        except Exception:
            continue
    return "\n".join(matches) if matches else f"No matches for '{args['query']}'"


_FAIL_STREAK: dict[tuple[str, str], int] = {}


async def _run_command(workspace: Path, args: dict, override: bool = False) -> str:
    from . import config, guard

    cmd = args["command"]
    approval = config.load_config().get("approval_mode", "guarded")
    verdict = guard.assess_command(cmd)
    if verdict["level"] == "danger" and approval != "auto" and not override:
        return guard.guard_message(cmd, verdict)
    if config.load_config().get("docker_sandbox") and guard.DOCKER_AVAILABLE:
        cmd = guard.docker_wrap(cmd)
    timeout = min(int(args.get("timeout_sec") or 30), 120)
    env = {**os.environ, "TERM": "dumb", "NO_COLOR": "1"}
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(workspace), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=env,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Error: command timed out after {timeout}s: {cmd}"
        text = out.decode("utf-8", "replace")
        if len(text) > MAX_CMD_OUTPUT:
            text = text[:MAX_CMD_OUTPUT] + f"\n… (truncated, exit={proc.returncode})"
        body = f"exit={proc.returncode}\n{text}" if text.strip() else f"exit={proc.returncode} (no output)"
        # --- anti-loop: cảnh báo khi lệnh giống nhau thất bại nhiều lần ---
        key = (str(workspace), cmd)
        if proc.returncode == 0:
            _FAIL_STREAK.pop(key, None)
        else:
            n = _FAIL_STREAK.get(key, 0) + 1
            _FAIL_STREAK[key] = n
            if n >= 2:
                body += (
                    f"\n\n⚠ This exact command has already failed {n} times in a row. "
                    "DO NOT run it again unchanged. Read the error carefully, verify with "
                    "list_dir/read_file, and use a DIFFERENT approach (e.g. on Windows use "
                    "`python` not `python3`, use dir/type instead of ls/cat)."
                )
        return body
    except Exception as e:
        return f"Error running command: {e}"


_TODO_MARK = {"pending": "◻", "doing": "▶", "done": "✅"}


def _todo_write(workspace: Path, args: dict) -> str:
    """Ghi checklist nhiệm vụ vào <ws>/.forge/todo.json (thay toàn bộ danh sách)."""
    import json as _json
    raw = args.get("items")
    if not isinstance(raw, list) or not raw:
        return "Error: thiếu items — gửi danh sách [{text, status}] ĐẦY ĐỦ"
    norm: list[dict] = []
    for it in raw[:50]:
        if isinstance(it, str):
            if it.strip():
                norm.append({"text": it.strip(), "status": "pending"})
        elif isinstance(it, dict):
            text = str(it.get("text") or "").strip()
            st = str(it.get("status") or "pending").lower()
            if text:
                norm.append({"text": text,
                             "status": st if st in _TODO_MARK else "pending"})
    if not norm:
        return "Error: không có mục hợp lệ nào"
    d = workspace / ".forge"
    d.mkdir(exist_ok=True)
    (d / "todo.json").write_text(
        _json.dumps(norm, ensure_ascii=False, indent=1), encoding="utf-8")
    done = sum(1 for i in norm if i["status"] == "done")
    body = "\n".join(f"{_TODO_MARK[i['status']]} {i['text']}" for i in norm)
    return f"TODO cập nhật — {done}/{len(norm)} xong:\n{body}"


def _host_is_private(hostname: str) -> bool:
    """True = host nội bộ/không công khai → chặn (chống SSRF)."""
    import ipaddress as _ip
    import socket as _socket
    host = hostname.strip("[]").lower()
    if not host or host in ("localhost", "*") or host.endswith(".localhost"):
        return True
    try:
        infos = _socket.getaddrinfo(host, None)
    except OSError:
        return True  # không phân giải được → không cho
    for info in infos:
        try:
            ip = _ip.ip_address(info[4][0])
        except ValueError:
            return True
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return True
    return False


def _strip_html(html: str) -> str:
    import re as _re
    from html import unescape
    s = _re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", html)
    s = _re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = _re.sub(r"(?is)</(p|div|li|tr|h[1-6]|section|article|table)>", "\n", s)
    s = _re.sub(r"(?s)<[^>]+>", " ", s)
    s = unescape(s)
    s = s.replace("\u00a0", " ")  # &nbsp; → space thường
    s = _re.sub(r"[ \t]+", " ", s)
    s = _re.sub(r"\n\s*\n\s*", "\n\n", s)
    return s.strip()


async def _fetch_url(workspace: Path, args: dict) -> str:
    import httpx
    from urllib.parse import urlparse
    url = str(args.get("url") or "").strip()
    if not url:
        return "Error: thiếu url"
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        return "Error: chỉ hỗ trợ http/https"
    if _host_is_private(u.hostname or ""):
        return ("Error: bị chặn vì bảo mật (SSRF) — không được truy cập "
                "host nội bộ/localhost/metadata")
    try:
        async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True,
                headers={"User-Agent": "forge-agent/0.14 (+self-hosted BYOK)"}) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        return f"Error: không tải được URL: {e}"
    if _host_is_private(str(resp.url).split("/")[2] if "://" in str(resp.url) else ""):
        return "Error: redirect đưa về host nội bộ — bị chặn"
    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
    if any(k in ctype for k in ("image/", "video/", "audio/", "font", "octet-stream",
                                "zip", "pdf")):
        return f"Error: URL trả về nội dung nhị phân ({ctype}) — không đọc được dạng chữ"
    text = resp.text
    if "html" in ctype:
        text = _strip_html(text)
    text = text.strip()
    cap = 20000
    if len(text) > cap:
        text = text[:cap] + f"\n… (đã cắt ở {cap} ký tự — trang dài {len(text)} ký tự)"
    return f"[{resp.status_code}] {resp.url} · {ctype or 'text'}\n\n{text or '(trang trống)'}"


async def _run_background(workspace: Path, args: dict) -> str:
    from . import background as bg
    from . import config, guard
    cmd = str(args.get("command") or "").strip()
    if not cmd:
        return "Error: thiếu command"
    verdict = guard.assess_command(cmd)
    approval = config.load_config().get("approval_mode", "guarded")
    if verdict["level"] == "danger" and approval != "auto":
        return guard.guard_message(cmd, verdict)
    tid, msg = await bg.start(cmd, workspace)
    if not tid:
        return msg
    await asyncio.sleep(0.3)  # cho có output đầu để LLM thấy ngay
    t = bg.get(tid)
    return msg + "\n" + (bg.render(t, incremental=False) if t else "(?)")


def _check_background(workspace: Path, args: dict) -> str:
    from . import background as bg
    tid = str(args.get("id") or "").strip()
    if not tid:
        return bg.summary()
    t = bg.get(tid)
    if not t:
        return f"Error: không có tác vụ «{tid}» — gọi check_background không id để xem danh sách"
    return bg.render(t, incremental=True)


async def _kill_background(workspace: Path, args: dict) -> str:
    from . import background as bg
    return await bg.kill(str(args.get("id") or ""))


_IMPL = {
    "list_dir": _list_dir,
    "todo_write": _todo_write,
    "check_background": _check_background,
    "read_file": _read_file,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "search_files": _search_files,
    "memory_save": _memory_save,
}


async def execute_tool(name: str, args: dict, workspace: Path, override: bool = False) -> dict:
    """Run one tool. Returns {"ok": bool, "output": str, "diff"?: str, "path"?: str}.

    override=True: user explicitly approved this exact command interactively.
    """
    from . import checkpoints

    diff = None
    changed_path = None
    try:
        if name in ("write_file", "edit_file", "run_command", "memory_save", "run_background"):
            await checkpoints.snapshot(
                checkpoints.key_for(workspace), workspace,
                f"{name}: {args.get('path', args.get('command', ''))[:60]}")
        if name == "run_command":
            output = await _run_command(workspace, args, override=override)
            ok = not output.startswith(("Error", "BLOCKED"))
        elif name == "fetch_url":
            output = await _fetch_url(workspace, args)
            ok = not output.startswith("Error")
        elif name == "run_background":
            output = await _run_background(workspace, args)
            ok = not output.startswith(("Error", "BLOCKED"))
        elif name == "check_background":
            output = _check_background(workspace, args)
            ok = not output.startswith("Error")
        elif name == "kill_background":
            output = await _kill_background(workspace, args)
            ok = not output.startswith("Error")
        elif name in ("lsp_diagnostics", "lsp_symbols", "lsp_definition", "lsp_references"):
            output, ok, changed_path = await _run_lsp_tool(name, workspace, args)
        elif name == "lsp_search_symbols":
            output, ok, changed_path = await _run_lsp_search_symbols(workspace, args)
        elif name in _IMPL:
            res = _IMPL[name](workspace, args)
            if isinstance(res, dict):
                output = res["output"]
                diff = res.get("diff")
                changed_path = res.get("path")
            else:
                output = res
            ok = not output.startswith(("Error", "BLOCKED"))
        else:
            output, ok = f"Error: unknown tool '{name}'", False
    except Exception as e:
        output, ok = f"Error: {e}", False

    # ---- LSP diagnostics sau khi ghi/sửa file code (Claude-Code-style) ----
    diags: list[dict] = []
    if ok and changed_path and name in ("write_file", "edit_file"):
        try:
            from . import lsp as _lsp
            p = Path(changed_path) if str(changed_path).startswith("/") else workspace / changed_path
            if p.is_file() and _lsp.available_for(p):
                diags = await _lsp.diagnostics_for(workspace, p)
                if diags:
                    output = output + "\n\n" + _lsp.format_diags(diags)
        except Exception as _e:  # LSP không bao giờ được làm hỏng tool call
            print(f"[lsp] bỏ qua lỗi: {_e}")

    # ---- hook on_file_change (kiểu Claude Code hooks — chạy formatter/lint tự đặt) ----
    if ok and changed_path and name in ("write_file", "edit_file"):
        try:
            from . import config as _cfg_mod
            hook_cmd = _cfg_mod.load_config().get("on_file_change")
            if hook_cmd and str(hook_cmd).strip():
                import os as _os
                env = {**_os.environ,
                       "FORGE_CHANGED_FILE": str(changed_path),
                       "FORGE_WORKSPACE": str(workspace)}
                proc = await asyncio.create_subprocess_shell(
                    str(hook_cmd), cwd=str(workspace), env=env,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                    hook_out = out.decode("utf-8", "replace").strip()[:600]
                except asyncio.TimeoutError:
                    proc.kill()
                    hook_out, hook_rc = "timeout 30s", 124
                else:
                    hook_rc = proc.returncode or 0
                output += (f"\n🔗 Hook on_file_change (exit {hook_rc}): "
                           + (hook_out or "(không output)"))
        except Exception as _e:
            output += f"\n🔗 Hook on_file_change lỗi: {_e}"

    result = {"ok": ok, "output": output}
    if diff:
        result["diff"] = diff
    if changed_path:
        result["path"] = changed_path
    if diags:
        result["diagnostics"] = diags
    return result


async def _run_lsp_tool(name: str, workspace: Path, args: dict) -> tuple[str, bool, None]:
    """lsp_diagnostics / lsp_symbols — read-only, không bao giờ hỏng tool call."""
    from . import lsp as _lsp
    rel = str(args.get("path", "")).strip()
    if not rel:
        return "Error: thiếu path", False, None
    p = Path(rel) if str(rel).startswith("/") else workspace / rel
    if not p.is_file():
        return f"Error: không tìm thấy file {rel}", False, None
    lang = _lsp.lang_for(p)
    if lang is None:
        return f"Bỏ qua: {p.suffix} không phải file code có language server", True, None
    if not _lsp.server_cmd(lang):
        return (f"LSP cho {lang} chưa cài trên máy. Hướng dẫn: pip install "
                f'\"python-lsp-server[pyflakes,pycodestyle]\" (Python) hoặc '
                f"npm i -g typescript typescript-language-server (TS/JS).", True, None)
    if name == "lsp_diagnostics":
        diags = await _lsp.diagnostics_for(workspace, p)
        if not diags:
            return f"✓ {rel}: không có lỗi LSP", True, None
        return _lsp.format_diags(diags).replace("sau khi ghi file", f"({rel})"), True, None
    # các tool còn lại cần session
    sess = await _lsp._get_session(workspace, lang)
    if sess is None:
        return f"Error: không khởi động được language server cho {p.suffix}", False, None
    if name == "lsp_symbols":
        syms = await sess.symbols(p)
        if not syms:
            return "(không có symbol — file rỗng hoặc ngôn ngữ chưa hỗ trợ)", True, None
        lines = [f"{'  ' * x['depth']}{x['kind']} {x['name']} (dòng {x['line']})" for x in syms[:80]]
        return f"Cấu trúc {rel}:\n" + "\n".join(lines), True, None
    if name in ("lsp_definition", "lsp_references"):
        line = int(args.get("line", 1) or 1)
        char = int(args.get("character", 1) or 1)
        try:
            locs = (await sess.definition(p, line, char) if name == "lsp_definition"
                    else await sess.references(p, line, char))
        except Exception as e:
            return f"Error: LSP {name} lỗi: {e}", False, None
        if not locs:
            return (f"Không tìm thấy {name.replace('lsp_', '')} cho vị trí {rel}:{line} "
                    "(kiểm tra lại line/cột — dùng lsp_symbols để định vị trước)", True, None)
        ws_str = str(workspace)
        rows = []
        for ln in locs:
            short = ln["file"].replace(ws_str + "/", "").replace(ws_str, ".")
            rows.append(f"  {short}:{ln['line']}:{ln['character']}")
        verb = "Định nghĩa" if name == "lsp_definition" else "Nơi dùng"
        return f"{verb} ({len(locs)} vị trí):\n" + "\n".join(rows), True, None
    return f"Error: unknown lsp tool {name}", False, None


async def _run_lsp_search_symbols(workspace: Path, args: dict) -> tuple[str, bool, None]:
    from . import lsp as _lsp
    q = str(args.get("query", "")).strip()
    if not q:
        return "Error: thiếu query", False, None
    # thử từng ngôn ngữ có language server
    results: list[dict] = []
    no_support: list[str] = []
    for lang, cmds in (("python", _lsp.SERVER_DEFS["python"]), ("typescript", _lsp.SERVER_DEFS["typescript"])):
        if not any(__import__("shutil").which(c[0]) for c in cmds):
            continue
        sess = await _lsp._get_session(workspace, lang)
        if sess is None:
            continue
        if not sess.capabilities.get("workspaceSymbolProvider"):
            no_support.append(lang)
            continue
        try:
            results = await sess.workspace_symbols(q)
            if results:
                break
        except Exception:
            continue
    if not results:
        if no_support:
            return (f"Language server ({', '.join(no_support)}) không hỗ trợ tìm symbol toàn "
                    f"workspace — dùng tool search_files thay thế", True, None)
        return f"Không tìm thấy symbol nào khớp «{q}» (hoặc máy chưa có language server)", True, None
    ws_str = str(workspace)
    rows = [f"  {x['kind']} {x['name']} — {x['file'].replace(ws_str + '/', '')}:{x['line']}"
            for x in results[:30]]
    return f"Symbols khớp «{q}» ({len(results)}):\n" + "\n".join(rows), True, None
