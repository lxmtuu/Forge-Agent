"""Audit log — JSONL mỗi tool call của agent (OWASP LLM06: audit trail).

- File: <DATA_DIR>/audit/YYYY-MM-DD.jsonl (xoay theo ngày, UTF-8).
- Mỗi dòng: {ts, session, tool, source, ok, ms, args} — args đã cắt ngắn + MÃ HOÁ
  mọi chuỗi giống token (ghp_…, sk-or-…, Bearer …) → token không bao giờ nằm trong log.
- log_tool() KHÔNG BAO GIỜ raise — audit hỏng không được làm hỏng tool call.
- Xem: /audit [n] (CLI/TUI/Web) hoặc đọc file trực tiếp.
"""
import datetime
import json
import re
import time
from pathlib import Path

from . import config

_CAP = 200  # mỗi giá trị args cắt ở 200 ký tự
_MAX_LINE = 4000
# token có prefix đặc trưng (ghp_…, sk-…) → mask cả đuôi
_SECRET_PREFIX = re.compile(r"((?:ghp_|github_pat_|gho_|sk-or-v1-|sk-|xoxb-|AIza)\S+)", re.IGNORECASE)
# token sau nhãn (Bearer X · token=Y · key: Z) → giữ nhãn, mask giá trị
_SECRET_KV = re.compile(r"(\b(?:Bearer|token|key|password|passwd|secret)\s*[:=]?\s*\"?)(\S{4,})", re.IGNORECASE)


def scrub(text) -> str:
    """Chuỗi hoá an toàn để ghi log: mask token-like + cắt ngắn."""
    s = str(text if text is not None else "")
    s = _SECRET_KV.sub(lambda m: m.group(1) + m.group(2)[:4] + "…", s)
    s = _SECRET_PREFIX.sub(lambda m: m.group(1)[:6] + "…", s)
    if len(s) > _CAP:
        s = s[:_CAP] + "…"
    return s


def _dir() -> Path:
    d = config.DATA_DIR / "audit"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def log_tool(session_id: str, tool: str, args: dict | None, ok: bool,
             duration_ms: float | None = None, source: str = "internal",
             note: str = "") -> None:
    """Ghi 1 dòng audit. Không bao giờ raise."""
    try:
        entry = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "session": str(session_id)[:40],
            "tool": scrub(tool),
            "source": source,
            "ok": bool(ok),
            "ms": round(float(duration_ms)) if duration_ms is not None else None,
            "args": {scrub(k): scrub(v) for k, v in list((args or {}).items())[:8]},
        }
        if note:
            entry["note"] = scrub(note)
        line = json.dumps(entry, ensure_ascii=False)
        if len(line) > _MAX_LINE:
            line = line[:_MAX_LINE] + '"}'
        out = _dir() / f"{datetime.date.today().isoformat()}.jsonl"
        with out.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001 — audit không được phá tool call
        pass


def tail(n: int = 20) -> list[dict]:
    """n bản ghi MỚI NHẤT (mới nhất trước) — quét từ file hôm nay lùi lại tối đa 7 ngày."""
    out: list[dict] = []
    d = _dir()
    days = [datetime.date.today() - datetime.timedelta(days=i) for i in range(7)]
    for day in days:
        f = d / f"{day.isoformat()}.jsonl"
        if not f.exists():
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for ln in reversed(lines):
            if len(out) >= max(1, min(n, 10000)):
                return out
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def format_listing(n: int = 20, rows: list[dict] | None = None) -> str:
    """Chuỗi hiển thị cho /audit; caller multi-user có thể truyền rows đã lọc owner."""
    rows = tail(n) if rows is None else rows[:n]
    if not rows:
        return ("(chưa có tool call nào được ghi)\n"
                "Audit log ghi mọi tool call của agent vào data/audit/<ngày>.jsonl "
                "— chạy agent một lượt rồi xem lại ở đây.")
    lines = [f"### 📘 Audit log — {len(rows)} tool call mới nhất"]
    for e in rows:
        icon = "✅" if e.get("ok") else "❌"
        ms = f"{e['ms']}ms" if e.get("ms") is not None else "—"
        t = str(e.get("ts", ""))[11:19] or "??:??:??"
        args = " ".join(f"{k}={v}" for k, v in (e.get("args") or {}).items())[:90]
        note = f" · {e['note']}" if e.get("note") else ""
        lines.append(f"- `{t}` {icon} **{e.get('tool')}** ({e.get('source')}) · {ms}{note}"
                     + (f" — {args}" if args else ""))
    lines.append("File đầy đủ: data/audit/<ngày>.jsonl (JSONL, xoay theo ngày)")
    return "\n".join(lines)


def monotonic_ms(t0: float) -> float:
    return (time.monotonic() - t0) * 1000.0
