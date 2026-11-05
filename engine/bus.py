"""Cross-session messaging (F2 — theo Claude v2.1.224 ListAgents/SendMessage).

Tin nhắn giữa các phiên: JSONL `data/messages/<sid>.jsonl` (ts/from/text),
mốc đã-đọc theo offset (`<sid>.read`). Lượt kế tiếp của phiên đích thấy gợi ý
INBOX trong system prompt và gọi tool `check_inbox` để đọc (tự đánh dấu đã đọc).
Kích thước text giới hạn 4000 ký tự/lượt (giống _MAX_LINE của audit log).
"""
from __future__ import annotations

import json
import time

from . import config

_MAX_TEXT = 4000


def _dir():
    return config.DATA_DIR / "messages"


def _path(sid: str):
    return _dir() / f"{sid}.jsonl"


def _offset_path(sid: str):
    return _dir() / f"{sid}.read"


def send(to_sid: str, from_sid: str, text: str) -> dict:
    """Ghi 1 tin vào hộp thư của to_sid. Trả entry đã ghi (không raise với OSError nhỏ)."""
    config.ensure_dirs()
    _dir().mkdir(parents=True, exist_ok=True)
    ent = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "from": (from_sid or "?")[:64],
           "text": (text or "").strip()[:_MAX_TEXT]}
    with _path(to_sid).open("a", encoding="utf-8") as f:
        f.write(json.dumps(ent, ensure_ascii=False) + "\n")
    return ent


def _entries(sid: str) -> list[dict]:
    try:
        raw = _path(sid).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for ln in raw.splitlines():
        try:
            d = json.loads(ln)
            if isinstance(d, dict) and "text" in d:
                out.append(d)
        except ValueError:
            continue
    return out


def _read_offset(sid: str) -> int:
    try:
        return max(0, int(_offset_path(sid).read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return 0


def inbox(sid: str) -> list[dict]:
    """Tin CHƯA ĐỌC (từ mốc offset trở đi) rồi tăng mốc = đánh dấu đã đọc."""
    allent = _entries(sid)
    off = _read_offset(sid)
    fresh = allent[off:]
    try:
        _offset_path(sid).write_text(str(len(allent)), encoding="utf-8")
    except OSError:
        pass
    return fresh


def peek(sid: str) -> list[dict]:
    """Tin chưa đọc nhưng KHÔNG đổi mốc (cho REST/UI xem trước)."""
    return _entries(sid)[_read_offset(sid):]


def unread_count(sid: str) -> int:
    return len(peek(sid))


def total(sid: str) -> int:
    return len(_entries(sid))
