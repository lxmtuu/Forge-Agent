"""Checkpoint undo and session fork restore the checkpointed bytes whatever Git is configured to do.

The result of `git add` / `checkout-index` / `archive` depends on core.autocrlf and on the
workspace's .gitattributes, so every case runs under a Git configuration of its own.
"""
import atexit
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory(prefix="forge-ckpt-exact-")
atexit.register(lambda: _tmp.cleanup())
os.environ["FORGE_DATA_DIR"] = _tmp.name
os.environ.pop("FORGE_PROFILE", None)

from engine import checkpoints, worktree  # noqa: E402

FILES = {"lf.txt": b"one\ntwo\n", "crlf.txt": b"one\r\ntwo\r\n", "mixed.txt": b"one\r\ntwo\n",
         "ident.txt": b"$Id$\n", "subst.txt": b"$Format:%H$\n"}

CONFIGS = {"autocrlf-true": "[core]\n\tautocrlf = true\n",
           "autocrlf-input": "[core]\n\tautocrlf = input\n",
           "autocrlf-false": "[core]\n\tautocrlf = false\n"}
ATTRIBUTES = {"none": None,
              "text-auto": "* text=auto\n",
              "eol-lf": "*.txt text eol=lf\n",
              "eol-crlf": "* text eol=crlf\n",
              "ident": "* ident\n",
              "export": "subst.txt export-subst\nlf.txt export-ignore\n"}


class ByteExact(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=_tmp.name))
        self.ws = self.root / "workspace"
        self.ws.mkdir()

    def git_config(self, text: str):
        path = self.root / "gitconfig"
        path.write_text(text)
        return patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(path), "GIT_CONFIG_NOSYSTEM": "1"})

    def write_files(self, attributes):
        if attributes is not None:
            (self.ws / ".gitattributes").write_text(attributes)
        for name, data in FILES.items():
            (self.ws / name).write_bytes(data)

    def assert_files_exact(self, directory: Path, skip=()):
        for name, data in FILES.items():
            if name in skip:
                continue
            self.assertEqual((directory / name).read_bytes(), data, name)

    async def test_undo_restores_exact_bytes_for_every_configuration(self):
        for cname, config in CONFIGS.items():
            for aname, attributes in ATTRIBUTES.items():
                with self.subTest(config=cname, attributes=aname):
                    self.ws = self.root / f"ws-{cname}-{aname}"
                    self.ws.mkdir()
                    with self.git_config(config):
                        self.write_files(attributes)
                        key = checkpoints.key_for(self.ws)
                        self.assertIsNotNone(await checkpoints.snapshot(key, self.ws, "before"))
                        for name in FILES:
                            (self.ws / name).write_bytes(b"edited\n")
                        result = await checkpoints.undo(key, self.ws)
                    self.assertTrue(result["ok"], result)
                    self.assert_files_exact(self.ws)

    async def test_repository_without_the_attributes_file_is_repaired_on_next_use(self):
        with self.git_config(CONFIGS["autocrlf-true"]):
            self.write_files(None)
            key = checkpoints.key_for(self.ws)
            self.assertIsNotNone(await checkpoints.snapshot(key, self.ws, "first"))
            attributes = checkpoints._repo_dir(key) / "info" / "attributes"
            attributes.unlink()  # a repository created before this rule existed
            for name in FILES:
                (self.ws / name).write_bytes(b"edited\n")
            result = await checkpoints.undo(key, self.ws)
        self.assertTrue(result["ok"], result)
        self.assertEqual(attributes.read_text(), checkpoints.EXACT_ATTRIBUTES)

    async def test_undo_refuses_when_conversions_cannot_be_disabled(self):
        with self.git_config(CONFIGS["autocrlf-true"]):
            self.write_files(None)
            key = checkpoints.key_for(self.ws)
            self.assertIsNotNone(await checkpoints.snapshot(key, self.ws, "first"))
            (self.ws / "lf.txt").write_bytes(b"edited\n")
            with patch.object(checkpoints, "ensure_exact_attributes", return_value=False):
                result = await checkpoints.undo(key, self.ws)
        self.assertFalse(result["ok"], result)
        self.assertEqual((self.ws / "lf.txt").read_bytes(), b"edited\n")

    async def test_snapshot_fails_closed_when_conversions_cannot_be_disabled(self):
        with self.git_config(CONFIGS["autocrlf-true"]):
            self.write_files(None)
            outcome = {}
            with patch.object(checkpoints, "ensure_exact_attributes", return_value=False):
                result = await checkpoints.snapshot(checkpoints.key_for(self.ws), self.ws, "x", outcome=outcome)
        self.assertIsNone(result)
        self.assertEqual(outcome["status"], "failed")

    async def test_fork_export_keeps_export_ignore_files_and_does_not_substitute(self):
        with self.git_config(CONFIGS["autocrlf-true"]):
            self.write_files(ATTRIBUTES["export"])
            key = checkpoints.key_for(self.ws)
            self.assertIsNotNone(await checkpoints.snapshot(key, self.ws, "first"))
            sync_dir, async_dir = self.root / "fork-sync", self.root / "fork-async"
            self.assertTrue(worktree.export_tree_sync(key, sync_dir))
            self.assertTrue(await worktree.export_tree(key, async_dir))
        for directory in (sync_dir, async_dir):
            self.assert_files_exact(directory)

    def test_attributes_file_is_written_once_and_is_idempotent(self):
        repo = self.root / "repo.git"
        repo.mkdir()
        self.assertTrue(checkpoints.ensure_exact_attributes(repo))
        target = repo / "info" / "attributes"
        self.assertEqual(target.read_bytes(), checkpoints.EXACT_ATTRIBUTES.encode())
        stamp = target.stat().st_mtime_ns
        self.assertTrue(checkpoints.ensure_exact_attributes(repo))
        self.assertEqual(target.stat().st_mtime_ns, stamp)


if __name__ == "__main__":
    unittest.main()
