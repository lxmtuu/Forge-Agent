"""MCP elicitation registry (spec modelcontextprotocol 2026-07-28).

Khi MCP server gửi `elicitation/create` giữa chừng một tool call, Forge hiện
form cho NGƯỜI DÙNG (web modal / TUI) rồi trả về:
  {"action": "accept"|"decline"|"cancel", "content": {...}  # accept dạng form
UI resolve qua POST /api/elicitation/{eid} hoặc trực tiếp trong TUI.

An toàn theo spec:
- Client phải hiện rõ server nào đang hỏi → mỗi request mang tên server.
- Form mode KHÔNG được dùng cho secret (password/token/api-key/…) → Forge
  tự động decline các request có field giống secret.
- Luôn cho phép decline/cancel.
"""
import asyncio
import contextvars
import re
import secrets
import time

PENDING: dict[str, dict] = {}
TIMEOUT_SEC = 180.0
_OWNER: contextvars.ContextVar[str] = contextvars.ContextVar("forge_elicitation_owner", default="")
_SESSION: contextvars.ContextVar[str] = contextvars.ContextVar("forge_elicitation_session", default="")
SECRET_HINTS = re.compile(r"pass(word)?|token|secret|api[_ -]?key|card|cvv|otp", re.IGNORECASE)

# đặc điểm nhận biết secret trong tên field schema (form mode bị cấm)


def bind_session(owner_id: str, session_id: str):
    """Trả token context; asyncio.Task tạo sau đó kế thừa owner/session."""
    return _OWNER.set(owner_id), _SESSION.set(session_id)


def reset_session(tokens) -> None:
    owner_token, session_token = tokens
    _SESSION.reset(session_token)
    _OWNER.reset(owner_token)


def create(server: str, message: str, schema: dict | None, url: str | None = None) -> str:
    cleanup()
    eid = "el_" + secrets.token_hex(5)
    fut: asyncio.Future = asyncio.get_event_loop().create_future()

    # Form mode xin secret → tự động decline (spec: MUST NOT qua form)
    if schema is not None and not url:
        props = " ".join((schema.get("properties") or {}).keys())
        if SECRET_HINTS.search(props) or SECRET_HINTS.search(message or ""):
            fut.set_result({"action": "decline", "content": None,
                            "_auto": "secret-like field — form mode bị cấm theo spec MCP"})

    PENDING[eid] = {
        "server": server,
        "message": message or "",
        "schema": schema if not url else None,   # form mode
        "url": url,                               # url mode (không tự mở)
        "future": fut,
        "owner_id": _OWNER.get(),
        "session_id": _SESSION.get(),
        "ts": time.time(),
    }
    return eid


async def wait(eid: str, timeout: float = TIMEOUT_SEC) -> dict:
    """Chờ người dùng quyết định. Timeout → cancel (người dùng không chọn gì)."""
    entry = PENDING.get(eid)
    if not entry:
        return {"action": "cancel", "content": None}
    try:
        return await asyncio.wait_for(entry["future"], timeout=timeout)
    except asyncio.TimeoutError:
        return {"action": "cancel", "content": None}
    finally:
        PENDING.pop(eid, None)


def resolve(eid: str, action: str, content: dict | None = None,
            owner_id: str | None = None) -> bool:
    entry = PENDING.get(eid)
    if (not entry or entry["future"].done()
            or (owner_id is not None and entry.get("owner_id", "") != owner_id)):
        return False
    if action not in ("accept", "decline", "cancel"):
        action = "cancel"
    result: dict = {"action": action, "content": None}
    if action == "accept" and isinstance(content, dict) and entry["schema"]:
        # chỉ giữ field khai báo trong schema (flat primitives) + required check
        props = entry["schema"].get("properties") or {}
        clean = {k: v for k, v in content.items() if k in props}
        missing = [k for k in (entry["schema"].get("required") or []) if k not in clean]
        if missing:
            result = {"action": "cancel", "content": None, "_missing": missing}
        else:
            result["content"] = clean
    entry["future"].set_result(result)
    return True


def snapshot(owner_id: str | None = None) -> list[dict]:
    """Danh sách pending cho UI polling (không có future)."""
    cleanup()
    return [
        {"id": eid, "server": e["server"], "message": e["message"],
         "schema": e["schema"], "url": e["url"]}
        for eid, e in PENDING.items() if not e["future"].done()
        and (owner_id is None or e.get("owner_id", "") == owner_id)
    ]


def cleanup() -> None:
    now = time.time()
    for eid in [x for x, e in PENDING.items() if now - e["ts"] > 600]:
        e = PENDING.pop(eid, None)
        if e and not e["future"].done():
            e["future"].set_result({"action": "cancel", "content": None})
