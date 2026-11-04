"""Skills — SKILL.md model-invoked (chuẩn Claude Code).

- Vị trí: <workspace>/.forge/skills/<tên>.md (project) hoặc data/forge/skills/ (global).
- Frontmatter: `description` (bắt buộc — là "trigger"), `disable-model-invocation: true`
  nếu chỉ muốn gọi tay bằng /<tên>.
- Progressive disclosure: chỉ name + description (~100 tokens/skill) vào system prompt;
  LLM tự quyết định ĐỌC file (tool read_file) khi nhiệm vụ khớp description.
- Gõ tay: /<tên> [args] — được engine/commands.py expand (đã nhận cả .forge/skills/).
"""
import re
from pathlib import Path

from . import config

_FM = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
MAX_DESC = 200


def _dirs(workspace: Path):
    yield Path(workspace) / ".forge" / "skills"
    yield config.DATA_DIR / "forge" / "skills"


def _parse(md: str) -> dict:
    meta: dict = {"description": "", "disable_model_invocation": False}
    body = md.strip()
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            for line in body[3:end].splitlines():
                m = _FM.match(line.strip())
                if not m:
                    continue
                k, v = m.group(1), m.group(2).strip()
                if k == "description":
                    meta["description"] = v[:MAX_DESC]
                elif k in ("disable-model-invocation", "disable_model_invocation"):
                    meta["disable_model_invocation"] = v.lower() in ("true", "1", "yes")
            body = body[end + 4:]
    return meta


def list_skills(workspace: Path) -> list[dict]:
    """Danh sách skills (project đè global) — name + description cho system prompt."""
    out: list[dict] = []
    seen: set[str] = set()
    for base in _dirs(workspace):
        try:
            for p in sorted(base.glob("*.md")):
                if p.stem in seen:
                    continue
                try:
                    meta = _parse(p.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                if not meta["description"]:
                    continue
                seen.add(p.stem)
                out.append({
                    "name": p.stem,
                    "description": meta["description"],
                    "path": str(p),
                    "model_invocable": not meta["disable_model_invocation"],
                })
        except OSError:
            continue
    return out


def skills_block(workspace: Path) -> str:
    """Đoạn chèn vào system prompt — chi phí ~100 tokens/skill, không nạp body."""
    skills = [s for s in list_skills(workspace) if s["model_invocable"]]
    if not skills:
        return ""
    lines = [
        "=== SKILLS — quy trình tự động hóa sẵn có của dự án (model-invoked) ===",
        "Khi nhiệm vụ người dùng khớp mô tả một skill bên dưới, hãy DÙNG tool read_file "
        "đọc nội dung file của skill đó NGAY và làm theo từng bước trong đó.",
    ]
    for s in skills:
        lines.append(f"- /{s['name']} — {s['description']}")
        lines.append(f"  (đọc: .forge/skills/{s['name']}.md)")
    return "\n".join(lines) + "\n"
