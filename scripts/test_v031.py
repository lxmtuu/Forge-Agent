# -*- coding: utf-8 -*-
"""Suite v0.31 "Onboarding" — launcher 1-click (run_forge.bat/.sh + scripts/launch.py)
+ USER_GUIDE.md tiếng Việt. Bám research: bat phải PURE-ASCII (codepage lúc cmd parse
file quyết định), logic tiếng Việt nằm trong Python helper.

Kiểm: bat/sh đúng pattern research · launch.py --check chạy thật ·
MỌI lệnh slash trong USER_GUIDE phải TỒN TẠI trong code (docs không được bịa).

Chạy:  python scripts/test_v031.py
"""
import asyncio
import os
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v031-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")

PASS, FAIL = [], []


def check(name):
    def deco(fn):
        async def run():
            try:
                await fn()
                PASS.append(name)
                print(f"  ✓ {name}", flush=True)
            except Exception as e:
                FAIL.append((name, f"{e}"))
                print(f"  ✗ {name}: {e}", flush=True)
                traceback.print_exc(limit=3)
        return run
    return deco


@check("T1 run_forge.bat: PURE-ASCII + py -3 fallback python + %~dp0 gọi launch.py + pause khi lỗi (quy tắc research)")
async def t1():
    raw = (ROOT / "run_forge.bat").read_bytes()
    non_ascii = [b for b in raw if b > 127]
    assert not non_ascii, f"bat chứa {len(non_ascii)} byte >127 — cmd parse theo codepage sẽ vỡ"
    s = raw.decode("ascii")
    assert "where py" in s and "where python" in s, "phải thử py rồi python"
    assert "%~dp0scripts\\launch.py" in s, "phải gọi launch.py theo đường-dẫn-tương-đối-script"
    assert "pause" in s, "double-click lỗi phải pause để người dùng đọc"
    assert "Add python.exe to PATH" in s, "hướng dẫn cài Python phải nhắc tick PATH"
    assert "chcp" not in s.lower(), "không cần chcp — bat phải thuần ASCII"


@check("T2 run_forge.sh: bash -n sạch + exec launch.py với tham số truyền qua")
async def t2():
    sh = ROOT / "run_forge.sh"
    r = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    s = sh.read_text(encoding="utf-8")
    assert "exec python3 scripts/launch.py" in s or "exec python scripts/launch.py" in s
    assert '"$@"' in s, "phải truyền --no-browser… qua launch.py"


@check("T3 launch.py --check chạy THẬT, exit 0, in đủ thông tin môi trường")
async def t3():
    env = {**os.environ, "FORGE_PORT": "8123", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "launch.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=60, cwd=str(ROOT))
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    for needle in ("Python", ".venv", "node/npx", "git", "Cổng"):
        assert needle in r.stdout, (needle, r.stdout[:200])


@check("T4 USER_GUIDE: MỌI lệnh /slash trong guide phải tồn tại trong CODE (docs không được bịa)")
async def t4():
    guide = (ROOT / "docs/guides/USER_GUIDE.md").read_text(encoding="utf-8")
    guide = re.sub(r"https?://\S+", "", guide)          # URL chứa /không-phải-lệnh
    tokens = sorted({m.lower() for m in re.findall(r"(?<![\w.])/([a-z][a-z0-9_-]{1,20})\b", guide)})
    assert tokens, "guide phải nhắc lệnh slash"
    source = ""
    for pat in ("cli/*.py", "tui/*.py", "server/*.py", "engine/*.py"):
        for f in ROOT.glob(pat):
            source += f.read_text(encoding="utf-8", errors="ignore")
    missing = [f"/{tok}" for tok in tokens if f"/{tok}" not in source]
    assert not missing, f"Các lệnh KHÔNG có trong code (guide đang bịa?): {missing}"


@check("T5 USER_GUIDE: cấu hình đầy đủ — numbered steps, run_forge.bat, DEMO, sự cố, launch.py nhắc guide")
async def t5():
    g = (ROOT / "docs/guides/USER_GUIDE.md").read_text(encoding="utf-8")
    for sec in ("## 1.", "## 2.", "## 3.", "## 10.", "Sự cố", "run_forge.bat", "DEMO MODE",
                "openrouter.ai", "Allow once", "chcp 65001", "Bước 1.", "Bước 2."):
        assert sec in g, f"guide thiếu '{sec}'"
    lp = (ROOT / "scripts" / "launch.py").read_text(encoding="utf-8")
    assert "USER_GUIDE.md" in lp, "launcher phải dẫn người dùng tới guide"
    assert "USER_GUIDE.md" in (ROOT / "README.md").read_text(encoding="utf-8"), \
        "README phải link guide"


async def main():
    print(f"=== SUITE v0.31 Onboarding — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4, t5]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
