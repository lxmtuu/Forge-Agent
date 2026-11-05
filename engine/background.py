# -*- coding: utf-8 -*-
"""Lệnh shell chạy NỀN cho agent (chuẩn background tasks của Claude Code).

- start() → task id; tiến trình chạy độc lập, agent làm việc khác tiếp.
- status()/check() → trạng thái + output MỚI kể từ lần xem trước (offset).
- kill() → dừng tác vụ. Buffer giữ đuôi 60KB (log dài không phình RAM).
- Chỉ sống trong tiến trình hiện tại (không persist — tác vụ nền là việc tức thời).
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path

MAX_RUNNING = 8
MAX_TOTAL = 24         # vượt ngưỡng này dọn task đã xong cũ nhất
BUF_CAP = 60_000        # giữ đuôi 60KB
VIEW_CAP = 4000         # mỗi lần check trả tối đa 4KB output mới

_TASKS: dict[str, dict] = {}


def _reap() -> None:
    if len(_TASKS) <= MAX_TOTAL:
        return
    done = [(t["started"], k) for k, t in _TASKS.items() if t["status"] != "running"]
    for _, k in sorted(done)[: len(_TASKS) - MAX_TOTAL]:
        _TASKS.pop(k, None)


async def start(command: str, workspace: Path) -> tuple[str, str]:
    """Chạy lệnh nền. Trả (task_id, message)."""
    _reap()
    running = sum(1 for t in _TASKS.values() if t["status"] == "running")
    if running >= MAX_RUNNING:
        ids = ", ".join(k for k, t in _TASKS.items() if t["status"] == "running")
        return "", (f"Error: đã có {running} tác vụ nền đang chạy ({ids}) — "
                    "kiểm tra/kill bớt bằng check_background rồi hẵng chạy mới.")
    env = {**os.environ, "TERM": "dumb", "NO_COLOR": "1"}
    proc = await asyncio.create_subprocess_shell(
        command, cwd=str(workspace), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, env=env)
    tid = f"bg-{uuid.uuid4().hex[:6]}"
    t = {"id": tid, "cmd": command, "proc": proc, "buf": bytearray(), "off": 0,
         "status": "running", "code": None, "started": time.time(), "killed": False}
    _TASKS[tid] = t
    asyncio.create_task(_pump(t))
    return tid, f"[{tid}] đã chạy nền: {command}"


async def _pump(t: dict) -> None:
    try:
        stream = t["proc"].stdout
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            t["buf"].extend(chunk)
            if len(t["buf"]) > BUF_CAP:
                del t["buf"][: len(t["buf"]) - BUF_CAP]
    except Exception:
        pass
    finally:
        try:
            code = await t["proc"].wait()
        except Exception:
            code = -1
        t["code"] = code
        t["status"] = "killed" if t["killed"] else ("done" if code == 0 else "failed")


def get(tid: str) -> dict | None:
    return _TASKS.get(tid.strip())


def render(t: dict, incremental: bool) -> str:
    new = bytes(t["buf"][t["off"] if incremental else 0:]).decode("utf-8", "replace")
    t["off"] = len(t["buf"])
    if len(new) > VIEW_CAP:
        new = "…\n" + new[-VIEW_CAP:]
    status_vi = {"running": "⏳ đang chạy", "done": "✅ xong",
                 "failed": f"❌ lỗi (exit {t['code']})",
                 "killed": f"🛑 đã kill (exit {t['code']})"}.get(t["status"], t["status"])
    head = f"[{t['id']}] {status_vi} · {t['cmd'][:80]} · {time.time() - t['started']:.0f}s"
    if new.strip():
        return f"{head}\n--- output mới ---\n{new.rstrip()}"
    return head + ("\n(chưa có output mới)" if incremental else "")


async def kill(tid: str) -> str:
    t = get(tid)
    if not t:
        return f"Error: không có tác vụ «{tid}»"
    if t["status"] != "running":
        return f"[{t['id']}] đã kết thúc trước đó ({t['status']}) — không cần kill."
    t["killed"] = True
    try:
        t["proc"].kill()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(t["proc"].wait(), timeout=5)
    except asyncio.TimeoutError:
        return f"[{t['id']}] kill chậm — thử lại bằng check_background."
    # pump có thể chưa kịp chạy finally → tự cập nhật trạng thái ngay (tránh render sai)
    t["code"] = t["proc"].returncode
    t["status"] = "killed"
    return render(t, incremental=False)


def summary() -> str:
    if not _TASKS:
        return "(chưa có tác vụ nền nào)"
    rows = []
    for t in sorted(_TASKS.values(), key=lambda x: x["started"]):
        mark = {"running": "⏳", "done": "✅", "failed": "❌", "killed": "🛑"}.get(t["status"], "·")
        rows.append(f"{mark} [{t['id']}] {t['cmd'][:60]}")
    return "\n".join(rows)
