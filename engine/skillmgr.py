"""Skill manager — /skills list · add <git-url|đường-dẫn> · new <tên> · remove <tên>.

- add: git clone --depth 1 (hoặc copy thư mục local) → tìm các <tên>/SKILL.md
  (hỗ trợ cả repo kiểu anthropics/skills với skills/<tên>/SKILL.md) → validate
  (bắt buộc name+description) → cài vào ~/.forge/skills/<tên>/ (user scope, đè bản cũ).
  Luôn in cảnh báo trust: skill ngoài là hướng dẫn cho LLM — đọc trước khi tin.
- Trả chuỗi tiếng Việt sẵn sàng in/hiển thị (CLI, TUI, web dùng chung).
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .skills import validate_skill_text as validate_skill_path


def _copy_skill(src_dir: Path, dest_root: Path, name: str) -> str | None:
    """Copy 1 thư mục skill vào dest_root/<tên>/; trả lỗi nếu không hợp lệ."""
    skill_md = src_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"{name}: không đọc được SKILL.md ({e})"
    diags = validate_skill_path(text, name)
    fatal = [d for d in diags if "BỎ" in d or "không đọc được" in d]
    if fatal:
        return f"{name}: bị từ chối — {'; '.join(fatal)}"
    dest = dest_root / name
    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src_dir, dest)
    except (OSError, shutil.Error) as e:
        return f"{name}: không copy được ({e})"
    note = f" (⚠ {'; '.join(diags)})" if diags else ""
    return f"✅ {name}{note}"


def _find_skill_dirs(root: Path) -> list[Path]:
    """Tìm mọi thư mục chứa SKILL.md: root/, root/<tên>/, root/skills/<tên>/ (repo kiểu anthropics/skills)."""
    out: list[Path] = []
    if (root / "SKILL.md").is_file():
        out.append(root)
    for marker in (root, root / "skills"):
        if marker.is_dir():
            try:
                out.extend(p.parent for p in sorted(marker.glob("*/SKILL.md")) if p.is_file())
            except OSError:
                pass
    # khử trùng lặp, giữ thứ tự
    seen: set[Path] = set()
    uniq = []
    for d in out:
        rp = d.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(d)
    return uniq


def add(workspace: Path, src: str) -> str:
    """Cài skill từ URL git, 'owner/repo' (GitHub), hoặc thư mục local vào ~/.forge/skills/."""
    src = (src or "").strip().strip('"')
    if not src:
        return "Dùng: /skills add <git-url | owner/repo | đường-dẫn-thư-mục>"
    dest_root = Path.home() / ".forge" / "skills"
    p = Path(src).expanduser()

    def _install_from(root: Path, label: str) -> str:
        dirs = _find_skill_dirs(root)
        if not dirs:
            return f"❌ Trong {label} không thấy SKILL.md nào (cần <tên>/SKILL.md)."
        results = [x for d in dirs if (x := _copy_skill(d, dest_root, d.name))]
        ok = sum(1 for r in results if r.startswith("✅"))
        return (f"📦 Đã cài {ok}/{len(results)} skill từ {label} → {dest_root}\n  "
                + "\n  ".join(results)
                + "\n⚠ Skill ngoài là hướng dẫn cho LLM — mở SKILL.md đọc trước khi tin.")

    tmp = None
    try:
        if p.is_dir():
            return _install_from(p, src)
        if re.match(r"^https?://", src) or src.startswith("git@") or src.endswith(".git"):
            url = src
        elif re.match(r"^[\w.-]+/[\w.-]+$", src):
            url = f"https://github.com/{src}"
        else:
            return (f"❌ Không hiểu nguồn '{src}' — dùng URL git, 'owner/repo', "
                    "hoặc đường dẫn thư mục chứa <tên>/SKILL.md.")
        tmp = Path(tempfile.mkdtemp(prefix="forge-skill-"))
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", url, str(tmp / "repo")],
            capture_output=True, text=True, timeout=90, check=False,
        )
        if r.returncode != 0:
            err = (r.stderr or "").strip().splitlines()
            return (f"❌ Không clone được {url}"
                    + (f"\n   {err[-1]}" if err else "")
                    + "\n   (cần git trong PATH; kiểm tra URL / mạng)")
        return _install_from(tmp / "repo", url)
    except subprocess.TimeoutExpired:
        return f"❌ Clone quá chậm (timeout 90s): {src}"
    except FileNotFoundError:
        return "❌ Không tìm thấy lệnh git trong PATH — cài Git hoặc dùng thư mục local."
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


_TEMPLATE = """---
name: {name}
description: >-
  {desc}
---

# {name}

## Mục đích
(Mô tả ngắn skill này làm gì và KHI NÀO nên dùng — phần description phía trên là "trigger",
phải nói cả "làm gì" lẫn "khi nào dùng".)

## Các bước
1. (Bước 1)
2. (Bước 2)
3. (Kiểm tra kết quả)

## Gotchas
- (Bẫy thường gặp, điều KHÔNG nên làm)

## Tài nguyên
- (Nếu cần: tạo thư mục scripts/ cho script chạy được — không tương tác, có --help;
  references/ cho tài liệu tham khảo đọc khi cần.)
"""


def new_skill(workspace: Path, name: str, desc: str = "") -> str:
    """Scaffold skill mới đúng chuẩn vào <workspace>/.forge/skills/<tên>/SKILL.md."""
    name = (name or "").strip().strip("/")
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name) or len(name) > 64:
        return (f"❌ Tên '{name}' phải kebab-case [a-z0-9-], ≤64 ký tự (vd: commit-vn, "
                "review-api) — chuẩn Agent Skills.")
    dest = Path(workspace) / ".forge" / "skills" / name
    skill_md = dest / "SKILL.md"
    if skill_md.exists():
        return f"❌ Đã có {skill_md} — dùng tên khác hoặc xoá trước."
    desc = desc or f"Làm {name.replace('-', ' ')} theo quy trình chuẩn của dự án. Dùng khi nhiệm vụ người dùng khớp."
    try:
        dest.mkdir(parents=True, exist_ok=True)
        skill_md.write_text(_TEMPLATE.format(name=name, desc=desc), encoding="utf-8")
    except OSError as e:
        return f"❌ Không ghi được: {e}"
    diags = validate_skill_path(skill_md.read_text(encoding="utf-8"), name)
    warn = f"\n⚠ {'; '.join(diags)}" if diags else ""
    return (f"✅ Đã tạo {skill_md}{warn}\n"
            f"   Mở file điền các bước rồi dùng ngay: /{name} — hoặc bảo agent "
            f"\"đọc .forge/skills/{name}/SKILL.md và hoàn thiện nó\".")


def trust(workspace: Path, arg: str) -> str:
    """Quản trị trust cho skill PROJECT: /skills trust (liệt kê) · trust <tên> · trust all.

    Skill project chưa tin KHÔNG nạp vào catalog model (chống prompt injection
    từ repo lạ — khuyến nghị của chuẩn agentskills.io).
    """
    from .skills import list_skills, save_trusted
    arg = (arg or "").strip()
    skills, _ = list_skills(workspace)
    untrusted = [s for s in skills if s["source"] == "project" and not s.get("trusted", True)]
    if not arg:
        if not untrusted:
            return ("✅ Mọi skill project đều đã được tin — không có gì cần chấp nhận.\n"
                    "(Skill user/built-in luôn được tin sẵn.)")
        lines = [f"🔒 {len(untrusted)} skill project CHƯA được tin (không nạp vào model):"]
        for s_ in untrusted:
            lines.append(f"  - {s_['name']} — {s_['description'][:80]}")
            lines.append(f"    {s_['path']}")
        lines.append("Chấp nhận 1 skill:  /skills trust <tên>   ·   Chấp nhận tất cả:  /skills trust all")
        return "\n".join(lines)
    if arg == "all":
        if not untrusted:
            return "Không có skill nào cần chấp nhận."
        save_trusted(workspace, {s_["name"] for s_ in untrusted})
        return (f"✅ Đã tin {len(untrusted)} skill: "
                + ", ".join(s_["name"] for s_ in untrusted)
                + "\n(Catalog model nạp từ lượt chat kế tiếp.)")
    target = next((s_ for s_ in untrusted if s_["name"] == arg), None)
    if target is None:
        return (f"❌ Không có skill project CHƯA tin tên '{arg}'. "
                "Xem danh sách: /skills (dòng có 🔒)")
    save_trusted(workspace, {arg})
    return (f"✅ Đã tin skill '{arg}' — model nạp từ lượt chat kế tiếp.\n"
            f"   {target['path']}")


def remove(workspace: Path, name: str) -> str:
    """Gỡ skill khỏi USER scope (~/.forge/skills) — skill project thì tự xoá file trong repo."""
    name = (name or "").strip().strip("/")
    dest = Path.home() / ".forge" / "skills" / name
    if not dest.exists():
        return (f"❌ Không thấy '{name}' trong {dest} — skill project-level nằm trong repo "
                f"(xóa thủ công), remove chỉ gỡ skill đã cài ở user scope.")
    try:
        shutil.rmtree(dest)
    except OSError as e:
        return f"❌ Không xoá được: {e}"
    return f"🗑 Đã gỡ '{name}' khỏi {dest}"


def format_listing(workspace: Path) -> str:
    """Chuỗi liệt kê skills cho /skills — nhóm theo nguồn, kèm diagnostics."""
    from .skills import list_skills
    skills, diags = list_skills(workspace)
    if not skills and not diags:
        return ("(chưa có skill nào)\n"
                "Tạo nhanh:  /skills new <tên>  ·  Cài từ ngoài:  /skills add <git-url|thư-mục>\n"
                "Vị trí quét: .forge/skills · .agents/skills · .claude/skills (project) · ~/.forge/skills (user)")
    LABELS = {
        "project": "📁 Project",
        "user": "🏠 User (~/.forge/skills)",
        "global-legacy": "🗄 Global cũ (data/forge/skills)",
        "built-in": "🧷 Built-in (đi kèm app)",
    }
    blocks: list[str] = []
    by_src: dict[str, list[dict]] = {}
    for s in skills:
        by_src.setdefault(s["source"], []).append(s)
    total = 0
    for src in ("project", "user", "global-legacy", "built-in"):
        rows = by_src.get(src, [])
        if not rows:
            continue
        lines = [f"### {LABELS[src]}"]
        for s in rows:
            total += 1
            icon = "📦" if s["fmt"] == "standard" else "📄"
            if src == "project" and not s.get("trusted", True):
                icon = "🔒"
            inv = "" if s["model_invocable"] else " · 🔕 chỉ gọi tay"
            at = (s.get("allowed_tools") or "").strip()
            at_s = f" · 🔑 {at[:60]}" if at else ""
            res = []
            for k in ("scripts", "references", "assets"):
                if s[k]:
                    res.append(k + "/")
            res_s = f" · {' '.join(res)}" if res else ""
            warn = f" · ⚠ {'; '.join(s['diags'])}" if s["diags"] else ""
            desc = s["description"][:100] + ("…" if len(s["description"]) > 100 else "")
            lines.append(f"- {icon} **{s['name']}**{inv}{at_s}{res_s} — {desc}{warn}")
            lines.append(f"  `{s['path']}`")
        blocks.append("\n".join(lines))
    n_lock = sum(1 for s in skills if s["source"] == "project" and not s.get("trusted", True))
    head = f"### 🧩 Skills ({total})\n" if total else "### 🧩 Skills\n"
    if n_lock:
        head += f"\n⚠ {n_lock} skill project có 🔒 chưa được tin — KHÔNG nạp vào model. Xem: /skills trust\n"
    tail = ""
    if diags:
        tail = "\n### ⚠ Chẩn đoán\n" + "\n".join(f"- {d}" for d in diags[:15])
        if len(diags) > 15:
            tail += f"\n- … và {len(diags) - 15} cảnh báo nữa"
    return (head + "\n\n".join(blocks) + tail
            + "\n\nLệnh: `/skills add <git-url|thư-mục>` · `/skills new <tên> [mô tả]` · "
              "`/skills trust [all|<tên>]` · `/skills remove <tên>`")


def set_model_invocable(workspace: Path, skill_path: str, invocable: bool) -> str:
    """Bật/tắt model-invocation cho 1 skill bằng cách sửa frontmatter SKILL.md.

    - Tắt: đặt `disable-model-invocation: true` (sửa nếu đã có, thêm nếu thiếu;
      file không có frontmatter → tạo frontmatter tối thiểu).
    - Bật: xoá/mở dòng disable-model-invocation.
    Trả chuỗi thông báo thân thiện (không raise với lỗi I/O thông thường).
    """
    from .skills import list_skills
    f = Path(skill_path)
    try:
        skills, _ = list_skills(workspace)
        match = [x for x in skills if str(x.get("path")) == str(f)]
        if not match:
            return f"❌ Không thấy skill tại {skill_path} (không nằm trong vị trí quét?)"
        name = match[0]["name"]
        try:
            lines = f.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError as e:
            return f"❌ Không đọc được file: {e}"
        if lines and lines[0].strip() == "---":
            end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
        else:
            end = None
        if end is None:
            if invocable:
                return f"ℹ️ '{name}' đã ở trạng thái bật."
            lines = ["---\n", f"name: {name}\n",
                     "description: (skill legacy — quản lý qua tab Skills)\n",
                     "disable-model-invocation: true\n", "---\n"] + lines
        else:
            idx = next((i for i in range(1, end)
                        if lines[i].strip().lower().startswith("disable-model-invocation")), None)
            if invocable:
                if idx is None:
                    return f"ℹ️ '{name}' đã ở trạng thái bật."
                del lines[idx]
            elif idx is not None:
                lines[idx] = "disable-model-invocation: true\n"
            else:
                lines.insert(1, "disable-model-invocation: true\n")
        try:
            f.write_text("".join(lines), encoding="utf-8")
        except OSError as e:
            return f"❌ Không ghi được file: {e}"
        return (f"🔕 '{name}' — chỉ gọi tay (model không tự dùng)." if not invocable
                else f"✅ '{name}' — model tự dùng được bình thường.")
    except Exception as e:  # noqa: BLE001 — quản trị skill không được làm sập chat
        return f"❌ Lỗi: {e}"
