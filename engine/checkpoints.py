"""Checkpoints — git-based snapshots for undo, isolated from any user repo.

Snapshots live in their own GIT_DIR (data/.ckpt-<sid>.git) with the session
workspace as the work tree, so we NEVER touch a real project's .git.
undo = restore the latest pre-operation snapshot, then pop its reference.
"""
import asyncio
import fnmatch
import logging
import re
import shutil
import time
from pathlib import Path

from . import config
from .secrets import sanitized_env
from .session import _valid_session_id

GIT = shutil.which("git")
EXCLUDES = ["node_modules", ".venv", "venv", "__pycache__", "dist", "build",
            "target", ".next", ".cache", ".ckpt-*"]
MAX_DIFF_LOG = 40
MAX_GIT_OUTPUT = 64_000  # default retained stdout+stderr bytes per invocation
MAX_GIT_TREE_OUTPUT = 4_000_000  # undo preflight only; larger trees fail closed
GIT_COMMAND_TIMEOUT = 60
GIT_CLEANUP_TIMEOUT = 2
GIT_CLEANUP_SHUTDOWN_WAIT = 5.0
_GIT_CLEANUPS: set[asyncio.Task] = set()


async def wait_git_cleanups() -> int:
    """Wait briefly for the current snapshot of tracked cleanups without cancelling them."""
    pending = set(_GIT_CLEANUPS)
    if not pending:
        return 0
    _, pending = await asyncio.wait(pending, timeout=GIT_CLEANUP_SHUTDOWN_WAIT)
    return len(pending)


def available() -> bool:
    return GIT is not None


def key_for(workspace) -> str:
    """Khóa checkpoint ổn định cho 1 workspace (dùng chung tools/TUI/server)."""
    import hashlib
    return hashlib.md5(str(workspace).encode(), usedforsecurity=False).hexdigest()[:12]


def _repo_dir(sid: str):
    if not _valid_session_id(sid):
        raise ValueError('Invalid checkpoint repository key')
    return config.WORKSPACES_DIR / f".ckpt-{sid}.git"


# Git applies content conversions (core.autocrlf, .gitattributes eol/text/filter/ident,
# working-tree-encoding, export-ignore/export-subst) on add, checkout and archive. A snapshot
# must be byte-exact, so the checkpoint repository switches every one of them off. The
# repository's own info/attributes has the highest precedence: it overrides the workspace's
# .gitattributes and the user's and system's attribute files.
EXACT_ATTRIBUTES = "* -text -filter -ident -working-tree-encoding -export-ignore -export-subst\n"


LEGACY_PENDING = "forge-legacy-pending"   # written when the attributes were added to a repository
LEGACY_HEAD = "forge-legacy-head"         # newest snapshot stored before that, i.e. possibly converted
LEGACY_NOTE = ("Lưu ý: checkpoint này được tạo trước khi checkpoint lưu byte-exact, nên Git có thể "
               "đã đổi line ending (CRLF→LF) của một số file khi lưu; đã khôi phục đúng như đã lưu.")


def ensure_exact_attributes(repo, *, new: bool = False) -> bool:
    """Make sure ``<repo>/info/attributes`` disables conversions; False if it cannot be written.

    Checked on every use, so repositories created before this rule are fixed as well. When the
    line has to be written into a repository that already exists, two more things follow:

    * the file index is removed, because Git trusts it for files whose timestamps did not change
      and would not read them again, so the next snapshot would keep their converted content;
    * a marker is left so the next snapshot or undo can record which snapshots were stored before
      the rule (see :func:`_settle_legacy`); those are restored as stored, with a note.

    The line is written last: if the index cannot be removed, the line is still missing and the
    next call starts over, instead of leaving a repository that looks repaired and is not.
    ``new=True`` says the repository has no snapshot yet, so neither the removal nor the marker.

    A repository directory that does not exist is left alone: there is nothing to convert, and
    the Git command that follows fails on its own.
    """
    try:
        # Never create a repository directory (or a stray tree in the cwd) just for this file.
        if not Path(repo).is_dir():
            return True
        target = Path(repo) / "info" / "attributes"
        try:
            if target.read_text(encoding="utf-8") == EXACT_ATTRIBUTES:
                return True
        except FileNotFoundError:
            pass
        target.parent.mkdir(parents=True, exist_ok=True)
        if not new:
            (Path(repo) / LEGACY_PENDING).write_bytes(b"")
            (Path(repo) / "index").unlink(missing_ok=True)
        target.write_text(EXACT_ATTRIBUTES, encoding="utf-8", newline="\n")
        return True
    except (OSError, UnicodeError):
        return False


_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


async def _settle_legacy(repo, git) -> bool:
    """Record the snapshots that exist when the rule is first applied; False if that failed.

    ``git(*args)`` runs a Git command on the checkpoint repository and returns ``(rc, output)``.
    Everything up to and including the head at that moment was stored under the user's Git
    configuration and may be converted. Runs before any new snapshot, so the head is that state.
    """
    pending = Path(repo) / LEGACY_PENDING
    try:
        if not pending.exists():
            return True
        rc, _ = await git("show-ref", "--verify", "--quiet", "refs/heads/forge")
        if rc == 0:
            rc, head = await git("rev-parse", "refs/heads/forge")
            head = head.strip()
            if rc != 0 or not _OID.fullmatch(head):
                return False
            (Path(repo) / LEGACY_HEAD).write_text(head, encoding="ascii")
        elif rc != 1:
            return False
        pending.unlink(missing_ok=True)
        return True
    except (OSError, UnicodeError):
        return False


async def _is_legacy(repo, git, oid: str) -> bool:
    """True when snapshot ``oid`` was stored before the rule and may be converted."""
    try:
        head = (Path(repo) / LEGACY_HEAD).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return False
    if not _OID.fullmatch(head):
        return False
    rc, _ = await git("merge-base", "--is-ancestor", oid, head)
    return rc == 0


def _git_args(sid: str, workspace) -> list[str]:
    return ["--git-dir", str(_repo_dir(sid)), "--work-tree", str(workspace)]


async def _drain_git_output(proc, max_output: int | None = None) -> tuple[bytes, bool]:
    """Drain output even beyond the retention cap, then wait for the child."""
    limit = MAX_GIT_OUTPUT if max_output is None else max_output
    retained = bytearray()
    truncated = False
    assert proc.stdout is not None
    while True:
        chunk = await proc.stdout.read(16_384)
        if not chunk:
            break
        available = max(0, limit - len(retained))
        retained.extend(chunk[:available])
        if len(chunk) > available:
            truncated = True
    await proc.wait()
    return bytes(retained), truncated


async def _cleanup_git_process(proc, communication: asyncio.Task) -> None:
    """Best-effort kill and reap of a Git process whose creation completed."""
    try:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        done, _ = await asyncio.wait({communication}, timeout=GIT_CLEANUP_TIMEOUT)
        if not done:
            logging.getLogger(__name__).warning("Checkpoint Git cleanup timed out")
            communication.cancel()
            # Do not let an inherited pipe held by another process block cleanup.
        else:
            try:
                communication.result()
            except Exception:
                logging.getLogger(__name__).exception("Checkpoint Git communication failed during cleanup")
    except Exception:
        logging.getLogger(__name__).exception("Checkpoint Git cleanup failed")
        communication.cancel()


def _track_git_cleanup(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _GIT_CLEANUPS.add(task)
    task.add_done_callback(_GIT_CLEANUPS.discard)
    return task


def _start_git_cleanup(proc, communication: asyncio.Task) -> asyncio.Task:
    return _track_git_cleanup(_cleanup_git_process(proc, communication))


async def _cleanup_late_git_spawn(spawn: asyncio.Task) -> None:
    """Own a cancelled caller's in-flight spawn until it resolves."""
    try:
        proc = await spawn
    except asyncio.CancelledError:
        logging.getLogger(__name__).warning("Late checkpoint Git spawn cleanup was cancelled")
        raise
    except Exception:
        logging.getLogger(__name__).exception("Late checkpoint Git spawn failed")
        return
    communication = asyncio.create_task(_drain_git_output(proc))
    await _cleanup_git_process(proc, communication)


async def _run_with_env(args: list[str], env: dict, *, on_detached_cleanup=None,
                        max_output: int | None = None, executable: str | None = None,
                        timeout: float | None = None) -> tuple[int, str]:
    git = GIT if executable is None else executable
    if git is None:
        return 127, "git không có"
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        git, *args, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, env=env,
    ))
    try:
        proc = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        cleanup = _track_git_cleanup(_cleanup_late_git_spawn(spawn))
        if on_detached_cleanup is not None:
            on_detached_cleanup(cleanup)
        raise
    communication = asyncio.create_task(_drain_git_output(proc, max_output))
    try:
        done, _ = await asyncio.wait({communication}, timeout=GIT_COMMAND_TIMEOUT if timeout is None else timeout)
    except asyncio.CancelledError:
        cleanup = _start_git_cleanup(proc, communication)
        # A second cancellation can interrupt this wait, not the cleanup task.
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            if on_detached_cleanup is not None:
                on_detached_cleanup(cleanup)
            raise
        raise
    if not done:
        cleanup = _start_git_cleanup(proc, communication)
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            if on_detached_cleanup is not None:
                on_detached_cleanup(cleanup)
            raise
        return 124, "timeout"
    try:
        out, truncated = communication.result()
    except Exception:
        cleanup = _start_git_cleanup(proc, communication)
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            if on_detached_cleanup is not None:
                on_detached_cleanup(cleanup)
            raise
        raise
    if truncated:
        # Never interpret truncated output as a tree/ref/commit or missing ref.
        return 125, "checkpoint Git output exceeded limit"
    return proc.returncode or 0, out.decode("utf-8", "replace").strip()


async def _run(args: list[str]) -> tuple[int, str]:
    return await _run_with_env(args, sanitized_env())


async def snapshot(sid: str, workspace, label: str, *, on_detached_cleanup=None,
                   outcome: dict | None = None) -> str | None:
    """Return checkpoint id or None; optionally report why no snapshot was created."""
    if outcome is not None:
        outcome["status"] = "failed"
    if not _valid_session_id(sid):
        return None
    if not available():
        if outcome is not None:
            outcome["status"] = "unavailable"
        return None
    if not config.load_config().get("checkpoints_enabled", True):
        if outcome is not None:
            outcome["status"] = "disabled"
        return None
    repo = str(_repo_dir(sid))
    base = _git_args(sid, workspace)
    env = sanitized_env({"GIT_DIR": repo, "GIT_WORK_TREE": str(workspace)})

    async def run(*args: str) -> tuple[int, str]:
        try:
            if on_detached_cleanup is None:
                return await _run_with_env(base + list(args), env)
            return await _run_with_env(base + list(args), env, on_detached_cleanup=on_detached_cleanup)
        except Exception as exc:
            logging.getLogger(__name__).warning("Checkpoint Git %s execution failed (%s)",
                                                args[0], type(exc).__name__)
            return 125, ""

    # Do not reinitialize an existing repository when its probe fails. A failed
    # or timed-out probe is not proof that an existing repository is absent.
    rc, _ = await run("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        if rc in (124, 125) or Path(repo).exists():
            return None
        _repo_dir(sid).parent.mkdir(parents=True, exist_ok=True)
        for step in (("init", "-q"), ("config", "user.email", "forge@local"),
                     ("config", "user.name", "forge-checkpoint")):
            rc, _ = await run(*step)
            if rc != 0:
                return None
    # Fail closed: a snapshot taken with conversions active cannot be restored byte-exact.
    if not ensure_exact_attributes(repo) or not await _settle_legacy(repo, run):
        return None

    pathspec = ["--", "."] + [f":(exclude){e}" for e in EXCLUDES]
    rc, _ = await run("add", "-A", *pathspec)
    if rc != 0:
        # An unrestricted retry would silently stage excluded paths on any
        # failure, including timeout or permissions errors. Fail closed instead.
        return None

    rc, tree = await run("write-tree")
    if rc != 0 or not tree.strip():
        return None
    rc, _ = await run("show-ref", "--verify", "--quiet", "refs/heads/forge")
    if rc == 0:
        rc, parent = await run("rev-parse", "refs/heads/forge")
        if rc != 0 or not parent.strip():
            return None
        parent = parent.strip()
        rc, commit = await run("commit-tree", tree, "-p", parent,
                               "-m", f"ckpt: {label} · {time.strftime('%H:%M:%S')}")
    elif rc == 1:
        parent = ""
        rc, commit = await run("commit-tree", tree,
                               "-m", f"ckpt (initial): {label} · {time.strftime('%H:%M:%S')}")
    else:
        return None
    if rc != 0 or not commit.strip():
        return None
    # Compare-and-swap avoids overwriting a ref that changed since the read;
    # the empty expected old value requires that the ref still does not exist.
    rc, _ = await run("update-ref", "refs/heads/forge", commit.strip(), parent)
    if rc != 0:
        return None
    if outcome is not None:
        outcome["status"] = "created"
    return commit.strip()[:10]


async def undo(sid: str, workspace) -> dict:
    """Restore the newest pre-operation snapshot and pop it from the undo stack."""
    if not _valid_session_id(sid):
        return {"ok": False, "message": "Invalid checkpoint repository key"}
    if not available():
        return {"ok": False, "message": "git không có trên máy — checkpoint không khả dụng"}
    repo = str(_repo_dir(sid))
    base = _git_args(sid, workspace)
    env = sanitized_env({"GIT_DIR": repo, "GIT_WORK_TREE": str(workspace)})

    rc, cur = await _run_with_env(base + ["rev-parse", "refs/heads/forge"], env)
    if rc != 0:
        return {"ok": False, "message": "Chưa có checkpoint nào để undo"}
    async def git(*args: str) -> tuple[int, str]:
        try:
            return await _run_with_env(base + list(args), env)
        except Exception:
            return 125, ""

    if not ensure_exact_attributes(repo) or not await _settle_legacy(repo, git):
        return {"ok": False, "message": "Không thể tắt chuyển đổi nội dung của Git cho checkpoint; undo chưa được thực hiện."}
    cur = cur.strip()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", cur):
        return {"ok": False, "message": "Không thể xác nhận checkpoint hiện tại; undo chưa được thực hiện."}
    try:
        rc, ancestry = await _run_with_env(base + ["rev-list", "--parents", "-n", "1", cur], env)
    except Exception:
        rc, ancestry = 125, ""
    ids = ancestry.split()
    # Forge snapshots form a linear chain. A root commit has no parent; reject
    # errors, malformed output and merge commits rather than guessing a stack.
    if (rc != 0 or len(ids) not in (1, 2) or ids[0] != cur or
        any(len(oid) != len(cur) or not re.fullmatch(r"[0-9a-f]+", oid) for oid in ids)):
        return {"ok": False, "message": "Không thể xác nhận lịch sử checkpoint; undo chưa được thực hiện."}
    parent = ids[1] if len(ids) == 2 else None

    # Older checkpoints may already track files in currently excluded paths.
    # Inspect the immutable target tree before touching the index or worktree;
    # fail closed on errors or incomplete output rather than risk overwriting.
    try:
        rc, listing = await _run_with_env(base + ["ls-tree", "-r", "-z", cur], env,
                                          max_output=MAX_GIT_TREE_OUTPUT)
    except Exception:
        rc, listing = 125, ""
    unsafe = {"ok": False, "message": "Không thể kiểm tra an toàn checkpoint đích; undo chưa được thực hiện."}
    if rc != 0 or (listing and not listing.endswith("\0")):
        return unsafe
    patterns = [pattern.casefold() for pattern in EXCLUDES]
    for record in listing.split("\0")[:-1]:
        meta, sep, path = record.partition("\t")
        # stdout and stderr share a pipe; reject unexpected text instead of
        # accidentally treating a Git warning as part of a safe filename.
        if not sep or not path or not re.fullmatch(
            r"(?:(?:100644|100755|120000) blob|160000 commit) (?:[0-9a-f]{40}|[0-9a-f]{64})", meta
        ):
            return unsafe
        if any(fnmatch.fnmatchcase(part.casefold(), pattern)
               for part in path.split("/") for pattern in patterns):
            return {"ok": False, "message": ("Checkpoint đích theo dõi đường dẫn thuộc diện loại trừ; "
                                             "undo chưa được thực hiện để tránh ghi đè dữ liệu.")}

    legacy = await _is_legacy(repo, git, cur)

    # These steps are not transactional: stop on the first failure and do not
    # claim success, since earlier steps may already have changed the workspace.
    steps = [
        ["read-tree", cur],
        ["checkout-index", "-af"],
        # Snapshot excludes these paths, so undo cannot restore them. Never let
        # clean remove their untracked contents, even without a .gitignore.
        ["clean", "-fdq"] + [arg for pattern in EXCLUDES for arg in ("-e", pattern)],
        # Atomically pop the snapshot only if the ref still has its old value.
        (["update-ref", "refs/heads/forge", parent, cur] if parent else
         ["update-ref", "-d", "refs/heads/forge", cur]),
    ]
    for step in steps:
        try:
            rc, _ = await _run_with_env(base + step, env)
        except Exception:
            rc = None  # Do not expose subprocess/OS exception details to callers.
        if rc != 0:
            status = f"mã {rc}" if rc is not None else "lỗi thực thi"
            return {"ok": False, "message": (f"Undo thất bại tại bước git {step[0]} ({status}). "
                                              "Workspace hoặc checkpoint có thể đã thay đổi một phần; "
                                              "hãy kiểm tra trước khi tiếp tục.")}
    message = f"Đã hoàn tác về checkpoint ({cur[:10]})"
    if legacy:
        message += ". " + LEGACY_NOTE
    return {"ok": True, "message": message}


async def list_checkpoints(sid: str, workspace) -> list[str]:
    if not _valid_session_id(sid) or not available():
        return []
    rc, out = await _run_with_env(
        _git_args(sid, workspace) + ["log", "--oneline", f"-n{MAX_DIFF_LOG}", "refs/heads/forge"],
        sanitized_env({"GIT_DIR": str(_repo_dir(sid)),
                       "GIT_WORK_TREE": str(workspace)}))
    return out.splitlines() if rc == 0 else []
