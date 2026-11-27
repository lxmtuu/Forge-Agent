"""Worktree textual Git runner drains bounded output and cleans direct child."""
import asyncio
import sys
import tracemalloc
import unittest
from unittest.mock import patch
from engine import checkpoints, worktree

class WorktreeGitRunner(unittest.IsolatedAsyncioTestCase):
    async def run_python(self,code,timeout=5):
        with patch.object(worktree,'GIT',sys.executable):
            return await asyncio.wait_for(worktree._run('-c',code,timeout=timeout),10)

    async def test_large_output_is_bounded_and_not_reported_success(self):
        tracemalloc.start()
        try:
            rc,out=await self.run_python("import sys; sys.stdout.buffer.write(b'x'*12000000); sys.stdout.flush()")
            _,peak=tracemalloc.get_traced_memory()
        finally: tracemalloc.stop()
        self.assertEqual(rc,125); self.assertIn('output',out.lower()); self.assertLess(len(out),1000)
        self.assertLess(peak,4_000_000)

    async def test_output_at_cap_succeeds_and_larger_fails(self):
        with patch.object(checkpoints,'MAX_GIT_OUTPUT',128):
            rc,out=await self.run_python("import sys; sys.stdout.write('x'*128)")
            self.assertEqual((rc,out),(0,'x'*128))
            rc,out=await self.run_python("import sys; sys.stdout.write('x'*129); sys.exit(1)")
            self.assertEqual(rc,125); self.assertIn('output',out.lower())

    async def test_small_stderr_and_exit_code_remain_visible(self):
        # The runner decodes UTF-8. Write the bytes: a child's own stderr uses the ANSI code page on
        # Windows, so writing the text would send an escape (or fail) under a narrow encoding.
        rc,out=await self.run_python("import sys; sys.stderr.buffer.write('Vi\\u1ec7t'.encode('utf-8')); sys.stderr.flush(); sys.exit(7)")
        self.assertEqual((rc,out),(7,'Việt'))

    async def test_timeout_reaps_direct_child(self):
        processes=[]; original=asyncio.create_subprocess_exec
        async def spawn(*args,**kwargs):
            proc=await original(*args,**kwargs); processes.append(proc); return proc
        try:
            with patch.object(worktree,'GIT',sys.executable),patch('asyncio.create_subprocess_exec',side_effect=spawn):
                result=await asyncio.wait_for(worktree._run('-c',"import time; time.sleep(30)",timeout=.2),5)
            self.assertEqual(result,(124,'timeout')); self.assertIsNotNone(processes[0].returncode)
        finally:
            for proc in processes:
                if proc.returncode is None:
                    proc.kill(); await proc.wait()

    async def test_cancellation_during_spawn_tracks_late_child_cleanup(self):
        entered=asyncio.Event(); release=asyncio.Event(); processes=[]
        original=asyncio.create_subprocess_exec
        async def spawn(*args,**kwargs):
            entered.set(); await release.wait()
            proc=await original(*args,**kwargs); processes.append(proc); return proc
        try:
            with patch.object(worktree,'GIT',sys.executable),patch('asyncio.create_subprocess_exec',side_effect=spawn):
                task=asyncio.create_task(worktree._run('-c',"import time; time.sleep(30)"))
                await asyncio.wait_for(entered.wait(),3); task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                self.assertTrue(checkpoints._GIT_CLEANUPS)
                release.set(); self.assertEqual(await asyncio.wait_for(checkpoints.wait_git_cleanups(),5),0)
                self.assertEqual(len(processes),1); self.assertIsNotNone(processes[0].returncode)
        finally:
            release.set()
            for proc in processes:
                if proc.returncode is None: proc.kill(); await proc.wait()

    async def test_cancellation_reaps_direct_child_and_propagates(self):
        processes=[]; started=asyncio.Event(); original=asyncio.create_subprocess_exec
        async def spawn(*args,**kwargs):
            proc=await original(*args,**kwargs); processes.append(proc); started.set(); return proc
        try:
            with patch.object(worktree,'GIT',sys.executable),patch('asyncio.create_subprocess_exec',side_effect=spawn):
                task=asyncio.create_task(worktree._run('-c',"import time; time.sleep(30)"))
                await asyncio.wait_for(started.wait(),3); await asyncio.sleep(.05); task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                self.assertIsNotNone(processes[0].returncode)
        finally:
            for proc in processes:
                if proc.returncode is None:
                    proc.kill(); await proc.wait()
