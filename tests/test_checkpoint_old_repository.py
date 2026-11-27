"""A checkpoint repository created before the byte-exact rule is repaired, and its old snapshots are flagged.

The first snapshot of every case is made with the helper turned off, which is what the code before
the rule did. Git's file index then holds the files as unchanged, so only a snapshot that makes
Git read them again stores them exactly.
"""
import atexit
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory(prefix="forge-ckpt-old-")
atexit.register(lambda: _tmp.cleanup())
os.environ["FORGE_DATA_DIR"] = _tmp.name
os.environ.pop("FORGE_PROFILE", None)

from engine import checkpoints  # noqa: E402

FILES = {"lf.txt": b"one\ntwo\n", "crlf.txt": b"one\r\ntwo\r\n", "mixed.txt": b"one\r\ntwo\n"}


class OldRepository(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=_tmp.name))
        self.ws = self.root / "workspace"
        self.ws.mkdir()
        config = self.root / "gitconfig"
        config.write_text("[core]\n\tautocrlf = true\n")
        patcher = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, data in FILES.items():
            (self.ws / name).write_bytes(data)
        time.sleep(2.5)  # after this Git treats the files as unchanged
        self.key = checkpoints.key_for(self.ws)

    async def old_snapshot(self):
        with patch.object(checkpoints, "ensure_exact_attributes", return_value=True):
            self.assertIsNotNone(await checkpoints.snapshot(self.key, self.ws, "old"))

    def edit_all(self):
        for name in FILES:
            (self.ws / name).write_bytes(b"edited\n")

    async def test_a_snapshot_taken_after_the_repair_stores_untouched_files_exactly(self):
        await self.old_snapshot()
        (self.ws / "new.txt").write_bytes(b"a new file\n")
        self.assertIsNotNone(await checkpoints.snapshot(self.key, self.ws, "new"))
        self.edit_all()
        result = await checkpoints.undo(self.key, self.ws)
        self.assertTrue(result["ok"], result)
        for name, data in FILES.items():
            self.assertEqual((self.ws / name).read_bytes(), data, name)
        self.assertNotIn(checkpoints.LEGACY_NOTE, result["message"])  # this snapshot is exact

    async def test_an_old_snapshot_is_restored_with_a_note(self):
        await self.old_snapshot()
        self.edit_all()
        result = await checkpoints.undo(self.key, self.ws)
        self.assertTrue(result["ok"], result)
        self.assertIn(checkpoints.LEGACY_NOTE, result["message"])

    async def test_the_repair_is_recorded_once_and_a_new_repository_has_no_marker(self):
        await self.old_snapshot()
        repo = checkpoints._repo_dir(self.key)
        self.assertIsNotNone(await checkpoints.snapshot(self.key, self.ws, "new"))
        self.assertFalse((repo / checkpoints.LEGACY_PENDING).exists())
        self.assertTrue((repo / checkpoints.LEGACY_HEAD).exists())
        fresh = self.root / "fresh"
        fresh.mkdir()
        (fresh / "a.txt").write_bytes(b"a\n")
        fresh_key = checkpoints.key_for(fresh)
        self.assertIsNotNone(await checkpoints.snapshot(fresh_key, fresh, "first"))
        fresh_repo = checkpoints._repo_dir(fresh_key)
        self.assertFalse((fresh_repo / checkpoints.LEGACY_PENDING).exists())
        self.assertFalse((fresh_repo / checkpoints.LEGACY_HEAD).exists())
        self.assertTrue((await checkpoints.undo(fresh_key, fresh))["ok"])

    async def test_a_failed_index_removal_is_tried_again_by_the_next_call(self):
        await self.old_snapshot()
        (self.ws / "new.txt").write_bytes(b"a new file\n")
        real_unlink = Path.unlink

        def index_in_use(path, *args, **kwargs):  # what Windows answers while another process has it open
            if path.name == "index":
                raise PermissionError(13, "in use")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", index_in_use):
            self.assertIsNone(await checkpoints.snapshot(self.key, self.ws, "refused"))
        attributes = checkpoints._repo_dir(self.key) / "info" / "attributes"
        self.assertFalse(attributes.exists())  # still not repaired, so the next call starts over
        self.assertIsNotNone(await checkpoints.snapshot(self.key, self.ws, "new"))
        self.edit_all()
        result = await checkpoints.undo(self.key, self.ws)
        self.assertTrue(result["ok"], result)
        for name, data in FILES.items():
            self.assertEqual((self.ws / name).read_bytes(), data, name)
        self.assertNotIn(checkpoints.LEGACY_NOTE, result["message"])

    async def test_a_new_worktree_base_is_exact_and_has_no_legacy_record(self):
        from engine import worktree_base
        done = await worktree_base.capture("child-exact", self.ws)
        self.assertTrue(done["ok"], done)
        repo = checkpoints._repo_dir(done["repo_key"])
        self.assertEqual((repo / "info" / "attributes").read_text(), checkpoints.EXACT_ATTRIBUTES)
        self.assertFalse((repo / checkpoints.LEGACY_PENDING).exists())


if __name__ == "__main__":
    unittest.main()
