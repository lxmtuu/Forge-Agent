"""Repo map kiểu Aider (A5) — bản đồ cấu trúc + symbol nén gọn cho context.

Không tree-sitter: trích symbol bằng regex theo ngôn ngữ (py/js-ts/go/rs),
rank theo SỐ FILE KHÁC tham chiếu tên symbol (PageRank đơn giản hoá — đủ tốt
cho workspace vừa), budget ký tự chặt (mặc định 6KB, auto-nạp chỉ khi ≤4KB).

API:
  build(workspace)  → dict {map, files, symbols, truncated, cached}
  auto_context(ws)  → str ("" nếu không đủ điều kiện tự nạp)
"""
from __future__ import annotations

import re
from pathlib import Path

BUDGET_CHARS = 6000
AUTO_MAX_CHARS = 4000      # auto-nạp vào system prompt chỉ khi map gọn hơn thế này
AUTO_MAX_FILES = 60        # …và workspace không quá nhiều file (tránh đốt token)
MAX_FILES_SCAN = 400       # quét tối đa — lớn hơn thì bỏ symbol, chỉ còn cây thư mục
SKIP_DIRS = {".git", ".forge", ".venv", "venv", "__pycache__", "node_modules",
             "dist", "build", ".mypy_cache", ".ruff_cache", ".coverage", "data"}

# regex trích symbol theo phần mở rộng — giữ GỌN, chấp nhận không bắt hết
_PATTERNS: dict[str, list[re.Pattern[str]] | None] = {
    ".py": [re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),
            re.compile(r"^\s*class\s+([A-Za-z_]\w*)")],
    ".js": [re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
            re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"),
            re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(")],
    ".ts": None, ".tsx": None, ".jsx": None,   # dùng chung bộ js
    ".go": [re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"),
            re.compile(r"^type\s+([A-Za-z_]\w*)\s+struct")],
    ".rs": [re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"),
            re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)")],
}
for _k in (".ts", ".tsx", ".jsx"):
    _PATTERNS[_k] = _PATTERNS[".js"]

_CACHE: dict[tuple[str, int, tuple], dict] = {}


def _iter_files(workspace: Path) -> list[Path]:
    out: list[Path] = []
    try:
        for p in sorted(workspace.rglob("*")):
            rel = p.relative_to(workspace)
            if any(part in SKIP_DIRS for part in rel.parts[:-1]) or p.name in SKIP_DIRS:
                continue
            if p.is_file() and p.stat().st_size < 300_000:
                out.append(p)
                if len(out) >= MAX_FILES_SCAN:
                    break
    except OSError:
        pass
    return out


def _symbols(text: str, suffix: str) -> list[str]:
    pats = _PATTERNS.get(suffix)
    if not pats:
        return []
    found: list[str] = []
    for ln in text.splitlines():
        for pat in pats:
            m = pat.match(ln)
            if m:
                name = m.group(1)
                if name not in found:
                    found.append(name)
                break
        if len(found) >= 12:   # cap symbol/file — map phải gọn
            break
    return found


def _signature(files: list[Path]) -> tuple:
    sig = []
    for p in files:
        try:
            st = p.stat()
            # ĐƯỜNG DẪN ĐẦY ĐỦ + MỌI file đã quét: tránh cache hit chéo workspace
            # và cache cũ khi file sau phần tử 200 đổi (test_v032-T1).
            sig.append((str(p.resolve()), st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    return tuple(sig)


def build(workspace: Path, budget: int = BUDGET_CHARS) -> dict:
    """Dựng map: mỗi dòng `đường/dẫn.py — ClassA, fn_b (n refs)`; rank refs giảm dần."""
    workspace = Path(workspace)
    files = _iter_files(workspace)
    # budget phải nằm trong key — budget khác là map khác (bug bắt bởi T1)
    sig = (str(workspace), budget, _signature(files))
    hit = _CACHE.get(sig)
    if hit is not None:
        return {**hit, "cached": True}

    texts: dict[Path, str] = {}
    syms: dict[Path, list[str]] = {}
    for p in files:
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        texts[p] = t
        s = _symbols(t, p.suffix.lower())
        if s:
            syms[p] = s

    # rank: symbol được nhắc trong file KHÁC nhiều → rank cao
    all_syms = [x for v in syms.values() for x in v]
    def refs_of(name: str) -> int:
        n = 0
        for p2, t2 in texts.items():
            if name in syms.get(p2, []) or []:
                continue
            if name in t2:
                n += 1
        return n
    ref_count: dict[str, int] = {}
    for name in set(all_syms):
        if len(name) >= 4:                       # tên quá ngắn → nhiễu
            ref_count[name] = refs_of(name)

    lines: list[str] = []
    used = 0
    truncated = False
    shown = 0
    # file có symbol + được nhắc nhiều trước, rồi file thường theo tên
    ordered = sorted(texts.keys(),
                     key=lambda p: (-(max((ref_count.get(x, 0) for x in syms.get(p, [])),
                                          default=0)), str(p.relative_to(workspace))))
    for p in ordered:
        rel = p.relative_to(workspace).as_posix()
        ss = syms.get(p, [])
        rc = max((ref_count.get(x, 0) for x in ss), default=0)
        line = f"{rel} — {', '.join(ss[:8])} ({rc} refs)" if ss else rel
        if used + len(line) + 1 > budget:
            truncated = True
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1

    header = f"[Repo map] {len(texts)} file · {len(set(all_syms))} symbol · budget {budget} ký tự"
    map_text = header + "\n" + "\n".join(lines)
    if truncated:
        map_text += f"\n… (còn {len(texts) - shown} file chưa hiện — dùng tool repo_map với budget lớn hơn)"
    result = {"map": map_text, "files": len(texts), "symbols": len(set(all_syms)),
              "truncated": truncated, "cached": False}
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[sig] = result
    return result


def auto_context(workspace: Path) -> str:
    """Chuỗi chèn system prompt — chỉ khi workspace nhỏ (đúng tinh thần Aider:
    map cho repo vừa; repo lớn dùng tool repo_map chủ động)."""
    r = build(workspace, budget=AUTO_MAX_CHARS)
    if not r["files"] or r["files"] > AUTO_MAX_FILES or r["truncated"]:
        return ""
    return "\n\n## Bản đồ workspace (repo map — tự nạp)\n" + r["map"]
