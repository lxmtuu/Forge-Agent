"""Custom agents — .forge/agents/<tên>.md (frontmatter + prompt, kiểu OpenCode).

Frontmatter hỗ trợ (tuỳ chọn):
    ---
    description: Review code theo chuẩn team
    model: anthropic/claude-sonnet-5.5     # optional — đè model phiên
    mode: agent                            # direct | agent | plan
    ---
Phần thân là QUY TẮC/NHÂN CÁCH của agent. Gõ:  /run <tên> <nhiệm vụ>
Vị trí: <workspace>/.forge/agents/  hoặc global  data/forge/agents/
"""
import re
from pathlib import Path

from . import config

_FM_LINE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")


def _candidates(workspace: Path, name: str):
    yield Path(workspace) / ".forge" / "agents" / f"{name}.md"
    yield config.DATA_DIR / "forge" / "agents" / f"{name}.md"


def _parse(md: str) -> dict:
    meta: dict = {"description": "", "model": "", "mode": ""}
    body = md.strip()
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            for line in body[3:end].splitlines():
                m = _FM_LINE.match(line.strip())
                if m and m.group(1) in ("description", "model", "mode"):
                    meta[m.group(1)] = m.group(2).strip()
            body = body[end + 4:].strip()
    meta["prompt"] = body
    return meta


def load(workspace: Path, name: str) -> dict | None:
    name = re.sub(r"[^A-Za-z0-9_\-]", "", name or "")
    if not name:
        return None
    for p in _candidates(workspace, name):
        try:
            if p.is_file():
                meta = _parse(p.read_text(encoding="utf-8", errors="replace"))
                if not meta["prompt"]:
                    continue
                meta["name"] = name
                meta["path"] = str(p)
                if meta["mode"] not in ("direct", "agent", "plan", ""):
                    meta["mode"] = ""
                return meta
        except OSError:
            continue
    return None


def list_agents(workspace: Path) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for base in (Path(workspace) / ".forge" / "agents",
                 config.DATA_DIR / "forge" / "agents"):
        try:
            for p in sorted(base.glob("*.md")):
                if p.stem in seen:
                    continue  # project đè global
                try:
                    meta = _parse(p.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                if not meta["prompt"]:
                    continue
                seen.add(p.stem)
                out.append({"name": p.stem, "description": meta["description"],
                            "model": meta["model"], "mode": meta["mode"]})
        except OSError:
            continue
    return out


def expand(text: str, workspace: Path) -> tuple[str, str, str] | None:
    """Xử lý '/run <tên> <task>'. Trả (text_mới, model, mode) hoặc None."""
    if not text.strip().lower().startswith("/run"):
        return None
    parts = text.strip()[4:].strip().split(None, 1)
    if not parts:
        return None
    name = parts[0]
    task = parts[1].strip() if len(parts) > 1 else "Bắt đầu làm việc."
    meta = load(workspace, name)
    if meta is None:
        return None
    new_text = (f"[AGENT RULES — đang đóng vai agent «{meta['name']}» "
                f"(quy tắc từ .forge/agents/{name}.md, tuân thủ tuyệt đối)]\n"
                f"{meta['prompt']}\n\n=== NHIỆM VỤ ===\n{task}")
    return new_text, meta["model"], meta["mode"]
