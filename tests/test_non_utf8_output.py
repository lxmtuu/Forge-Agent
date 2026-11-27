"""Handlers that print an error and carry on must not fail when stdout cannot encode the text.

Each case runs in a child process because the output encoding is fixed when Python starts.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK_TESTS = ["tests.test_hook_trust_compaction", "tests.test_hook_trust_notification",
              "tests.test_hook_trust_stop", "tests.test_hook_trust_turn_start"]


def run(args, encoding, *, data_dir=None):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("FORGE_", "PYTHONIO", "PYTHONUTF8"))}
    env.update(PYTHONUTF8="0", PYTHONIOENCODING=encoding, PYTHONPATH=str(ROOT))
    if data_dir:
        env["FORGE_DATA_DIR"] = data_dir
    return subprocess.run([sys.executable, *args], cwd=str(ROOT), env=env, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=300)


class NonUtf8Output(unittest.TestCase):
    def test_print_of_vietnamese_text_does_not_raise_with_a_narrow_encoding(self):
        code = ("import sys, engine\n"
                "print('[hooks] stop lỗi (bỏ qua): x')\n"
                "print('[hooks] stderr lỗi', file=sys.stderr)\n")
        # strict is PYTHONIOENCODING=cp1252; surrogateescape is the default of Python on Windows
        for encoding in ("cp1252", "ascii", "cp1252:surrogateescape", "ascii:surrogateescape"):
            with self.subTest(encoding=encoding):
                done = run(["-c", code], encoding)
                self.assertEqual(done.returncode, 0, done.stderr.decode("ascii", "replace"))
                self.assertIn(b"[hooks] stop l\\u1ed7i (b\\u1ecf qua): x", done.stdout)  # escaped, not dropped
                self.assertIn(b"l\\u1ed7i", done.stderr)

    def test_the_encoding_that_was_asked_for_is_kept(self):
        code = "import sys, engine\nprint(sys.stdout.encoding, sys.stdout.errors)\nprint('lỗi')\n"
        done = run(["-c", code], "cp1252")
        self.assertEqual(done.stdout.split()[0], b"cp1252")
        utf8 = run(["-c", code], "utf-8")
        self.assertIn("lỗi".encode("utf-8"), utf8.stdout)  # UTF-8 output is not escaped

    def test_a_handler_that_means_to_continue_continues(self):
        with tempfile.TemporaryDirectory() as data:
            for encoding in ("cp1252", "cp1252:surrogateescape"):
                with self.subTest(encoding=encoding):
                    done = run(["-m", "unittest", *HOOK_TESTS], encoding, data_dir=data)
                    self.assertEqual(done.returncode, 0, done.stderr.decode("ascii", "replace")[-1500:])


if __name__ == "__main__":
    unittest.main()
