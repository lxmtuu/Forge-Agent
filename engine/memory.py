# -*- coding: utf-8 -*-
"""Bộ nhớ dài hạn của Forge: MEMORY.md (dự án + toàn cục).

- ``# <nội dung>`` (quick-memory, chuẩn Claude Code) → ghi ngay, không tốn LLM.
- ``memory_overview`` → xem những gì đang được nạp (cho lệnh /memory).
- ``clear_memory`` → xoá MEMORY.md dự án (có bản sao .bak).

Dùng chung cho tool ``memory_save`` (agent tự ghi) và lệnh ``#``/``/memory``.
"""
from __future__ import annotations

import time
from pathlib import Path

CAP_BYTES = 8192   # cap tổng MEMORY.md
KEEP_BYTES = 6000  # khi vượt cap: giữ 6KB cuối (mới nhất)
ENTRY_MAX = 500


def _clip(old: str) -> str:
    if len(old.encode("utf-8")) <= CAP_BYTES:
        return old
    lines = old.splitlines()
    keep: list[str] = []
    size = 0
    for ln in reversed(lines):
        size += len(ln.encode("utf-8")) + 1
        if size > KEEP_BYTES:
            break
        keep.append(ln)
    return "\n".join(reversed(keep)).lstrip("\n") + "\n"


def append_entry(workspace: Path, content: str) -> str:
    """Ghi 1 dòng ``- [ngày] nội dung`` vào <ws>/MEMORY.md. Trả lời tiếng Việt."""
    content = str(content).strip()
    if not content:
        return "Error: thiếu content"
    mem = workspace / "MEMORY.md"
    try:
        old = mem.read_text(encoding="utf-8", errors="replace") if mem.exists() else ""
    except OSError:
        old = ""
    old = _clip(old)
    stamp = time.strftime("%Y-%m-%d")
    entry = f"- [{stamp}] {content.replace(chr(10), ' ')[:ENTRY_MAX]}"
    if entry in old:
        return f"Đã có trong MEMORY.md (bỏ qua trùng): {content[:80]}"
    try:
        mem.write_text((old.rstrip() + "\n" if old.strip() else "") + entry + "\n",
                       encoding="utf-8")
    except OSError as e:
        return f"Error: không ghi được MEMORY.md: {e}"
    return f"Đã ghi vào MEMORY.md: {content[:100]}"


def quick_memory(workspace: Path, text: str) -> str:
    """'# <nội dung>' → ghi nhớ nhanh; trả câu trả lời ngắn có 🧠."""
    return "🧠 " + append_entry(workspace, text)


def memory_overview(workspace: Path, data_dir: Path | None = None) -> str:
    """Tổng kêeh bộ nhớ đang nạp — cho lệnh /memory (xem, không tốn LLM)."""
    from .context_files import load_with_imports

    data_dir = data_dir or _default_data_dir()
    rows: list[str] = ["🧠 Bộ nhớ đang nạp vào mỗi phiên:"]

    g = data_dir / "AGENTS.md"
    if g.is_file():
        n = len(g.read_text(encoding="utf-8", errors="replace"))
        imp = _count_imports(g)
        rows.append(f"  • Quy tắc toàn cục  data/AGENTS.md — ✓ {_kb(n)}"
                    + (f" ({imp} @import)" if imp else ""))
    else:
        rows.append("  • Quy tắc toàn cục  data/AGENTS.md — chưa có")

    rules = next(((workspace / nm) for nm in ("AGENTS.md", "AGENTS.txt", "CLAUDE.md")
                  if (workspace / nm).is_file()), None)
    if rules:
        text = load_with_imports(rules)
        n = len(text.encode("utf-8"))
        imp = _count_imports(rules)
        rows.append(f"  • Quy tắc dự án      {rules.name} — ✓ {_kb(n)}"
                    + (f" ({imp} @import)" if imp else ""))
    else:
        rows.append("  • Quy tắc dự án      AGENTS.md — chưa có (/init để sinh)")

    mem = workspace / "MEMORY.md"
    if mem.is_file():
        entries = [l for l in mem.read_text(encoding="utf-8", errors="replace").splitlines()
                   if l.strip().startswith("- [")]
        rows.append(f"  • MEMORY.md (dự án) — ✓ {_kb(len(mem.read_text(encoding='utf-8', errors='replace').encode()))} · "
                    f"{len(entries)} ghi nhớ")
        if entries:
            rows.append(f"    Gần nhất: {entries[-1][:120]}")
    else:
        rows.append("  • MEMORY.md (dự án) — chưa có")

    gmem = data_dir / "MEMORY.md"
    rows.append("  • MEMORY.md (toàn cục) — " +
                (f"✓ {_kb(len(gmem.read_text(encoding='utf-8', errors='replace').encode()))}" if gmem.is_file() else "chưa có"))
    rows.append("  💡 Gõ «# nội dung» → ghi nhớ nhanh · «/memory clear» → xoá MEMORY.md dự án")
    return "\n".join(rows)


def clear_memory(workspace: Path) -> str:
    """Xoá MEMORY.md dự án (giữ bản .bak)."""
    mem = workspace / "MEMORY.md"
    if not mem.is_file():
        return "(chưa có MEMORY.md để xoá)"
    try:
        (workspace / "MEMORY.md.bak").write_text(
            mem.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        mem.unlink()
    except OSError as e:
        return f"⚠ Không xoá được: {e}"
    return "🗑 Đã xoá MEMORY.md (bản sao: MEMORY.md.bak)"


def _count_imports(path: Path) -> int:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    in_fence = False
    n = 0
    for line in raw.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and "`" not in line:
            n += line.count("@")
    return n


def _kb(n: int) -> str:
    return f"{n / 1024:.1f}KB" if n >= 1024 else f"{n}B"


def _default_data_dir() -> Path:
    from . import config
    return config.DATA_DIR
