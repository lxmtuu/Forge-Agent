"""Extraction resource accounting applies to both archive export paths."""
import io
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from engine import worktree


def archive(entries):
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, data in entries:
            info=tarfile.TarInfo(name); info.size=len(data); tar.addfile(info,io.BytesIO(data))
    return buf.getvalue()

def hardlink_archive():
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w') as tar:
        item=tarfile.TarInfo('file'); item.size=4; tar.addfile(item,io.BytesIO(b'data'))
        link=tarfile.TarInfo('link'); link.type=tarfile.LNKTYPE; link.linkname='file'; tar.addfile(link)
    return buf.getvalue()

class ArchiveLimits(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.dst=self.root/'dst'

    def assert_clean(self):
        self.assertFalse(self.dst.exists())
        self.assertFalse(any(p.name.startswith('.forge-archive-') for p in self.root.iterdir()))

    def test_cumulative_size_rejected_and_exact_limit_succeeds(self):
        raw=archive([('one',b'123'),('two',b'456')])
        with patch.object(worktree,'WORKTREE_EXTRACT_BYTES_LIMIT',5):
            self.assertFalse(worktree._extract_archive_staged(raw,self.dst))
        self.assert_clean()
        with patch.object(worktree,'WORKTREE_EXTRACT_BYTES_LIMIT',6):
            self.assertTrue(worktree._extract_archive_staged(raw,self.dst))
        self.assertEqual((self.dst/'two').read_bytes(),b'456')

    def test_member_count_includes_empty_entries(self):
        raw=archive([('one',b''),('two',b''),('three',b'')])
        with patch.object(worktree,'WORKTREE_EXTRACT_MEMBERS_LIMIT',2):
            self.assertFalse(worktree._extract_archive_staged(raw,self.dst))
        self.assert_clean()
        with patch.object(worktree,'WORKTREE_EXTRACT_MEMBERS_LIMIT',3):
            self.assertTrue(worktree._extract_archive_staged(raw,self.dst))

    def test_hardlinks_rejected_to_prevent_unaccounted_copy_fallback(self):
        self.assertFalse(worktree._extract_archive_staged(hardlink_archive(),self.dst))
        self.assert_clean()

    @unittest.skipUnless(shutil.which('tar'), 'tar required')
    def test_sparse_archive_uses_logical_size_not_payload_size(self):
        source=self.root/'sparse'; source.touch()
        with source.open('r+b') as f: f.truncate(1024*1024)
        packed=self.root/'sparse.tar'
        proc=subprocess.run(['tar','--format=pax','--sparse','-cf',str(packed),'-C',str(self.root),'sparse'],capture_output=True)
        if proc.returncode: self.skipTest('GNU sparse tar options unavailable')
        with tarfile.open(packed) as tar:
            info=tar.next()
            if not info.issparse(): self.skipTest('tar did not create a sparse entry')
            self.assertEqual(info.size,1024*1024)
        with patch.object(worktree,'WORKTREE_EXTRACT_BYTES_LIMIT',1024):
            self.assertFalse(worktree._extract_archive_staged(packed.read_bytes(),self.dst))
        self.assert_clean()

    async def test_both_public_exports_enforce_extraction_limits(self):
        raw=archive([('file',b'123456')])
        with patch.object(worktree,'WORKTREE_EXTRACT_BYTES_LIMIT',5), \
             patch.object(worktree,'available_for',new_callable=AsyncMock,return_value=True), \
             patch.object(worktree,'_run_binary_git',new_callable=AsyncMock,return_value=(0,raw,b'')), \
             patch.object(worktree,'_run_binary_sync',return_value=(0,raw,b'')), \
             patch.object(worktree,'GIT','git'), patch.object(worktree,'_repo') as repo, \
             patch('engine.checkpoints.ensure_exact_attributes',return_value=True):
            repo.return_value.exists.return_value=True
            self.assertFalse(await worktree.export_tree('source',self.dst)); self.assert_clean()
            self.assertFalse(worktree.export_tree_sync('source',self.dst)); self.assert_clean()
