"""Custom slash commands — .forge/commands/<name>.md (chuẩn OpenCode/Claude Code).

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
    # skills của Claude Code ≈ lệnh: .forge/skills/<name>.md cũng được nhận (alias)
    yield Path(workspace) / ".forge" / "commands" / f"{name}.md"
    yield Path(workspace) / ".forge" / "skills" / f"{name}.md"
    yield config.DATA_DIR / "forge" / "commands" / f"{name}.md"


def find_custom(workspace: Path, name: str) -> Path | None:
    for p in _candidates(workspace, name):
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def expand(text: str, workspace: Path) -> str | None:
    """Nếu text là /<name> có file markdown tương ứng → trả prompt đã expand.

    Trả None khi: không phải dạng /cmd, là lệnh built-in (có handler riêng),
    hoặc không tìm thấy file command.
    """
    if not text or not text.startswith("/"):
        return None
    m = _CMD_RE.match(text.strip())
    if not m:
        return None
    name, args = m.group(1), (m.group(2) or "").strip()
    p = find_custom(workspace, name)
    if p is None:
        return None
    try:
        md = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    md = _strip_frontmatter(md)
    if not md:
        return None
    if "$ARGUMENTS" in md or "$ARGS" in md:
        return md.replace("$ARGUMENTS", args).replace("$ARGS", args)
    return md + (f"\n\n=== USER ARGUMENTS ===\n{args}" if args else "")
