"""/loop — chạy định kỳ một tác vụ trong phiên (F1, theo Claude /loop).

- Trong tiến trình: vòng lặp sống bằng asyncio task (server/CLI) hoặc
  Textual set_interval (TUI) — server restart là dừng (ghi rõ cho người dùng).
- Mỗi nhịp chạy ĐỦ một lượt agent bình thường → tool + audit log + session
  persist như chat thường; web tải lại phiên là thấy các lượt loop.
-parse_interval: "45s" | "30m" | "1h" | số trần = phút.
"""
from __future__ import annotations

import asyncio
import time

_MIN_EVERY_S = 10
_MAX_EVERY_S = 7 * 24 * 3600


def parse_interval(raw: str, default_minutes: float = 30.0) -> int:
    """'45s'/'30m'/'2h'/'1d' → giây (clamp 10s..7d). Số trần → phút. Sai → default."""
    s = (raw or "").strip().lower()
    if not s:
        return int(default_minutes * 60)
    try:
        if s.endswith("s"):
            v = float(s[:-1])
        elif s.endswith("m"):
            v = float(s[:-1]) * 60
        elif s.endswith("h"):
            v = float(s[:-1]) * 3600
        elif s.endswith("d"):
            v = float(s[:-1]) * 86400
        else:
            v = float(s) * 60  # số trần = phút
    except ValueError:
        return int(default_minutes * 60)
    return int(max(_MIN_EVERY_S, min(v, _MAX_EVERY_S)))


def fmt_interval(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


class LoopManager:
    """Quản lý loop theo phiên — một phiên MỘT loop (start đè loop cũ)."""

    def __init__(self) -> None:
        self._loops: dict[str, dict] = {}

    def start(self, sid: str, every_s: int, text: str, mode: str,
              run_fn, max_runs: int = 0) -> dict:
        """run_fn(sid, text, mode) → coroutine chạy 1 lượt. max_runs=0 = vô hạn."""
        self.stop(sid)
        st: dict = {"every": int(every_s), "text": text, "mode": mode,
                    "runs": 0, "max": int(max_runs), "started": time.time(),
                    "last_ok": None, "task": None}

        async def _runner() -> None:
            try:
                while True:
                    st["runs"] += 1
                    try:
                        await run_fn(sid, st["text"], st["mode"])
                        st["last_ok"] = True
                    except Exception as e:  # noqa: BLE001 — lượt hỏng không chết loop
                        st["last_ok"] = False
                        st["last_error"] = str(e)[:200]
                    if st["max"] and st["runs"] >= st["max"]:
                        break
                    await asyncio.sleep(st["every"])
            finally:  # CancelledError tự lan — không cần bắt/re-raise
                cur = asyncio.current_task()
                ent = self._loops.get(sid)
                if ent and ent.get("task") is cur:
                    # giữ entry làm báo cáo (running=False, finished=True) — xoá khi stop/start
                    ent["task"] = None
                    ent["finished"] = True

        task = asyncio.create_task(_runner())
        st["task"] = task
        self._loops[sid] = st
        return self.status(sid)

    def stop(self, sid: str) -> bool:
        """Dừng loop đang chạy. Entry đã kết thúc tự nhiên → chỉ dọn dẹp, trả False."""
        ent = self._loops.pop(sid, None)
        if not ent:
            return False
        t = ent.get("task")
        if t and not t.done():
            t.cancel()
            return True
        return False

    def status(self, sid: str) -> dict:
        ent = self._loops.get(sid)
        if not ent:
            return {"running": False}
        running = bool(ent.get("task"))
        out = {"running": running, "finished": bool(ent.get("finished")),
               "every": ent["every"], "text": ent["text"], "mode": ent["mode"],
               "runs": ent["runs"], "max": ent["max"],
               "last_ok": ent.get("last_ok"),
               "since": int(time.time() - ent["started"])}
        if not running:
            out.pop("since")
        return out

    def status_all(self) -> list[dict]:
        return [{"session": sid, **self.status(sid)}
                for sid in list(self._loops) if self.status(sid)["running"]]


manager = LoopManager()
