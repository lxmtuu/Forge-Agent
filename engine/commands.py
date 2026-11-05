"""Custom slash commands — .forge/commands/<name>.md + mọi SKILL.md (chuẩn Agent Skills).

- Thư mục dự án:  <workspace>/.forge/commands/<name>.md
- Thư mục toàn cục: <DATA_DIR>/forge/commands/<name>.md
- Frontmatter `--- ... ---` (nếu có) được bỏ; thay `$ARGUMENTS` bằng phần
  text sau tên lệnh. Dùng:  /deploy staging  → nội dung deploy.md.
"""
import re
from pathlib import Path

from . import config

_CMD_RE = re.compile(r"^/([A-Za-z0-9_\-]+)(?:\s+(.+))?$", re.DOTALL)


def _strip_frontmatter(md: str) -> str:
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            md = md[end + 4:]
    return md.strip()


def _candidates(workspace: Path, name: str):
    # CHỈ file lệnh .forge/commands — skill (kể cả dẹt) đi qua find_skill để kiểm tra trust
    yield Path(workspace) / ".forge" / "commands" / f"{name}.md"
    yield config.DATA_DIR / "forge" / "commands" / f"{name}.md"


def find_custom(workspace: Path, name: str) -> Path | None:
    """Chỉ tìm FILE LỆNH .forge/commands — skill mọi định dạng xử lý riêng trong expand()."""
    for p in _candidates(workspace, name):
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def _finish(md: str, args: str) -> str | None:
    md = _strip_frontmatter(md)
    if not md:
        return None
    if "$ARGUMENTS" in md or "$ARGS" in md:
        return md.replace("$ARGUMENTS", args).replace("$ARGS", args)
    return md + (f"\n\n=== USER ARGUMENTS ===\n{args}" if args else "")


def expand(text: str, workspace: Path) -> str | None:
    """Nếu text là /<name> có file command/skill tương ứng → trả prompt đã expand.

    Trả None khi: không phải dạng /cmd, là lệnh built-in (có handler riêng),
    không tìm thấy file, hoặc skill project CHƯA ĐƯỢC TIN (dùng blocked_reason
    để phân biệt 'không rõ' với 'bị chặn').
    """
    if not text or not text.startswith("/"):
        return None
    m = _CMD_RE.match(text.strip())
    if not m:
        return None
    name, args = m.group(1), (m.group(2) or "").strip()
    p = find_custom(workspace, name)
    if p is not None:
        try:
            md = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        return _finish(md, args)
    # skill chuẩn Agent Skills (mọi nguồn) — skill project phải đã được tin
    from .skills import find_skill
    sk = find_skill(workspace, name)
    if sk is None or not sk.get("trusted", True):
        return None
    try:
        md = Path(sk["path"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _finish(md, args)


def blocked_reason(workspace: Path, text: str) -> str | None:
    """Nếu /<tên> trỏ vào skill project chưa tin → trả lời hướng dẫn cho NGƯỜI DÙNG.

    (Không trả nội dung skill cho model — chống prompt injection từ repo lạ.)
    """
    if not text or not text.startswith("/"):
        return None
    m = _CMD_RE.match(text.strip())
    if not m:
        return None
    from .skills import find_skill
    sk = find_skill(workspace, m.group(1))
    if sk and sk["source"] == "project" and not sk.get("trusted", True):
        return (f"🔒 Skill '{sk['name']}' nằm trong dự án nhưng CHƯA ĐƯỢC TIN "
                f"(không nạp vào model — chống prompt injection từ repo lạ).\n"
                f"   Xem nội dung trước: {sk['path']}\n"
                f"   Chấp nhận: /skills trust {sk['name']}")
    return None
