"""Checkpoints — git-based snapshots for undo, isolated from any user repo.

Snapshots live in their own GIT_DIR (data/.ckpt-<sid>.git) with the session
workspace as the work tree, so we NEVER touch a real project's .git.
undo = reset worktree to the parent of the latest checkpoint.
"""
import asyncio
import shutil
import time

from . import config

GIT = shutil.which("git")
EXCLUDES = ["node_modules", ".venv", "venv", "__pycache__", "dist", "build",
            "target", ".next", ".cache", ".ckpt-*"]
MAX_DIFF_LOG = 40


def available() -> bool:
    return GIT is not None


def key_for(workspace) -> str:
    """Khóa checkpoint ổn định cho 1 workspace (dùng chung tools/TUI/server)."""
    import hashlib
    return hashlib.md5(str(workspace).encode(), usedforsecurity=False).hexdigest()[:12]


def _repo_dir(sid: str):
    return config.WORKSPACES_DIR / f".ckpt-{sid}.git"


def _git_args(sid: str, workspace) -> list[str]:
    return ["--git-dir", str(_repo_dir(sid)), "--work-tree", str(workspace)]


async def _run(args: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        GIT, *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode, out.decode("utf-8", "replace").strip()


def _env_clean() -> dict:
    # tránh GIT_DIR/GIT_WORK_TREE rò rỉ từ môi trường
    return {"GIT_DIR": "", "GIT_WORK_TREE": "", "HOME": __import__("os").environ.get("HOME", "")}


async def snapshot(sid: str, workspace, label: str) -> str | None:
    """Commit current worktree state. Returns checkpoint id or None (disabled/failed)."""
    if not available() or not config.load_config().get("checkpoints_enabled", True):
        return None
    repo = str(_repo_dir(sid))
    base = _git_args(sid, workspace)
    from os import environ
    env = {**environ, "GIT_DIR": repo, "GIT_WORK_TREE": str(workspace)}

    async def run(*args: str) -> tuple[int, str]:
        return await _run_with_env(base + list(args), env)

    # init once
    rc, _ = await run("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        _repo_dir(sid).parent.mkdir(parents=True, exist_ok=True)  # git init không tạo cha
        await run("init", "-q")
        await run("config", "user.email", "forge@local")
        await run("config", "user.name", "forge-checkpoint")

    pathspec = ["--", "."] + [f":(exclude){e}" for e in EXCLUDES]
    rc, _ = await run("add", "-A", *pathspec)
    if rc != 0:  # old git without exclude pathspec support
        await run("add", "-A")

    rc, tree = await run("write-tree")
    if rc != 0:
        return None
    rc, parent = await run("rev-parse", "refs/heads/forge")
    if rc == 0:
        rc, commit = await run("commit-tree", tree, "-p", parent.strip(),
                               "-m", f"ckpt: {label} · {time.strftime('%H:%M:%S')}")
    else:
        rc, commit = await run("commit-tree", tree,
                               "-m", f"ckpt (initial): {label} · {time.strftime('%H:%M:%S')}")
    if rc != 0:
        return None
    await run("update-ref", "refs/heads/forge", commit.strip())
    return commit.strip()[:10]


async def _run_with_env(args: list[str], env: dict) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        GIT, *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode, out.decode("utf-8", "replace").strip()


async def undo(sid: str, workspace) -> dict:
    """Revert worktree to the previous checkpoint. Returns {"ok", "message"}."""
    if not available():
        return {"ok": False, "message": "git không có trên máy — checkpoint không khả dụng"}
    repo = str(_repo_dir(sid))
    base = _git_args(sid, workspace)
    from os import environ
    env = {**environ, "GIT_DIR": repo, "GIT_WORK_TREE": str(workspace)}

    rc, cur = await _run_with_env(base + ["rev-parse", "refs/heads/forge"], env)
    if rc != 0:
        return {"ok": False, "message": "Chưa có checkpoint nào để undo"}
    cur = cur.strip()
    rc, parent = await _run_with_env(base + ["rev-parse", cur + "^"], env)
    if rc != 0:
        return {"ok": False, "message": "Đang ở checkpoint đầu tiên — không còn gì để undo"}

    await _run_with_env(base + ["read-tree", parent.strip()], env)
    await _run_with_env(base + ["checkout-index", "-af"], env)
    await _run_with_env(base + ["clean", "-fdq"], env)
    await _run_with_env(base + ["update-ref", "refs/heads/forge", parent.strip()], env)
    return {"ok": True, "message": f"Đã hoàn tác về checkpoint trước ({parent.strip()[:10]})"}


async def list_checkpoints(sid: str, workspace) -> list[str]:
    if not available():
        return []
    rc, out = await _run_with_env(
        _git_args(sid, workspace) + ["log", "--oneline", f"-n{MAX_DIFF_LOG}", "refs/heads/forge"],
        {**__import__("os").environ, "GIT_DIR": str(_repo_dir(sid)),
         "GIT_WORK_TREE": str(workspace)})
    return out.splitlines() if rc == 0 else []
