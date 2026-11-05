"""Worktree isolation (B2 — theo Claude `isolation: worktree`).

Sub-agent với isolation="worktree" làm việc trong BẢN SAO git-worktree tách ra
từ snapshot checkpoint của cha — tool/ghi/xoá của nó KHÔNG đụng workspace cha.
Sau khi xong: xem diff (`diff_stat`), gộp có chủ đích (`merge`) hoặc bỏ
(`discard`). Fork cũng tận dụng snapshot: xuất cây từ branch `forge` (nhanh,
trạng thái nhất quán) thay vì copytree lúc file đang ghi dở.

Repo dùng: repo checkpoint nội bộ của cha (`.ckpt-<sid>.git`, branch `forge`).
Không có checkpoint (git thiếu / snapshot lỗi) → trả None — caller fallback
hành vi cũ (chia sẻ/copytree). KHÔNG BAO GIỜ raise cho caller agent.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from . import config

GIT = shutil.which("git")


def wt_path(sub_sid: str):
    return config.WORKSPACES_DIR / f"wt-{sub_sid}"


def _repo(sid: str):
    return config.WORKSPACES_DIR / f".ckpt-{sid}.git"


async def _run(*args: str, timeout: float = 60) -> tuple[int, str]:
    git = GIT
    if git is None:
        return 127, "git không có"
    proc = await asyncio.create_subprocess_exec(
        git, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode or 0, out.decode("utf-8", "replace").strip()


async def available_for(sid: str) -> bool:
    repo = _repo(sid)
    if not GIT or not repo.exists():
        return False
    rc, _ = await _run("--git-dir", str(repo), "rev-parse", "refs/heads/forge")
    return rc == 0


async def make(src_sid: str, sub_sid: str) -> str | None:
    """Tạo worktree `wt-<sub_sid>` từ branch forge của cha, branch riêng iso/<sub_sid>.

    Trả về đường dẫn (str) hoặc None nếu không khả dụng.
    """
    if not await available_for(src_sid):
        return None
    repo = str(_repo(src_sid))
    path = wt_path(sub_sid)
    config.ensure_dirs()
    if path.exists():
        await _run("--git-dir", repo, "worktree", "remove", "--force", str(path))
    rc, out = await _run("--git-dir", repo, "worktree", "add", "-b",
                         f"iso/{sub_sid}", str(path), "forge")
    if rc != 0:
        print(f"[worktree] add lỗi: {out[:200]}")
        return None
    return str(path)


async def diff_stat(sub_sid: str, src_sid: str, wt=None) -> str:
    """diff --stat giữa điểm rẽ nhánh (branch iso/<sub> của repo cha) và worktree hiện tại."""
    if wt is None:
        wt = wt_path(sub_sid)
    repo = _repo(src_sid)
    if not GIT or not repo.exists() or not Path(wt).exists():
        return ""
    rc, _ = await _run("--git-dir", str(repo), "rev-parse", f"iso/{sub_sid}")
    if rc != 0:
        return ""
    env_wt = ["--git-dir", str(repo), "--work-tree", str(wt)]
    await _run(*env_wt, "add", "-A", "--", ".")  # đưa cả file mới vào index để diff thấy
    _rc, out = await _run(*env_wt, "diff", "--stat", f"iso/{sub_sid}", "--")
    return out if _rc == 0 else ""


async def merge(sub_sid: str, src_sid: str, parent_sid: str, parent_ws) -> dict:
    """Gộp thay đổi của worktree sub về workspace cha.

    Patch = diff (branch iso/<sub> → working tree của wt) trong repo checkpoint
    CỦA CHA, áp bằng `git apply` vào workspace cha. Trả {"ok", "message", "files"}.
    """
    repo = _repo(src_sid)
    wt = wt_path(sub_sid)
    if not GIT or not repo.exists() or not wt.exists():
        return {"ok": False, "message": "worktree không tồn tại (đã bỏ?)", "files": 0}
    env_wt = ["--git-dir", str(repo), "--work-tree", str(wt)]
    await _run(*env_wt, "add", "-A", "--", ".")
    # patch phải lấy bằng BYTES nguyên bản — --binary chứa NUL, đi qua decode text là hỏng
    proc = await asyncio.create_subprocess_exec(
        GIT, *env_wt, "diff", "--binary", f"iso/{sub_sid}", "--",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    raw, err = await proc.communicate()
    if proc.returncode != 0:
        return {"ok": False, "message": f"diff lỗi: {err.decode()[:150]}", "files": 0}
    if not raw.strip():
        return {"ok": True, "message": "(worktree không khác gì điểm rẽ nhánh — không có gì để gộp)",
                "files": 0}
    _rc, stat = await _run(*env_wt, "diff", "--stat", f"iso/{sub_sid}", "--")
    n_files = len([ln for ln in stat.splitlines() if "|" in ln])
    # git apply KHÔNG tôn trọng --work-tree — phải đặt CWD = workspace cha (-C)
    proc = await asyncio.create_subprocess_exec(
        GIT, "-C", str(parent_ws), "apply", "--whitespace=nowarn", "-",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate(raw)  # bytes nguyên bản
    if proc.returncode != 0:
        return {"ok": False,
                "message": f"Áp patch KHÔNG được (workspace cha đã đổi sau khi rẽ nhánh?) — {out.decode()[:200]}",
                "files": 0}
    return {"ok": True, "message": f"Đã gộp {n_files} file từ worktree về workspace cha.",
            "files": n_files}


async def discard(sub_sid: str, src_sid: str) -> dict:
    """Bỏ worktree + branch iso + repo checkpoint của sub (không đụng workspace cha)."""
    removed = []
    path = wt_path(sub_sid)
    if path.exists():
        await _run("--git-dir", str(_repo(src_sid)), "worktree", "remove", "--force",
                   str(path))
        if path.exists():
            await _run("rm", "-rf", str(path))
        removed.append(str(path))
    repo = _repo(sub_sid)
    if repo.exists():
        shutil.rmtree(repo, ignore_errors=True)
        removed.append(str(repo))
    if GIT and _repo(src_sid).exists():
        await _run("--git-dir", str(_repo(src_sid)), "branch", "-D", f"iso/{sub_sid}")
        await _run("--git-dir", str(_repo(src_sid)), "worktree", "prune")
    return {"ok": bool(removed), "removed": removed}


async def list_all() -> list[dict]:
    """Quét worktree đang tồn tại (wt-*) + dòng diff ngắn (repo cha suy từ file .git)."""
    out: list[dict] = []
    if not config.WORKSPACES_DIR.exists():
        return out
    for p in sorted(config.WORKSPACES_DIR.glob("wt-*")):
        sub_sid = p.name[3:]
        src_sid = ""
        try:
            gitfile = (p / ".git").read_text(encoding="utf-8").strip()
            # "gitdir: <...>/.ckpt-<src>.git/worktrees/<name>"
            marker = ".ckpt-"
            seg = next(x for x in gitfile.split("/") if marker in x)
            src_sid = seg[len(marker):-len(".git")]
        except Exception:  # noqa: S110, BLE001 — không parse được thì bỏ qua chi tiết
            pass
        stat = await diff_stat(sub_sid, src_sid, p) if src_sid else ""
        out.append({"session": sub_sid, "src": src_sid, "path": str(p),
                    "stat": stat.splitlines()[-1] if stat else "(không khác gì điểm rẽ nhánh)",
                    "detail": stat})
    return out


async def export_tree(src_sid: str, dst_dir) -> bool:
    """Xuất cây snapshot `forge` của src vào dst_dir (fork từ trạng thái nhất quán)."""
    if not GIT or not await available_for(src_sid):
        return False
    proc = await asyncio.create_subprocess_exec(
        GIT, "--git-dir", str(_repo(src_sid)), "archive", "forge", "--",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _err = await proc.communicate()
    if proc.returncode != 0 or not out:
        return False
    import io
    import tarfile
    dst_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(out), mode="r|") as tf:
        tf.extractall(dst_dir, filter="data")
    return True


def export_tree_sync(src_sid: str, dst_dir) -> bool:
    """Bản sync của export_tree cho SessionStore.fork() (archive cục bộ, nhanh)."""
    if not GIT or not _repo(src_sid).exists():
        return False
    import subprocess
    r = subprocess.run([GIT, "--git-dir", str(_repo(src_sid)), "archive", "forge", "--"],
                       capture_output=True, timeout=120, check=False)
    if r.returncode != 0 or not r.stdout:
        return False
    import io
    import tarfile
    dst_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r|") as tf:
        tf.extractall(dst_dir, filter="data")
    return True
