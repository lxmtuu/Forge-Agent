"""Worktree isolation (B2 — theo Claude `isolation: worktree`).

Sub-agent với isolation="worktree" làm việc trong BẢN SAO git-worktree tách ra
từ snapshot checkpoint của cha — tool/ghi/xoá của nó KHÔNG đụng workspace cha.
Sau khi xong: xem diff (`diff_stat`), gộp có chủ đích (`merge`) hoặc bỏ
(`discard`). Fork cũng tận dụng snapshot: xuất cây từ branch `forge` (nhanh,
trạng thái nhất quán) thay vì copytree lúc file đang ghi dở.

Repo dùng: repo checkpoint nội bộ của cha (`.ckpt-<sid>.git`, branch `forge`).
Không có checkpoint (git thiếu / snapshot lỗi) → trả None; sub-agent yêu cầu
worktree phải báo lỗi thay vì tự chuyển sang workspace khác.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from . import config
from .secrets import sanitized_env
from .session import _valid_session_id

GIT = shutil.which("git")
WORKTREE_PATCH_LIMIT = 8 * 1024 * 1024
WORKTREE_ARCHIVE_LIMIT = 16 * 1024 * 1024
WORKTREE_EXTRACT_BYTES_LIMIT = 16 * 1024 * 1024
WORKTREE_EXTRACT_MEMBERS_LIMIT = 10_000
WORKTREE_GIT_STDERR_LIMIT = 64_000
WORKTREE_APPLY_STDOUT_LIMIT = 64_000
WORKTREE_GIT_TIMEOUT = 60
WORKTREE_GIT_CLEANUP_TIMEOUT = 2


async def _read_binary_prefix(stream, limit):
    retained = bytearray()
    overflow = False
    while True:
        chunk = await stream.read(16_384)
        if not chunk:
            break
        room = max(0, limit - len(retained))
        retained.extend(chunk[:room])
        overflow = overflow or len(chunk) > room
    return bytes(retained), overflow


async def _write_binary_input(stream, data):
    complete = True
    try:
        for offset in range(0, len(data), 16_384):
            stream.write(data[offset:offset + 16_384])
            await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        complete = False
    finally:
        stream.close()
    try:
        await stream.wait_closed()
    except (BrokenPipeError, ConnectionResetError):
        complete = False
    return complete


async def _collect_binary(proc, stdout_limit, stderr_limit, input_data=None):
    tasks = [asyncio.create_task(_read_binary_prefix(proc.stdout, stdout_limit)),
             asyncio.create_task(_read_binary_prefix(proc.stderr, stderr_limit))]
    if input_data is not None:
        tasks.append(asyncio.create_task(_write_binary_input(proc.stdin, input_data)))
    try:
        results = await asyncio.gather(*tasks)
        await proc.wait()
        return results[0], results[1], (results[2] if input_data is not None else True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _cleanup_binary(proc, communication):
    try:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        done, _ = await asyncio.wait({communication}, timeout=WORKTREE_GIT_CLEANUP_TIMEOUT)
        if not done:
            communication.cancel()
        else:
            try:
                communication.result()
            except (Exception, asyncio.CancelledError):
                pass
        waiter = asyncio.create_task(proc.wait())
        done, _ = await asyncio.wait({waiter}, timeout=WORKTREE_GIT_CLEANUP_TIMEOUT)
        if not done:
            waiter.cancel()
    except Exception:
        # Cleanup is best effort; do not hide the original timeout/cancellation.
        pass


async def _cleanup_late_binary_spawn(spawn, stdout_limit, stderr_limit):
    try:
        proc = await spawn
    except Exception:
        return
    communication = asyncio.create_task(_collect_binary(proc, stdout_limit, stderr_limit))
    await _cleanup_binary(proc, communication)


async def _run_binary_git(executable, args, env, *, stdout_limit, stderr_limit, timeout, input_data=None):
    """Capture binary stdout separately; truncation is always an error.

    Direct-child cleanup is best effort. Spawn and escaped descendants can
    outlive the caller; timeout begins after subprocess creation completes.
    """
    from . import checkpoints
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        executable, *args, stdin=asyncio.subprocess.PIPE if input_data is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env))
    try:
        proc = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        checkpoints._track_git_cleanup(_cleanup_late_binary_spawn(spawn, stdout_limit, stderr_limit))
        raise
    communication = asyncio.create_task(_collect_binary(proc, stdout_limit, stderr_limit, input_data))
    try:
        done, _ = await asyncio.wait({communication}, timeout=timeout)
    except asyncio.CancelledError:
        cleanup = checkpoints._track_git_cleanup(_cleanup_binary(proc, communication))
        await asyncio.shield(cleanup)
        raise
    if not done:
        cleanup = checkpoints._track_git_cleanup(_cleanup_binary(proc, communication))
        await asyncio.shield(cleanup)
        return 124, b'', b'timeout'
    try:
        (out, out_over), (err, err_over), input_complete = communication.result()
    except Exception:
        cleanup = checkpoints._track_git_cleanup(_cleanup_binary(proc, communication))
        await asyncio.shield(cleanup)
        raise
    if out_over or err_over or (not input_complete and proc.returncode == 0):
        return 125, b'', err
    return proc.returncode or 0, out, err


def _git_env() -> dict[str, str]:
    """Do not let inherited Git path/index overrides redirect worktree operations."""
    env = sanitized_env()
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR',
                'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_NAMESPACE'):
        env.pop(key, None)
    return env


def wt_path(sub_sid: str):
    if not _valid_session_id(sub_sid):
        raise ValueError('Invalid worktree session ID')
    return config.WORKSPACES_DIR / f"wt-{sub_sid}"


def _repo(sid: str):
    if not _valid_session_id(sid):
        raise ValueError('Invalid worktree repository key')
    return config.WORKSPACES_DIR / f".ckpt-{sid}.git"


async def _run(*args: str, timeout: float = 60) -> tuple[int, str]:
    git = GIT
    if git is None:
        return 127, "git không có"
    # Share the checkpoint runner's bounded drain and direct-child cleanup.
    # Overflow is an error, not a successful truncated Git response.
    from . import checkpoints
    return await checkpoints._run_with_env(list(args), _git_env(), executable=git, timeout=timeout)


async def available_for(sid: str) -> bool:
    if not _valid_session_id(sid):
        return False
    repo = _repo(sid)
    if not GIT or not repo.exists():
        return False
    rc, _ = await _run("--git-dir", str(repo), "rev-parse", "refs/heads/forge")
    return rc == 0


async def make(src_sid: str, sub_sid: str) -> str | None:
    """Tạo worktree `wt-<sub_sid>` từ branch forge của cha, branch riêng iso/<sub_sid>.

    Trả về đường dẫn (str) hoặc None nếu không khả dụng.
    """
    if not _valid_session_id(src_sid) or not _valid_session_id(sub_sid):
        return None
    path = wt_path(sub_sid)
    # Never remove or reuse a preexisting path: it may contain unrelated data
    # or an existing worktree with unmerged changes. This check is not atomic
    # with Git's subsequent creation, and does not establish filesystem isolation.
    if path.exists() or path.is_symlink():
        return None
    if not await available_for(src_sid):
        return None
    repo = str(_repo(src_sid))
    config.ensure_dirs()
    if path.exists() or path.is_symlink():
        return None
    from . import checkpoints
    if not checkpoints.ensure_exact_attributes(repo):
        return None
    rc, out = await _run("--git-dir", repo, "worktree", "add", "-b",
                         f"iso/{sub_sid}", str(path), "forge")
    if rc != 0:
        print(f"[worktree] add lỗi: {out[:200]}")
        return None
    return str(path)


async def _worktree_matches(wt: Path, repo: Path, sub_sid: str) -> bool:
    """Check repo, branch and Git's reciprocal linked-worktree path metadata.

    This is best effort, not an attestation or protection against replacement.
    """
    try:
        rc, common = await _run('-C', str(wt), 'rev-parse', '--git-common-dir')
        if rc != 0 or not common.strip():
            return False
        actual = Path(common.strip())
        if not actual.is_absolute():
            actual = wt / actual
        common_repo = repo.resolve(strict=True)
        if actual.resolve(strict=True) != common_repo:
            return False
        # A copied .git file can resolve to the same repo and branch from a
        # different directory. Check Git's worktree-admin backlink as well.
        gitfile = wt / '.git'
        if gitfile.is_symlink() or not gitfile.is_file():
            return False
        rc, admin_text = await _run('-C', str(wt), 'rev-parse', '--git-dir')
        if rc != 0 or not admin_text.strip():
            return False
        admin = Path(admin_text.strip())
        if not admin.is_absolute():
            admin = wt / admin
        if admin.is_symlink():
            return False
        admin = admin.resolve(strict=True)
        if admin.parent != (common_repo / 'worktrees').resolve(strict=True):
            return False
        backlink = admin / 'gitdir'
        if backlink.is_symlink() or not backlink.is_file():
            return False
        with backlink.open('rb') as stream:
            raw = stream.read(8193)
        if not raw or len(raw) > 8192 or b'\x00' in raw:
            return False
        import os
        back = Path(os.fsdecode(raw.rstrip(b'\r\n')))
        if not back.is_absolute():
            back = admin / back
        if back.resolve(strict=True) != gitfile.resolve(strict=True):
            return False
        rc, branch = await _run('-C', str(wt), 'symbolic-ref', '--quiet', '--short', 'HEAD')
        return rc == 0 and branch.strip() == f'iso/{sub_sid}'
    except (OSError, RuntimeError, ValueError):
        return False


async def diff_stat_result(sub_sid: str, src_sid: str, wt=None) -> dict:
    """Return explicit status; an empty successful stat means no changes.

    Staging may mutate the worktree index even when the later diff fails.
    """
    from .hooks import HookTrustDenied
    failure = {"ok": False, "stat": ""}
    if not _valid_session_id(sub_sid) or not _valid_session_id(src_sid):
        return failure
    try:
        expected = wt_path(sub_sid)
        candidate = expected if wt is None else Path(wt)
        if (expected.is_symlink() or candidate.is_symlink() or not expected.is_dir() or
                candidate.resolve(strict=True) != expected.resolve(strict=True)):
            return failure
        repo = _repo(src_sid)
        if not GIT or not repo.exists():
            return failure
        if not await _worktree_matches(expected, repo, sub_sid):
            return failure
        env_wt = ["-C", str(expected)]
        rc, _ = await _run(*env_wt, "add", "-A", "--", ".")
        if rc != 0:
            return failure
        rc, out = await _run(*env_wt, "diff", "--stat", f"iso/{sub_sid}", "--")
        return {"ok": True, "stat": out} if rc == 0 else failure
    except HookTrustDenied:
        raise
    except Exception:
        return failure


async def diff_stat(sub_sid: str, src_sid: str, wt=None) -> str:
    """Legacy text-only API: empty still means either no changes or failure."""
    result = await diff_stat_result(sub_sid, src_sid, wt)
    return result['stat'] if result['ok'] else ""


async def merge(sub_sid: str, src_sid: str, parent_sid: str, parent_ws) -> dict:
    """Gộp thay đổi của worktree sub về workspace cha.

    Patch = diff (branch iso/<sub> → working tree của wt) trong repo checkpoint
    CỦA CHA, áp bằng `git apply` vào workspace cha. Trả {"ok", "message", "files"}.
    """
    if not all(_valid_session_id(sid) for sid in (sub_sid, src_sid, parent_sid)):
        return {"ok": False, "message": "ID worktree không hợp lệ", "files": 0}
    repo = _repo(src_sid)
    wt = wt_path(sub_sid)
    if not GIT or not repo.exists() or wt.is_symlink() or not wt.is_dir():
        return {"ok": False, "message": "worktree không tồn tại hoặc không hợp lệ", "files": 0}
    if not await _worktree_matches(wt, repo, sub_sid):
        return {"ok": False, "message": "worktree không khớp repo hoặc branch", "files": 0}
    env_wt = ["-C", str(wt)]
    rc, _ = await _run(*env_wt, "add", "-A", "--", ".")
    if rc != 0:
        return {"ok": False, "message": "không thể chuẩn bị diff worktree", "files": 0}
    # Keep binary patch bytes intact and never apply truncated output.
    try:
        rc, raw, err = await _run_binary_git(
            GIT, [*env_wt, "diff", "--binary", f"iso/{sub_sid}", "--"], _git_env(),
            stdout_limit=WORKTREE_PATCH_LIMIT, stderr_limit=WORKTREE_GIT_STDERR_LIMIT,
            timeout=WORKTREE_GIT_TIMEOUT)
    except Exception:
        return {"ok": False, "message": "diff lỗi; không thể xác nhận patch worktree", "files": 0}
    if rc != 0:
        return {"ok": False, "message": "diff lỗi hoặc vượt giới hạn; patch chưa được áp", "files": 0}
    if not raw.strip():
        return {"ok": True, "message": "(worktree không khác gì điểm rẽ nhánh — không có gì để gộp)",
                "files": 0}
    _rc, stat = await _run(*env_wt, "diff", "--stat", f"iso/{sub_sid}", "--")
    n_files = len([ln for ln in stat.splitlines() if "|" in ln])
    # Undo uses the workspace key and stores pre-operation state. Do not treat
    # the isolated worktree's session-keyed base as the parent's undo history.
    from . import checkpoints
    try:
        checkpoint = await checkpoints.snapshot(checkpoints.key_for(parent_ws), parent_ws,
                                                f"merge wt-{sub_sid}")
    except Exception:
        checkpoint = None
    warning = ("" if checkpoint else
               " Cảnh báo: không tạo được checkpoint trước khi gộp; undo có thể không khôi phục trạng thái trước khi gộp.")
    # Name the repository and the work tree explicitly. Without --git-dir Git looks for a
    # repository above the workspace: inside a clone it then skips every path ("Skipped
    # patch", exit 0), and a global core.autocrlf converts line endings. The checkpoint
    # repository carries the rule that disables conversions (see checkpoints).
    # A timeout, overflow or failure cannot prove the patch had no side effects; never
    # claim rollback.
    if not checkpoints.ensure_exact_attributes(repo):
        return {"ok": False, "message": "không thể đặt quy tắc byte-exact cho repo; patch chưa được áp",
                "files": 0, "checkpoint_created": bool(checkpoint)}
    try:
        rc, _out, _err = await _run_binary_git(
            GIT, ["-C", str(parent_ws), "--git-dir", str(repo), "--work-tree", str(parent_ws),
                  "apply", "--whitespace=nowarn", "-"], _git_env(),
            stdout_limit=WORKTREE_APPLY_STDOUT_LIMIT, stderr_limit=WORKTREE_GIT_STDERR_LIMIT,
            timeout=WORKTREE_GIT_TIMEOUT, input_data=raw)
    except Exception:
        rc = 125
    if rc != 0:
        return {"ok": False,
                "message": ("Không thể xác nhận áp patch; workspace có thể đã thay đổi một phần. "
                            "Hãy kiểm tra trước khi thử lại.") + warning,
                "files": 0, "checkpoint_created": bool(checkpoint)}
    # Exit code 0 does not prove the patch was applied; compare with the work folder.
    mismatched = await _paths_not_applied(wt, parent_ws, sub_sid)
    if mismatched is None or mismatched:
        return {"ok": False,
                "message": ("Git báo đã áp patch nhưng workspace không khớp worktree"
                            + (f" ({len(mismatched)} đường dẫn)" if mismatched else "")
                            + "; workspace có thể đã thay đổi một phần. Hãy kiểm tra trước khi thử lại.")
                           + warning,
                "files": 0, "checkpoint_created": bool(checkpoint)}
    return {"ok": True, "message": f"Đã gộp {n_files} file từ worktree về workspace cha." + warning,
            "files": n_files, "checkpoint_created": bool(checkpoint)}


def _entry_state(path: Path):
    """Comparable content of one path: None if absent, else ('link'|'file', bytes)."""
    import os
    if path.is_symlink():
        return ("link", os.fsencode(os.readlink(path)))
    if path.is_file():
        return ("file", path.read_bytes())
    if path.exists():
        return ("other", b"")
    return None


async def _paths_not_applied(wt: Path, parent_ws, sub_sid: str) -> list[str] | None:
    """Paths of the patch whose parent content differs from the work folder; None if unknown.

    The work folder was just staged, so ``diff --name-only`` against the branch lists exactly
    the paths of the patch. ``--no-renames`` lists both sides of a rename.
    """
    try:
        rc, raw, _err = await _run_binary_git(
            GIT, ["-C", str(wt), "diff", "--name-only", "-z", "--no-renames", f"iso/{sub_sid}", "--"],
            _git_env(), stdout_limit=WORKTREE_PATCH_LIMIT, stderr_limit=WORKTREE_GIT_STDERR_LIMIT,
            timeout=WORKTREE_GIT_TIMEOUT)
        if rc != 0:
            return None
        import os
        parent = Path(parent_ws)
        bad: list[str] = []
        for item in raw.split(b"\0"):
            if not item:
                continue
            rel = os.fsdecode(item)
            if _entry_state(parent / rel) != _entry_state(wt / rel):
                bad.append(rel)
        return bad
    except Exception:
        return None


async def discard(sub_sid: str, src_sid: str) -> dict:
    """Remove only a validated worktree; never delete a child checkpoint repo.

    Validation is best effort and cannot protect against concurrent replacement.
    Partial removal is reported explicitly if branch cleanup fails.
    """
    if not _valid_session_id(sub_sid) or not _valid_session_id(src_sid):
        return {"ok": False, "removed": [], "message": "ID worktree không hợp lệ"}
    path = wt_path(sub_sid)
    repo = _repo(src_sid)
    if (not GIT or path.is_symlink() or not path.is_dir() or not repo.is_dir()
            or not await _worktree_matches(path, repo, sub_sid)):
        return {"ok": False, "removed": [], "message": "worktree không khớp hoặc không tồn tại"}
    rc, _ = await _run("--git-dir", str(repo), "worktree", "remove", "--force", str(path))
    if rc != 0 or path.exists() or path.is_symlink():
        return {"ok": False, "removed": [], "message": "không thể xác nhận đã bỏ worktree; kiểm tra trước khi thử lại"}
    removed = [str(path)]
    rc, _ = await _run("--git-dir", str(repo), "branch", "-D", f"iso/{sub_sid}")
    if rc != 0:
        return {"ok": False, "removed": removed, "message": "đã bỏ worktree nhưng chưa xóa được branch; kiểm tra trước khi thử lại"}
    return {"ok": True, "removed": removed}


async def list_all() -> list[dict]:
    """Quét worktree đang tồn tại (wt-*) + dòng diff ngắn (repo cha suy từ file .git)."""
    out: list[dict] = []
    if not config.WORKSPACES_DIR.exists():
        return out
    for p in sorted(config.WORKSPACES_DIR.glob("wt-*")):
        sub_sid = p.name[3:]
        if not _valid_session_id(sub_sid):
            continue
        src_sid = ""
        try:
            gitfile = (p / ".git").read_text(encoding="utf-8").strip()
            # "gitdir: <...>/.ckpt-<src>.git/worktrees/<name>"
            marker = ".ckpt-"
            seg = next(x for x in gitfile.split("/") if marker in x)
            src_sid = seg[len(marker):-len(".git")]
        except Exception:  # noqa: S110, BLE001 — không parse được thì bỏ qua chi tiết
            pass
        result = await diff_stat_result(sub_sid, src_sid, p) if src_sid else {"ok": False, "stat": ""}
        stat = result['stat']
        label = ("(không thể xác nhận diff worktree; hãy kiểm tra trước khi tiếp tục)"
                 if not result['ok'] else
                 (stat.splitlines()[-1] if stat else "(không khác gì điểm rẽ nhánh)"))
        out.append({"session": sub_sid, "src": src_sid, "path": str(p),
                    "stat": label, "detail": stat, "diff_ok": result['ok']})
    return out


def _rename_noreplace(src: Path, dst: Path) -> bool:
    """Linux atomic no-replace rename; return False when unavailable.

    Other errors propagate: in particular EEXIST must never trigger a fallback.
    """
    import ctypes
    import errno
    import os
    import sys
    if not sys.platform.startswith('linux'):
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError:
        return False
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    # AT_FDCWD and RENAME_NOREPLACE, as defined by Linux.
    if rename(-100, os.fsencode(src), -100, os.fsencode(dst), 1) == 0:
        return True
    err = ctypes.get_errno()
    if err in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
        return False
    raise OSError(err, os.strerror(err), str(dst))


def _extract_archive_staged(raw: bytes, dst_dir) -> bool:
    """Extract in a sibling and publish without replacing a destination.

    Linux uses atomic no-replace rename where supported. Else copytree can
    leave a partial destination on failure. Neither path is a sandbox.
    """
    import io
    import tarfile
    import tempfile
    try:
        destination = Path(dst_dir)
        if destination.exists() or destination.is_symlink():
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.forge-archive-', dir=destination.parent) as staging:
            members = 0
            total_bytes = 0

            def bounded_data_filter(member, target):
                nonlocal members, total_bytes
                members += 1
                if members > WORKTREE_EXTRACT_MEMBERS_LIMIT:
                    raise ValueError('archive member limit exceeded')
                # Hardlink extraction may fall back to copying an earlier file,
                # bypassing byte accounting based on the link header's size.
                if member.islnk():
                    raise ValueError('archive hardlinks are not supported')
                if member.isfile():
                    if member.size < 0:
                        raise ValueError('invalid archive size')
                    total_bytes += member.size
                    if total_bytes > WORKTREE_EXTRACT_BYTES_LIMIT:
                        raise ValueError('archive extraction size limit exceeded')
                return tarfile.data_filter(member, target)

            with tarfile.open(fileobj=io.BytesIO(raw), mode='r|') as tar:
                tar.extractall(staging, filter=bounded_data_filter)
            if not _rename_noreplace(Path(staging), destination):
                # Portable fallback: exclusive destination creation, but the
                # following copies are not transactional.
                shutil.copytree(staging, destination, symlinks=True)
        return True
    except Exception:
        return False


async def export_tree(src_sid: str, dst_dir) -> bool:
    """Xuất cây snapshot `forge` của src vào dst_dir (fork từ trạng thái nhất quán)."""
    if not _valid_session_id(src_sid) or not GIT or not await available_for(src_sid):
        return False
    from . import checkpoints
    if not checkpoints.ensure_exact_attributes(_repo(src_sid)):
        return False
    try:
        rc, out, _err = await _run_binary_git(
            GIT, ["--git-dir", str(_repo(src_sid)), "archive", "forge", "--"], _git_env(),
            stdout_limit=WORKTREE_ARCHIVE_LIMIT, stderr_limit=WORKTREE_GIT_STDERR_LIMIT,
            timeout=WORKTREE_GIT_TIMEOUT)
    except Exception:
        return False
    if rc != 0 or not out:
        return False
    return _extract_archive_staged(out, dst_dir)


def _run_binary_sync(executable, args, env, *, stdout_limit, stderr_limit, timeout):
    """Synchronous bounded drain, for legacy fork. Direct-child cleanup only.

    Reader threads are daemonized: descendants retaining pipes can outlive this
    bounded wait. This function does not limit Git CPU, disk or total output.
    """
    import os
    import subprocess
    import threading
    import time

    proc = subprocess.Popen([executable, *args], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    results = [None, None]
    readers = []
    started_streams = set()

    def drain(stream, limit, index):
        retained = bytearray()
        overflow = False
        try:
            while True:
                chunk = os.read(stream.fileno(), 16_384)
                if not chunk:
                    break
                room = max(0, limit - len(retained))
                retained.extend(chunk[:room])
                overflow = overflow or len(chunk) > room
            results[index] = (bytes(retained), overflow)
        except Exception:
            results[index] = None
        finally:
            try:
                stream.close()
            except OSError:
                pass

    timed_out = False
    try:
        for stream, limit, index in ((proc.stdout, stdout_limit, 0), (proc.stderr, stderr_limit, 1)):
            thread = threading.Thread(target=drain, args=(stream, limit, index), daemon=True)
            thread.start()
            readers.append(thread)
            started_streams.add(index)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
    finally:
        if proc.poll() is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=WORKTREE_GIT_CLEANUP_TIMEOUT)
            except subprocess.TimeoutExpired:
                pass
        deadline = time.monotonic() + WORKTREE_GIT_CLEANUP_TIMEOUT
        for reader in readers:
            reader.join(timeout=max(0, deadline - time.monotonic()))
        for index, stream in enumerate((proc.stdout, proc.stderr)):
            if index not in started_streams and stream is not None:
                stream.close()
    if timed_out:
        return 124, b'', b'timeout'
    if proc.returncode is None or any(reader.is_alive() for reader in readers) or any(x is None for x in results):
        return 125, b'', b'capture failed'
    (out, out_over), (err, err_over) = results
    if out_over or err_over:
        return 125, b'', err
    return proc.returncode or 0, out, err


def export_tree_sync(src_sid: str, dst_dir) -> bool:
    """Bản sync của export_tree cho SessionStore.fork() (archive cục bộ, nhanh)."""
    if not _valid_session_id(src_sid) or not GIT or not _repo(src_sid).exists():
        return False
    from . import checkpoints
    if not checkpoints.ensure_exact_attributes(_repo(src_sid)):
        return False
    try:
        rc, raw, _err = _run_binary_sync(
            GIT, ["--git-dir", str(_repo(src_sid)), "archive", "forge", "--"], _git_env(),
            stdout_limit=WORKTREE_ARCHIVE_LIMIT, stderr_limit=WORKTREE_GIT_STDERR_LIMIT,
            timeout=120)
    except Exception:
        return False
    if rc != 0 or not raw:
        return False
    return _extract_archive_staged(raw, dst_dir)
