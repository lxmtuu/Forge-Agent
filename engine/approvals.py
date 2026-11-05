"""Interactive command-approval registry.

In "ask" mode, when the agent wants to run a warn/danger shell command it pauses
and emits an approval_request event with an id. The UI (web or CLI) collects the
user's decision via POST /api/approvals/{id} or the terminal, and the engine
resumes. Pending requests auto-deny after a timeout.
"""
import asyncio
import secrets
import time

PENDING: dict[str, dict] = {}
TIMEOUT_SEC = 180.0

VALID_DECISIONS = ("approve", "approve_always", "deny")


def create(command: str, level: str, reasons: list[str], owner_id: str = "") -> str:
    cleanup()
    aid = "appr_" + secrets.token_hex(5)
    PENDING[aid] = {
        "command": command,
        "level": level,
        "reasons": reasons,
        "owner_id": owner_id,
        "future": asyncio.get_event_loop().create_future(),
        "ts": time.time(),
    }
    return aid


async def wait(aid: str, timeout: float = TIMEOUT_SEC) -> str:
    """Await the user's decision. Returns 'deny' on timeout."""
    entry = PENDING.get(aid)
    if not entry:
        return "deny"
    try:
        return await asyncio.wait_for(entry["future"], timeout=timeout)
    except asyncio.TimeoutError:
        return "deny"
    finally:
        PENDING.pop(aid, None)


def resolve(aid: str, decision: str, owner_id: str | None = None) -> bool:
    entry = PENDING.get(aid)
    if (not entry or entry["future"].done()
            or (owner_id is not None and entry.get("owner_id", "") != owner_id)):
        return False
    if decision not in VALID_DECISIONS:
        decision = "deny"
    entry["future"].set_result(decision)
    return True


def cleanup() -> None:
    now = time.time()
    for aid in [a for a, e in PENDING.items() if now - e["ts"] > 600]:
        e = PENDING.pop(aid, None)
        if e and not e["future"].done():
            e["future"].set_result("deny")
