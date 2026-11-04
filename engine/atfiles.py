"""@file references — đính kèm nội dung file vào prompt (kiểu Cursor/OpenCode).

Gõ "@src/main.py xem hàm foo" → nội dung src/main.py được nối vào message
dưới dạng code block có nhãn, để LLM đọc trực tiếp.
"""
import re
from pathlib import Path

MAX_FILES = 5
MAX_BYTES_PER_FILE = 40_000
BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
               ".gz", ".tar", ".exe", ".dll", ".so", ".dylib", ".pyc", ".class",
               ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".mov", ".avi"}

# @path: đứng sau đầu dòng/khoảng trắng/open bracket; path = chữ, số, . / - _ + \
_AT_RE = re.compile(r"(?:^|(?<=\s))@([\w./\\\-+]+)", re.MULTILINE)


def _resolve(workspace: Path, ref: str) -> Path | None:
    ref = ref.replace("\\", "/").lstrip("/")
    p = (workspace / ref).resolve()
    try:
        p.relative_to(workspace.resolve())  # chặn path traversal
    except ValueError:
        return None
    return p if p.is_file() else None


def expand_at_refs(text: str, workspace: Path) -> tuple[str, list[str]]:
    """Trả về (text_mới_có_block_đính_kèm, danh_sách_đường_dẫn_đã_đính).

    - Tối đa MAX_FILES file, mỗi file cắt MAX_BYTES_PER_FILE.
    - File nhị phân / không tồn tại / ngoài workspace → bỏ qua im lặng.
    - Text gốc giữ nguyên (LLM vẫn thấy @path người dùng gõ).
    """
    workspace = Path(workspace)
    seen: list[str] = []
    blocks: list[str] = []
    for m in _AT_RE.finditer(text or ""):
        if len(seen) >= MAX_FILES:
            break
        ref = m.group(1)
        if ref in seen:
            continue
        p = _resolve(workspace, ref)
        if p is None or p.suffix.lower() in BINARY_EXTS:
            continue
        try:
            if p.stat().st_size > MAX_BYTES_PER_FILE * 4:
                continue  # file quá lớn — bỏ qua
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not raw.strip():
            continue
        seen.append(ref)
        if len(raw) > MAX_BYTES_PER_FILE:
            raw = raw[:MAX_BYTES_PER_FILE] + "\n… (cắt bớt — file dài)"
        lang = p.suffix.lstrip(".").lower() or "text"
        blocks.append(f"📎 File đính kèm @{ref}:\n```{lang}\n{raw}\n```")
    if not blocks:
        return text, []
    return text + "\n\n---\n" + "\n\n".join(blocks), seen
