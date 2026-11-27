"""Experimental isolated current-workspace capture for future worktree routing.

Not used by production creation or management. A separate repository is reserved
per child, leaving the parent undo ref and index alone. Concurrent file changes
can make the captured tree inconsistent; this is not a sandbox or an atomic
filesystem snapshot. Failure/cancellation may leave a partial repo, deliberately
not deleted here. Callers must establish their own authorized parent/child binding.
"""
from __future__ import annotations

import re
from pathlib import Path
from . import checkpoints, config, worktree

_CHILD = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_-]{0,79}\Z')
_OID = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')


async def capture(child_sid: str, workspace) -> dict:
    """Reserve a new base repo and capture current files; return only on success.

    The repo is intentionally retained on failure and success; this prototype has
    no safe lifecycle/authorization cleanup implementation. A given child key
    cannot be reused, even after a failed capture.
    """
    fail = {'ok': False, 'message': 'Worktree base capture unavailable; inspect partial artifacts before retrying.'}
    if not isinstance(child_sid, str) or not _CHILD.fullmatch(child_sid):
        return fail
    try:
        if not checkpoints.available() or not config.load_config().get('checkpoints_enabled', True):
            return fail
        ws = Path(workspace).resolve(strict=True)
        if not ws.is_dir():
            return fail
        key = f'wtbase-{child_sid}'
        repo = checkpoints._repo_dir(key)
        repo.parent.mkdir(parents=True, exist_ok=True)
        repo.mkdir()  # exclusive: no existing repo may be overwritten or reused
        base = ['--git-dir', str(repo), '--work-tree', str(ws)]
        env = worktree._git_env()
        async def run(*args):
            return await checkpoints._run_with_env(base + list(args), env)
        for step in (('init', '-q'), ('config', 'user.email', 'forge@local'),
                     ('config', 'user.name', 'forge-worktree-base')):
            rc, _ = await run(*step)
            if rc != 0:
                return fail
        if not checkpoints.ensure_exact_attributes(repo, new=True):
            return fail
        rc, _ = await run('add', '-A', '--', '.', *[f':(exclude){e}' for e in checkpoints.EXCLUDES])
        if rc != 0:
            return fail
        rc, tree = await run('write-tree')
        if rc != 0 or not _OID.fullmatch(tree):
            return fail
        rc, commit = await run('commit-tree', tree, '-m', 'worktree base capture')
        if rc != 0 or not _OID.fullmatch(commit) or len(commit) != len(tree):
            return fail
        rc, _ = await run('update-ref', 'refs/heads/forge', commit, '')
        if rc != 0:
            return fail
        return {'ok': True, 'repo_key': key, 'commit': commit}
    except Exception:
        return fail
