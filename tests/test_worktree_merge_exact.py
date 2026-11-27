"""worktree.merge must apply the patch byte for byte, or say that it could not (issue #14)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import checkpoints, config, worktree

FILES = {"lf.txt": b"one\ntwo\n", "crlf.txt": b"one\r\ntwo\r\n", "mixed.txt": b"one\r\ntwo\n"}


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@unittest.skipUnless(shutil.which("git"), "Git required")
class MergeExact(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # A Git configuration of our own, so the machine's settings cannot change the result.
        self.gitconfig = self.root / "gitconfig"
        self.gitconfig.write_text("")
        env = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(self.gitconfig),
                                      "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        data = self.root / "data"
        wsdir = data / "workspaces"
        wsdir.mkdir(parents=True)
        (data / "sessions").mkdir()
        cfg = patch.multiple(config, DATA_DIR=data, WORKSPACES_DIR=wsdir,
                             SESSIONS_DIR=data / "sessions", CONFIG_FILE=data / "config.json")
        cfg.start()
        self.addCleanup(cfg.stop)

    async def _merge(self, autocrlf: str, in_repository: bool):
        self.gitconfig.write_text(f"[core]\n\tautocrlf = {autocrlf}\n")
        top = Path(tempfile.mkdtemp(dir=self.root))
        if in_repository:  # as <clone>/data/workspaces/<session id> is
            _git("init", "-q", str(top))
        ws = top / "workspace"
        ws.mkdir()
        for name, data in FILES.items():
            (ws / name).write_bytes(data)
        self.assertIsNotNone(await checkpoints.snapshot("parent", ws, "base"))
        wt = Path(await worktree.make("parent", "sub"))
        want = {"new.txt": b"new\n"}
        (wt / "new.txt").write_bytes(want["new.txt"])
        for name, data in FILES.items():
            want[name] = data.replace(b"two", b"changed")
            (wt / name).write_bytes(want[name])
        result = await worktree.merge("sub", "parent", "parent", ws)
        return ws, want, result

    def _assert_exact(self, ws, want):
        for name, data in want.items():
            self.assertEqual((ws / name).read_bytes(), data, name)

    async def test_workspace_below_the_root_of_a_repository(self):
        ws, want, result = await self._merge("false", in_repository=True)
        self.assertTrue(result["ok"], result)
        self._assert_exact(ws, want)

    async def test_workspace_in_a_repository_with_autocrlf_true(self):
        ws, want, result = await self._merge("true", in_repository=True)
        self.assertTrue(result["ok"], result)
        self._assert_exact(ws, want)

    async def test_plain_folder_with_autocrlf_true(self):
        ws, want, result = await self._merge("true", in_repository=False)
        self.assertTrue(result["ok"], result)
        self._assert_exact(ws, want)

    async def test_plain_folder_with_autocrlf_false(self):
        ws, want, result = await self._merge("false", in_repository=False)
        self.assertTrue(result["ok"], result)
        self._assert_exact(ws, want)

    async def test_deleted_file_is_removed_from_workspace(self):
        self.gitconfig.write_text("")
        ws = self.root / "ws"
        ws.mkdir()
        (ws / "gone.txt").write_bytes(b"x\n")
        (ws / "stay.txt").write_bytes(b"y\n")
        self.assertIsNotNone(await checkpoints.snapshot("parent", ws, "base"))
        wt = Path(await worktree.make("parent", "sub"))
        (wt / "gone.txt").unlink()
        result = await worktree.merge("sub", "parent", "parent", ws)
        self.assertTrue(result["ok"], result)
        self.assertFalse((ws / "gone.txt").exists())
        self.assertEqual((ws / "stay.txt").read_bytes(), b"y\n")

    async def test_success_is_not_reported_when_the_workspace_does_not_match(self):
        """Exit code 0 from Git is not evidence: if nothing was applied, merge must say so."""
        self.gitconfig.write_text("")
        ws = self.root / "ws"
        ws.mkdir()
        (ws / "f.txt").write_bytes(b"one\n")
        self.assertIsNotNone(await checkpoints.snapshot("parent", ws, "base"))
        wt = Path(await worktree.make("parent", "sub"))
        (wt / "f.txt").write_bytes(b"two\n")
        real = worktree._run_binary_git

        async def skip_apply(git, args, env, **kw):
            if "apply" in args:  # Git's "Skipped patch" case: exit 0, nothing written
                return 0, b"", b""
            return await real(git, args, env, **kw)

        with patch.object(worktree, "_run_binary_git", skip_apply):
            result = await worktree.merge("sub", "parent", "parent", ws)
        self.assertFalse(result["ok"], result)
        self.assertEqual((ws / "f.txt").read_bytes(), b"one\n")


if __name__ == "__main__":
    unittest.main()
