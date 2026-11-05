"""Skills — chuẩn mở Agent Skills (SKILL.md, agentskills.io) + tương thích ngược v0.11.

Format chuẩn (v0.15): <nguon-skills>/<tên>/SKILL.md (+ scripts/ references/ assets/)
Tương thích ngược: file dẹt <nguon-skills>/<tên>.md (v0.11) vẫn nạp, đánh dấu fmt="flat".

Nơi quét (thứ tự ưu tiên — project đè user):
  1. <workspace>/.forge/skills/      (project — thư mục riêng forge)
  2. <workspace>/.agents/skills/     (project — quy ước cross-client: Codex/Cursor/Copilot/Gemini)
  3. <workspace>/.claude/skills/     (project — tương thích Claude Code, kho skill lớn nhất)
  4. ~/.forge/skills/                (user — cài bằng /skills add)
  5. <DATA_DIR>/forge/skills/        (global-legacy — vị trí cũ v0.11)
  6. <repo>/bundled-skills/          (built-in — đi kèm app, ưu tiên thấp nhất)

Trust gating (khuyến nghị của chuẩn): skill PROJECT đến từ repo (có thể là repo lạ
vừa clone) → CHƯA tin thì KHÔNG nạp vào catalog model; người dùng chấp nhận bằng
/skills trust <tên>. User/legacy/built-in luôn tin. Lưu theo workspace trong
<DATA_DIR>/trusted-skills.json.

Progressive disclosure 3 tầng theo spec: catalog (name+description ~50-100 tokens)
→ body SKILL.md (LLM tự đọc khi khớp) → scripts/references (đọc/chạy khi body dẫn tới).
Lenient validation theo khuyến nghị chuẩn: cảnh báo vẫn nạp, chỉ bỏ khi thiếu description
hoặc YAML vỡ hoàn toàn. Diagnostics trả về cho /skills.
"""
import json
import re
from pathlib import Path

from . import config

_FM_LINE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
_NAME_OK = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_DESC_SPEC = 1024      # spec: description ≤ 1024 ký tự
MAX_DESC_CATALOG = 200    # catalog cắt ngắn cho nhẹ token
MAX_SKILLS = 200          # bounds: chống quét phình

# (nhãn nguồn, hàm tạo đường dẫn) — thứ tự = precedence, trước đè sau
def _sources(workspace: Path):
    ws = Path(workspace)
    yield "project", ws / ".forge" / "skills"
    yield "project", ws / ".agents" / "skills"
    yield "project", ws / ".claude" / "skills"
    yield "user", _user_skills_dir()
    yield "global-legacy", config.DATA_DIR / "forge" / "skills"
    yield "built-in", Path(__file__).resolve().parent.parent / "bundled-skills"


def _user_skills_dir() -> Path:
    """User scope theo chuẩn (call-time để test monkeypatch được Path.home)."""
    return Path.home() / ".forge" / "skills"


def _try_yaml(block: str) -> dict | None:
    """Parse YAML frontmatter; trả None nếu vỡ hoàn toàn (khách hàng có pyyaml hay không cũng chạy)."""
    try:
        import yaml
        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else None
    except ImportError:
        return _fallback_yaml(block)
    except Exception:
        # YAML vỡ — lỗi phổ biến nhất: giá trị chưa quote chứa ':' → fallback
        return _fallback_yaml(block)


def _fallback_yaml(block: str) -> dict | None:
    """Parser tối giản: 'key: value' + map con thụt đầu dòng (đủ cho frontmatter skill)."""
    out: dict = {}
    cur_map: dict | None = None
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line[:1] in (" ", "\t") and cur_map is not None:
            m = _FM_LINE.match(line.strip())
            if m:
                cur_map[m.group(1)] = m.group(2).strip().strip("\"'")
            continue
        cur_map = None
        m = _FM_LINE.match(line.strip())
        if not m:
            return None  # dòng không hiểu được → coi như YAML vỡ
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            cur_map = {}
            out[key] = cur_map
        else:
            out[key] = val.strip("\"'")
    return out


def _split_frontmatter(md: str) -> tuple[str, str] | None:
    """Trả (block_yaml, body) nếu file có frontmatter --- ... --- ở đầu; ngược lại None."""
    if not md.startswith("---"):
        return None
    end = md.find("\n---", 3)
    if end == -1:
        return None
    body = md[end + 4:]
    if body.startswith("\n"):
        body = body[1:]
    return md[3:end].strip("\n"), body


def _parse_skill(text: str, name: str, fmt: str) -> tuple[dict, list[str]]:
    """Parse 1 SKILL.md → (meta, diags). Lenient: warn vẫn nạp; chỉ hỏng khi thiếu description/YAML vỡ."""
    diags: list[str] = []
    meta: dict = {"name": name, "description": "", "model_invocable": True,
                  "license": "", "compatibility": "", "metadata": {}, "allowed_tools": ""}
    parts = _split_frontmatter(text)
    if parts is None:
        # không frontmatter — chỉ chấp nhận ở format flat cũ (không có mô tả → bỏ)
        return meta, diags
    block, body = parts
    data = _try_yaml(block)
    if data is None:
        diags.append("YAML frontmatter không đọc được → bỏ skill")
        meta["broken"] = True
        return meta, diags

    name_fm = str(data.get("name") or "").strip()
    if name_fm and name_fm != name:
        diags.append(f"name '{name_fm}' ≠ tên {'thư mục' if fmt == 'standard' else 'file'} "
                     f"'{name}' → vẫn nạp (lenient), dùng tên '{name}'")
    if len(name_fm) > 64:
        diags.append("name vượt 64 ký tự → vẫn nạp (lenient)")
    if name_fm and not _NAME_OK.match(name_fm):
        diags.append(f"name '{name_fm}' không kebab-case [a-z0-9-] → vẫn nạp (lenient)")
    if "anthropic" in name_fm.lower() or "claude" in name_fm.lower():
        diags.append("name chứa 'anthropic'/'claude' — spec cấm khi publish")

    desc = str(data.get("description") or "").strip()
    if not desc:
        diags.append("thiếu description (trigger bắt buộc theo spec) → BỎ skill")
        meta["broken"] = True
        return meta, diags
    if "<" in desc or ">" in desc:
        desc = desc.replace("<", "(").replace(">", ")")
        diags.append("description có dấu < > (spec cấm) → đã thay bằng ( )")
    if len(desc) > MAX_DESC_SPEC:
        desc = desc[:MAX_DESC_SPEC]
        diags.append(f"description vượt {MAX_DESC_SPEC} ký tự → cắt")

    if str(data.get("disable-model-invocation", "")).lower() in ("true", "1", "yes"):
        meta["model_invocable"] = False
    meta["description"] = desc
    meta["license"] = str(data.get("license") or "").strip()
    meta["compatibility"] = str(data.get("compatibility") or "").strip()[:500]
    md_map = data.get("metadata")
    if isinstance(md_map, dict):
        meta["metadata"] = {str(k): str(v) for k, v in list(md_map.items())[:20]}
    at = data.get("allowed-tools") or data.get("allowed_tools")
    if isinstance(at, list):
        at = " ".join(str(x) for x in at)
    meta["allowed_tools"] = str(at or "").strip()  # ⚗️ experimental — chỉ hiển thị
    return meta, diags


def _iter_skill_files(base: Path, source: str):
    """Yield (name, path, fmt, source) từ 1 thư mục skills: chuẩn <tên>/SKILL.md trước, flat .md sau."""
    if not base.is_dir():
        return
    try:
        std = sorted(p for p in base.glob("*/SKILL.md") if p.is_file())
    except OSError:
        std = []
    for p in std:
        yield p.parent.name, p, "standard", source
    try:
        flat = sorted(p for p in base.glob("*.md") if p.is_file() and p.name != "SKILL.md")
    except OSError:
        flat = []
    for p in flat:
        yield p.stem, p, "flat", source


def _trust_file() -> Path:
    return config.DATA_DIR / "trusted-skills.json"


def _ws_key(workspace: Path) -> str:
    try:
        return str(Path(workspace).resolve())
    except OSError:
        return str(workspace)


def load_trusted(workspace: Path) -> set[str]:
    """Tên các skill PROJECT đã được người dùng chấp nhận cho workspace này."""
    try:
        raw = json.loads(_trust_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(raw, dict):
        return set()
    val = raw.get(_ws_key(workspace))
    return {str(x) for x in val} if isinstance(val, list) else set()


def save_trusted(workspace: Path, names: set[str]) -> None:
    """Ghi nhận thêm các skill project được tin (gộp với danh sách cũ)."""
    f = _trust_file()
    try:
        raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    key = _ws_key(workspace)
    cur = {str(x) for x in (raw.get(key) or []) if isinstance(x, str)}
    cur |= set(names)
    raw[key] = sorted(cur)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def list_skills(workspace: Path) -> tuple[list[dict], list[str]]:
    """Danh sách skills theo precedence (trước đè sau) + diagnostics.

    Mỗi bản ghi: name, description, path, base_dir, source, fmt, model_invocable,
    license, compatibility, metadata, allowed_tools, scripts/references/assets (bool), diags.
    """
    out: list[dict] = []
    diags: list[str] = []
    seen: dict[str, dict] = {}
    total = 0
    trusted = load_trusted(workspace)
    for source, base in _sources(workspace):
        for name, path, fmt, src in _iter_skill_files(base, source):
            total += 1
            if total > MAX_SKILLS:
                diags.append(f"⚠ quá {MAX_SKILLS} mục — dừng quét (bounds theo khuyến nghị chuẩn)")
                break
            if name in seen:
                diags.append(f"⚠ '{name}' từ {src} bị che bởi nguồn "
                             f"{seen[name]['source']} (project đè user)")
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                diags.append(f"⚠ không đọc được {path}: {e}")
                continue
            meta, d = _parse_skill(text, name, fmt)
            if meta.get("broken"):
                diags.append(f"✗ [{src}] {name}: " + "; ".join(d))
                continue
            diags.extend(f"⚠ [{src}] {name}: {x}" for x in d)
            bd = path.parent if fmt == "standard" else path.parent
            seen[name] = {
                "name": name,
                "description": meta["description"],
                "path": str(path),
                "base_dir": str(bd),
                "source": src,
                "fmt": fmt,
                "model_invocable": meta["model_invocable"],
                "license": meta["license"],
                "compatibility": meta["compatibility"],
                "metadata": meta["metadata"],
                "allowed_tools": meta["allowed_tools"],
                "scripts": (bd / "scripts").is_dir(),
                "references": (bd / "references").is_dir(),
                "assets": (bd / "assets").is_dir(),
                "trusted": (src != "project") or (name in trusted),
                "diags": d,
            }
            out.append(seen[name])
    return out, diags


def find_skill(workspace: Path, name: str) -> dict | None:
    """Tìm skill theo tên (đã qua precedence) — dùng cho /<tên> expand."""
    skills, _ = list_skills(workspace)
    for s in skills:
        if s["name"] == name:
            return s
    return None


def validate_skill_text(text: str, name: str) -> list[str]:
    """Validate nhanh nội dung SKILL.md — dùng khi /skills add / /skills new."""
    _, diags = _parse_skill(text, name, "standard")
    return diags


def skills_block(workspace: Path) -> str:
    """Tầng 1 catalog chèn system prompt — chỉ name + description (+ gợi ý tài nguyên)."""
    skills, _ = list_skills(workspace)
    skills = [s for s in skills if s["model_invocable"] and s.get("trusted", True)]
    if not skills:
        return ""
    lines = [
        "=== SKILLS — quy trình chuyên môn sẵn có (chuẩn Agent Skills) ===",
        "Khi nhiệm vụ người dùng khớp mô tả một skill bên dưới, hãy DÙNG tool read_file "
        "đọc SKILL.md của skill đó NGAY và làm theo từng bước trong đó.",
        "Path tương đối trong skill (scripts/, references/, assets/) giải theo THƯ MỤC CỦA SKILL "
        "(thư mục cha của SKILL.md) — chạy script bằng tool shell với đường dẫn đó; "
        "script chỉ cần đọc output, không cần đọc code.",
    ]
    for s in skills:
        extra = []
        if s["scripts"]:
            extra.append("kèm scripts/")
        if s["references"]:
            extra.append("kèm references/")
        if s["assets"]:
            extra.append("kèm assets/")
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"- /{s['name']} — {s['description'][:MAX_DESC_CATALOG]}{suffix}")
        lines.append(f"  (đọc: {s['path']})")
        if extra:
            lines.append(f"  (thư mục gốc skill: {s['base_dir']})")
    return "\n".join(lines) + "\n"
