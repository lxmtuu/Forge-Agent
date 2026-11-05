"""Connectors — kết nối SaaS (GitHub, Linear, Supabase…) qua remote MCP chính thức.

3 lớp kiến trúc:
  [1] PRESETS bên dưới — khai báo endpoint/transport/kiểu auth/hướng dẫn (KHÔNG có code riêng từng app)
  [2] engine/mcp.py (đã có) — transport stdio/HTTP + headers, manager gắn tool vào agent
  [3] An toàn — secrets lưu riêng + mask khi hiển thị; tool MCP chưa allowlist phải duyệt (agent.py)

Lệnh (đồng bộ trên CLI/TUI/Web):
  /connectors                          liệt kê đã cài + presets sẵn sàng + trạng thái
  /connectors add <preset> [url] [--write]
  /connectors auth <tên> <token>       lưu token (mask khi hiển thị), không bao giờ vào context LLM
  /connectors allow <tên> [tool|*]     cho phép tool chạy không cần duyệt
  /connectors deny <tên> [tool|*]      rút phép
  /connectors remove <tên>
"""
import json
from pathlib import Path

from . import config
from .mcp import _sanitize_name, load_servers, save_servers

# ─────────────────────────────────────────── PRESETS (endpoint chính thức 2026) ──
PRESETS: dict[str, dict] = {
    "github": {
        "label": "GitHub — repos, PR, issues, Actions (server chính thức)",
        "transport": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "auth": "pat",
        "auth_hint": "Personal Access Token: github.com/settings/tokens → scope tối thiểu (vd repo:read nếu chỉ đọc)",
        "headers": {"Authorization": "Bearer {token}"},
    },
    "linear": {
        "label": "Linear — issues, projects, cycles (server chính thức)",
        "transport": "http",
        "url": "https://mcp.linear.app/mcp",
        "auth": "api-key",
        "oauth": {
            "authorize": "https://linear.app/oauth/authorize",
            "token": "https://api.linear.app/oauth/token",
            "scope": "read",
            "style": "post",
            "loopback_port": 8765,
        },
        "auth_hint": "API key: linear.app/settings/api (hoặc dùng /mcp/readonly để chỉ đọc); "
                     "hoặc OAuth: /connectors oauth linear <client_id> <client_secret>",
        "headers": {"Authorization": "Bearer {token}"},
    },
    "postgres": {
        "label": "PostgreSQL — SQL chỉ-đọc trên DB của BẠN (npx @modelcontextprotocol/server-postgres)",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres", "$DATABASE_URL"],
        "auth": "env",
        "auth_hint": "Đặt biến môi trường DATABASE_URL (vd postgresql://user:pass@host:5432/db) "
                     "trước khi thêm. Chỉ READ-ONLY theo thiết kế — truy vấn SELECT/EXPLAIN thôi. "
                     "Xoá connector + đặt DATABASE_URL khác để đổi DB.",
    },
    "notion": {
        "label": "Notion — pages, databases (chính thức · chỉ OAuth)",
        "transport": "http",
        "url": "https://mcp.notion.com/mcp",
        "auth": "oauth",
        "oauth": {
            "authorize": "https://api.notion.com/v1/oauth/authorize",
            "token": "https://api.notion.com/v1/oauth/token",
            "scope": "",
            "style": "basic",
            "loopback_port": 8765,
        },
        "auth_hint": "Tạo integration PUBLIC: notion.so/profile/integrations → thêm redirect "
                     "http://127.0.0.1:8765/callback → /connectors add notion rồi /connectors oauth notion <client_id> <client_secret>",
        "headers": {},
    },
    "sentry": {
        "label": "Sentry — lỗi, stacktrace (chính thức)",
        "transport": "http",
        "url": "https://mcp.sentry.dev/mcp",
        "auth": "oauth",
        "oauth": {
            "authorize": "https://sentry.io/oauth/authorize/",
            "token": "https://sentry.io/oauth/token/",
            "scope": "org:read project:read event:read",
            "style": "post",
            "loopback_port": 8765,
        },
        "auth_hint": "Tạo ứng dụng OAuth trong Sentry (Settings → Auth) → redirect "
                     "http://127.0.0.1:8765/callback → /connectors add sentry rồi /connectors oauth sentry <client_id> <client_secret>",
        "headers": {},
    },
    "figma-desktop": {
        "label": "Figma Dev Mode — cần Figma Desktop đang mở",
        "transport": "http",
        "url": "http://127.0.0.1:3845/mcp",
        "auth": "none",
        "auth_hint": "Mở Figma Desktop (Dev Mode MCP Server) trên cùng máy",
        "headers": {},
    },
    "context7": {
        "label": "Context7 — tài liệu thư viện mới nhất (không cần token)",
        "transport": "http",
        "url": "https://mcp.context7.com/mcp",
        "auth": "none",
        "auth_hint": "Không cần token",
        "headers": {},
    },
    "playwright": {
        "label": "Playwright — điều khiển browser thật (test E2E)",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"],
        "auth": "none",
        "auth_hint": "Cần Node.js trong PATH",
    },
    "filesystem": {
        "label": "File System — đọc/ghi file THƯ MỤC TÙY CHỌN ngoài workspace (npx @modelcontextprotocol/server-filesystem)",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "$FORGE_FS_DIR"],
        "auth": "env",
        "auth_hint": "Đặt FORGE_FS_DIR=<đường-dẫn-thư-mục> được phép truy cập trước khi thêm "
                     "(mặc định nếu thiếu: thư mục hiện hành). Cẩn thận: tool ghi ngoài workspace "
                     "sẽ KHÔNG có checkpoint/undo của Forge.",
    },
    "sequential-thinking": {
        "label": "Sequential Thinking — suy luận từng bước có sửa/lại nhánh (npx @modelcontextprotocol/server-sequential-thinking)",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "auth": "none",
        "auth_hint": "Không cần cấu hình — tool 'sequentialthinking' xuất hiện sau /mcp refresh.",
    },
    "composio-hub": {
        "label": "Composio Hub — Gmail, Slack, Vercel… 500+ app, managed OAuth (free 20k calls/tháng)",
        "transport": "http",
        "url": "",
        "auth": "hub",
        "auth_hint": "Đăng ký composio.dev → mục MCP → dán URL đầy đủ của bạn: "
                     "/connectors add composio-hub <url-của-bạn>",
    },
}

AUTH_LABEL = {
    "pat": "PAT (Bearer)",
    "api-key": "API key (Bearer)",
    "oauth": "OAuth 2.1 (browser + PKCE)",
    "oauth-pending": "OAuth (qua hub — xem auth_hint)",
    "env": "env-var (đặt biến môi trường trước)",
    "hub": "qua hub (dán URL)",
    "none": "không cần",
}

# ─────────────────────────────────────────── secrets ──────────────────────────
def _secrets_path() -> Path:
    return config.DATA_DIR / "secrets.json"


def _load_secrets() -> dict:
    try:
        data = json.loads(_secrets_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_secrets(data: dict) -> None:
    config.ensure_dirs()
    f = _secrets_path()
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        f.chmod(0o600)  # posix; Windows bỏ qua là bình thường
    except OSError:
        pass


def mask_token(t: str) -> str:
    if not t:
        return "(chưa có)"
    if len(t) <= 6:
        return "*" * len(t)
    return f"{t[:4]}…{t[-2:]}"


def has_auth(name: str) -> bool:
    ent = _load_secrets().get(_sanitize_name(name), {})
    return bool(ent.get("token") or (ent.get("oauth") or {}).get("access_token"))


# ─────────────────────────────────────────── cấu hình server ──────────────────
def _find_cfg(name: str) -> dict | None:
    key = _sanitize_name(name).lower()
    for cfg in load_servers():
        if _sanitize_name(cfg["name"]).lower() == key:
            return cfg
    return None


def add(name: str, url: str = "", write: bool = False) -> str:
    p = PRESETS.get((name or "").strip().lower())
    if p is None:
        return (f"❌ Không có preset '{name}'. Có sẵn: "
                + ", ".join(sorted(PRESETS)))
    cfg: dict = {"name": p["label"].split(" — ")[0].split(" (")[0], "preset": name.strip().lower(),
                 "enabled": True, "allowed_tools": []}
    cfg["label"] = p["label"]
    if p["transport"] == "http":
        final_url = url.strip() or p["url"]
        if not final_url:
            return f"❌ Preset '{name}' cần URL riêng — {p['auth_hint']}"
        if write and "read_only=true" in final_url:
            final_url = final_url.replace("?read_only=true", "")
            cfg["label"] = cfg["label"].replace("mặc định read_only", "CHẾ ĐỘ GHI — cẩn thận")
        cfg["url"] = final_url
        hdr = {}
        for k, v in p.get("headers", {}).items():
            hdr[k] = v
        if hdr:
            cfg["headers"] = hdr
    else:
        cfg["command"] = p.get("command", "")
        cfg["args"] = list(p.get("args", []))
        if p.get("env"):
            cfg["env"] = dict(p["env"])
    # merge theo tên đã sanitize (trùng → ghi đè)
    servers = [c for c in load_servers()
               if _sanitize_name(c["name"]) != _sanitize_name(cfg["name"])]
    servers.append(cfg)
    save_servers(servers)
    nxt = ""
    if p["auth"] in ("pat", "api-key"):
        nxt = f"\n   Tiếp: /connectors auth {cfg['name']} <token>"
    elif p["auth"] == "hub":
        nxt = "\n   (URL hub đã lưu — kiểm tra tool: gõ /mcp trong CLI hoặc xem /connectors)"
    elif p["auth"] == "env":
        var = next((a for a in p.get("args", []) if str(a).startswith("$")), "")
        var = var[1:] if var else "biến môi trường theo auth_hint"
        nxt = (f"\n   ⚠ Phải đặt biến môi trường {var} TRƯỚC — connector khởi động server lúc "
               f"refresh; thiếu biến → server lỗi, xem /mcp.")
    elif p.get("oauth"):
        nxt = f"\n   Tiếp: /connectors oauth {name} <client_id> [client_secret] — mở trình duyệt đăng nhập (OAuth 2.1 + PKCE)"
    elif p["auth"] == "oauth-pending":
        nxt = "\n   ⚠ Service này dùng OAuth phía nhà cung cấp — dùng hub Composio (xem auth_hint)."
    return (f"✅ Đã thêm connector '{cfg['name']}' ({p['label']})\n"
            f"   {AUTH_LABEL[p['auth']]} — {p['auth_hint']}{nxt}")


def auth(name: str, token: str) -> str:
    cfg = _find_cfg(name)
    if cfg is None:
        return f"❌ Chưa cài connector '{name}' — thêm trước bằng /connectors add {name}"
    token = (token or "").strip()
    if not token:
        return "❌ Token rỗng."
    key = _sanitize_name(cfg["name"])
    # ghi token thật vào headers/env mà engine tiêu thụ (không bao giờ in ra)
    tmpl = PRESETS.get(cfg.get("preset", ""), {}).get("headers") or cfg.get("headers") or {}
    hdr = dict(cfg.get("headers") or {})
    for k, v in tmpl.items():
        if "{token}" in v:
            hdr[k] = v.replace("{token}", token)
    if hdr:
        cfg["headers"] = hdr
    env = dict(cfg.get("env") or {})
    for k, v in (PRESETS.get(cfg.get("preset", ""), {}).get("env") or {}).items():
        if "{token}" in str(v):
            env[k] = str(v).replace("{token}", token)
    if env:
        cfg["env"] = env
    servers = [c if _sanitize_name(c["name"]) != key else cfg for c in load_servers()]
    save_servers(servers)
    # bản ghi mask để hiển thị/audit
    sec = _load_secrets()
    sec[key] = {"masked": mask_token(token), "connector": cfg["name"]}
    _save_secrets(sec)
    return (f"🔑 Đã lưu token cho '{cfg['name']}' ({mask_token(token)}). "
            "Gõ /mcp refresh rồi xem tool bằng /connectors.")


def remove(name: str) -> str:
    key = _sanitize_name(name).lower()
    servers = load_servers()
    kept = [c for c in servers if _sanitize_name(c["name"]).lower() != key]
    if len(kept) == len(servers):
        return f"❌ Không thấy connector '{name}'."
    save_servers(kept)
    sec = _load_secrets()
    sec.pop(key, None)
    _save_secrets(sec)
    return f"🗑 Đã gỡ connector '{name}' (token cũng xoá)."


def allow(name: str, tool: str = "*") -> str:
    cfg = _find_cfg(name)
    if cfg is None:
        return f"❌ Không thấy connector '{name}'."
    tool = (tool or "*").strip()
    cur = cfg.get("allowed_tools")
    if tool == "*":
        cfg["allowed_tools"] = "*"
    else:
        lst = list(cur) if isinstance(cur, list) else []
        if tool not in lst:
            lst.append(tool)
        cfg["allowed_tools"] = lst
    _replace_cfg(cfg)
    return (f"✅ '{cfg['name']}' — tool '{tool}' KHÔNG cần duyệt nữa."
            + (" (MỌI tool — cân nhắc kỹ!)" if tool == "*" else ""))


def deny(name: str, tool: str = "*") -> str:
    cfg = _find_cfg(name)
    if cfg is None:
        return f"❌ Không thấy connector '{name}'."
    tool = (tool or "*").strip()
    cur = cfg.get("allowed_tools")
    if tool == "*" or cur == "*":
        cfg["allowed_tools"] = []
    else:
        lst = [t for t in (cur or []) if t != tool]
        cfg["allowed_tools"] = lst
    _replace_cfg(cfg)
    return f"🔒 '{cfg['name']}' — đã rút phép tool '{tool}' (cần duyệt lại từ đầu)."


def _replace_cfg(cfg: dict) -> None:
    """Upsert cấu hình theo tên (không phân biệt hoa/thường) — chèn nếu chưa có."""
    key = _sanitize_name(cfg["name"]).lower()
    servers = [c for c in load_servers() if _sanitize_name(c["name"]).lower() != key]
    servers.append(cfg)
    save_servers(servers)


def tool_allowed(server_name: str, tool: str) -> bool:
    """True = đã allowlist (bỏ duyệt). Mặc định FALSE — an toàn là trên hết."""
    cfg = _find_cfg(server_name)
    if cfg is None:
        return False
    cur = cfg.get("allowed_tools") or []
    return cur == "*" or tool in cur


# ─────────────────────────────────────────── hiển thị ──────────────────────────
def status_listing() -> str:
    from .mcp import manager as mm
    live = {s["name"]: s for s in mm.status()}
    secrets = _load_secrets()
    cfgs = load_servers()
    blocks: list[str] = []
    n_auth = 0
    if cfgs:
        lines = ["### 🔌 Connectors đã cài"]
        for c in cfgs:
            key = _sanitize_name(c["name"])
            st = live.get(c["name"], {})
            icon = {"ready": "🟢", "error": "🔴"}.get(st.get("status", ""), "⚪")
            n_tools = len(st.get("tools") or [])
            authed = key in secrets
            if authed:
                n_auth += 1
            tok = f"🔑 {secrets[key]['masked']}" if authed else "🔓 chưa có token"
            allowed = c.get("allowed_tools") or []
            allow_s = "mọi tool" if allowed == "*" else (f"{len(allowed)} tool" if allowed else "chưa allowlist")
            err = f" · ⚠ {st['error']}" if st.get("error") else ""
            lines.append(
                f"- {icon} **{c['name']}** ({c.get('preset', 'thủ-công')}) · "
                f"{c.get('url') or (c.get('command', '') + ' ' + ' '.join(c.get('args', []))).strip()} · "
                f"{tok} · allow: {allow_s} · tools: {n_tools}{err}")
        blocks.append("\n".join(lines))
    installed = {_sanitize_name(c.get("preset", "")) for c in cfgs}
    rest = [k for k in sorted(PRESETS) if k not in installed]
    if rest:
        lines = ["### 📋 Presets sẵn sàng"]
        for k in rest:
            p = PRESETS[k]
            lines.append(f"- `{k}` — {p['label']} · auth: {AUTH_LABEL[p['auth']]}")
        lines.append("Cài: `/connectors add <tên>`")
        blocks.append("\n".join(lines))
    head = f"### 🔌 Connectors ({len(cfgs)} cài · {n_auth} có token)\n" if cfgs else "### 🔌 Connectors\n"
    tail = ("\n\nLệnh: `add <preset> [url]` · `auth <tên> <token>` · `oauth <tên> <client_id> [secret]` (browser + PKCE) · "
            "`logout <tên>` · `allow <tên> [tool|*]` · `deny` · `remove` · `/mcp` xem tool chi tiết")
    if not cfgs and not rest:
        return head + "(trống)" + tail
    return head + "\n\n".join(blocks) + tail
