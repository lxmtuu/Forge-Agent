"""Auto-commit mỗi lượt agent (B1 — opt-in, mặc định TẮT).

Theo pattern Aider (aider.chat/docs/git):
- workspace được `git init` ngầm + định danh bot (không đụng git toàn cục);
- sau lượt có thay đổi → commit với message dạng **Conventional Commits**
  do model RẺ (`model_roles.cheap`) sinh từ diff --stat + ngữ cảnh lượt;
- không có LLM / LLM lỗi → fallback heuristic (vẫn đúng format conventional);
- attribution trailer "🤖 forge-agent (auto-commit)" để lọc trong git log;
- KHÔNG BAO GIỜ raise — lỗi git/LLM chỉ bỏ qua lượt commit đó.
"""
from __future__ import annotations

import asyncio

from . import config

CONVENTIONAL = ("feat", "fix", "chore", "docs", "refactor", "test", "style",
                "perf", "build", "ci", "revert")
_MAX_SUBJECT = 72

_COMMIT_PROMPT = (
    "Sinh MỘT dòng commit message dạng Conventional Commits (feat|fix|chore|docs|"
    "refactor|test|perf: mô tả ngắn) cho thay đổi dưới đây. Chỉ IN đúng một dòng, "
    "không giải thích, không đặt trong dấu ngoặc kép, tối đa 72 ký tự.\n"
    "--- user yêu cầu ---\n{user}\n--- git diff --stat ---\n{stat}\n"
    "--- assistant đã làm ---\n{assistant}\n"
)


async def _git(ws, *args: str) -> tuple[int, str]:
    p = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(ws),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _err = await p.communicate()
    return p.returncode or 0, out.decode("utf-8", "replace")


async def ensure_repo(ws) -> None:
    """git init ngầm + định danh bot cục bộ (idempotent, không đụng config toàn cục)."""
    if not (ws / ".git").exists():
        await _git(ws, "init", "-q")
    await _git(ws, "config", "user.name", "Forge Agent")
    await _git(ws, "config", "user.email", "forge@localhost")
    await _git(ws, "config", "commit.gpgsign", "false")


def normalize_subject(raw: str, fallback: str = "cập nhật workspace") -> str:
    """Ép về đúng 1 dòng conventional ≤72 ký tự; thiếu prefix → đoán theo nội dung."""
    s = (raw or "").strip().strip("\"'`").splitlines()
    s = s[0].strip() if s else ""
    if len(s) > _MAX_SUBJECT:
        s = s[:_MAX_SUBJECT - 1].rstrip() + "…"
    low = s.lower()
    if low.split(":")[0].strip() in CONVENTIONAL and ":" in s:
        return s
    base = (s or fallback).strip() or fallback
    pick = (fallback + " " + s).lower()
    kind = "fix" if any(k in pick for k in ("fix", "lỗi", "bug", "sửa lỗi", "crash", "hotfix")) else "feat"
    subject = f"{kind}: {base}"[:_MAX_SUBJECT]
    if len(subject) >= _MAX_SUBJECT:
        subject = subject[:_MAX_SUBJECT - 1].rstrip() + "…"
    return subject


def _fallback_subject(user_text: str, stat: str) -> str:
    files = []
    for ln in stat.splitlines():
        if "|" in ln:
            name = ln.split("|")[0].strip().split("/")[-1]
            if name:
                files.append(name)
    base = (user_text or "").strip().splitlines()
    base = base[0].strip() if base else ""
    base = (base[:48] or (", ".join(files[:3]) or "cập nhật workspace"))
    kind = "fix" if any(k in (user_text or "").lower() for k in ("fix", "lỗi", "bug", "sửa")) else "feat"
    return f"{kind}: {base}"


def _cheap_model() -> str | None:
    from .llm import resolve_model
    try:
        return resolve_model("cheap")
    except Exception:  # noqa: BLE001 — không resolve được role thì dùng model mặc định
        return None


async def _llm_subject(user_text: str, stat: str, assistant_text: str) -> str | None:
    """Hỏi model rẻ sinh subject — bất kỳ lỗi nào → None (dùng fallback)."""
    if not config.get_api_key():
        return None
    try:
        from .llm import stream_chat
        prompt = _COMMIT_PROMPT.format(user=user_text[:600], stat=stat[:1200],
                                       assistant=(assistant_text or "")[:400])
        parts: list[str] = []
        async for ev in stream_chat([{"role": "user", "content": prompt}],
                                    model=_cheap_model()):
            if ev["type"] == "delta":
                parts.append(ev["text"])
        out = "".join(parts).strip()
        return out or None
    except Exception:  # noqa: BLE001 — LLM hỏng vẫn phải commit bằng fallback
        return None


async def commit_turn(ws, sid: str, user_text: str = "", assistant_text: str = "",
                      use_llm: bool = True) -> dict | None:
    """Commit mọi thay đổi của workspace sau một lượt. None = không có gì để commit."""
    try:
        await ensure_repo(ws)
        await _git(ws, "add", "-A")
        _rc, status = await _git(ws, "status", "--porcelain")
        if not status.strip():
            return None
        _rc, stat = await _git(ws, "diff", "--cached", "--stat")
        subject = None
        if use_llm:
            raw = await _llm_subject(user_text, stat, assistant_text)
            if raw:
                subject = normalize_subject(raw)
        if not subject:
            subject = normalize_subject(_fallback_subject(user_text, stat),
                                        fallback=_fallback_subject(user_text, stat))
        n_files = len([ln for ln in status.splitlines() if ln.strip()])
        await _git(ws, "commit", "-q", "-m", subject,
                   "-m", f"🤖 forge-agent (auto-commit · phiên {sid[:8]} · {n_files} file)")
        return {"subject": subject, "files": n_files}
    except Exception as e:  # noqa: BLE001 — auto-commit không được làm sập lượt chat
        print(f"[autocommit] bỏ qua: {e}")
        return None


def commit_turn_sync(ws, sid: str, user_text: str = "", assistant_text: str = "",
                     use_llm: bool = True) -> dict | None:
    """Bọc sync cho CLI/TUI (gọi trong thread riêng, có event loop riêng)."""
    return asyncio.run(commit_turn(ws, sid, user_text, assistant_text, use_llm))
