# -*- coding: utf-8 -*-
"""Suite v0.27 "MCP 6 gói" — kiểm chứng phủ đủ các MCP người dùng yêu cầu:
Playwright · File System · Postgres · GitHub · Context7 · Sequential Thinking
+ $VAR expansion khi spawn stdio + spawn THẬT sequential-thinking (skip nếu thiếu npx).

Chạy:  python scripts/test_v028.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v028-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("FORGE_PROFILE", None)

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


@check("T1 phủ đủ 6 MCP yêu cầu: playwright/filesystem/postgres/context7/sequential-thinking "
       "có preset riêng; GitHub = preset 'github' (remote chính thức api.githubcopilot.com, PAT)")
async def t1():
    from engine.connectors import PRESETS, AUTH_LABEL
    # 6 gói người dùng hỏi — ánh xạ:
    covered = {
        "MCP Playwright": "playwright",
        "File system MCP": "filesystem",
        "Postgres MCP": "postgres",
        "Github MCP": "github",        # remote chính thức (stdio server-github đã deprecated)
        "Context7 MCP": "context7",
        "Sequential Thinking MCP": "sequential-thinking",
    }
    for human, pid in covered.items():
        assert pid in PRESETS, f"{human}: thiếu preset '{pid}'"
        p = PRESETS[pid]
        assert p["label"] and p["auth"] in AUTH_LABEL, (pid, p)
    # chi tiết then chốt
    assert PRESETS["playwright"]["transport"] == "stdio"
    assert PRESETS["filesystem"]["auth"] == "env" and any(
        "$FORGE_FS_DIR" in str(a) for a in PRESETS["filesystem"]["args"])
    assert PRESETS["postgres"]["auth"] == "env" and any(
        "$DATABASE_URL" in str(a) for a in PRESETS["postgres"]["args"])
    gh = PRESETS["github"]
    assert gh["transport"] == "http" and gh["url"] == "https://api.githubcopilot.com/mcp/"
    assert gh["auth"] == "pat" and gh["headers"]["Authorization"] == "Bearer {token}"
    assert PRESETS["context7"]["auth"] == "none" and PRESETS["context7"]["url"].startswith("https://")
    assert PRESETS["sequential-thinking"]["auth"] == "none"
    # preset stdio github deprecated KHÔNG được quay lại
    assert "github-mcp" not in PRESETS


@check("T2 $VAR expansion: thiếu biến → chuỗi rỗng (lỗi server rõ ràng) · có biến → resolve · nhúng → expandvars")
async def t2():
    from engine.mcp import manager as mm
    os.environ["FORGE_T2_DIR"] = str(TMP / "fsdir")
    try:
        out = mm._expand_args(["-y", "pkg", "$FORGE_T2_DIR"])
        assert out == ["-y", "pkg", str(TMP / "fsdir")], out
        assert mm._expand_args(["$KHONG_TON_TAI"]) == [""]
        mixed = mm._expand_args([f"thư-mục-là-$FORGE_T2_DIR/x"])
        assert mixed == [f"thư-mục-là-{TMP / 'fsdir'}/x"], mixed
    finally:
        os.environ.pop("FORGE_T2_DIR", None)


@check("T3 add 4 preset env/none mới: lưu template $VAR nguyên bản (resolve lúc spawn) · msg có cảnh báo env · remove sạch")
async def t3():
    from engine import connectors as fc
    from engine.mcp import load_servers
    for pid in ("postgres", "filesystem", "sequential-thinking"):
        msg = fc.add(pid)
        assert "✅" in msg, (pid, msg)
        cfg = [c for c in load_servers() if c.get("preset") == pid][0]
        if pid in ("postgres", "filesystem"):
            assert any(str(a).startswith("$") for a in cfg["args"]), cfg["args"]
            assert "⚠" in msg, f"{pid}: phải cảnh báo đặt env trước — {msg}"
        else:
            assert "⚠" not in msg or "env" not in msg.lower()
        # remove theo tên hiển thị trong cfg
        assert "🗑" in fc.remove(cfg["name"])
    assert not load_servers()


@check("T4 spawn THẬT sequential-thinking qua npx → tool sequentialthinking vào specs (skip nếu máy thiếu npx)")
async def t4():
    if shutil.which("npx") is None:
        print("    (skip — không có npx trên máy)")
        return
    from engine import connectors as fc
    from engine.mcp import manager as mm
    assert "✅" in fc.add("sequential-thinking")
    specs, routing = await mm.get_tool_specs()
    names = [sp["function"]["name"] for sp in specs]
    assert any("sequentialthinking" in n for n in names), names
    assert list(routing.keys()) == names, "routing phải phủ hết specs"
    fc.remove("Sequential Thinking")
    from engine.mcp import load_servers
    assert not [c for c in load_servers() if c.get("preset") == "sequential-thinking"]


@check("T5 postgres THIẾU DATABASE_URL: status error với thông điệp rõ (không crash, không literal $VAR)")
async def t5():
    if shutil.which("npx") is None:
        print("    (skip — không có npx)")
        return
    os.environ.pop("DATABASE_URL", None)
    from engine import connectors as fc
    from engine.mcp import manager as mm
    assert "✅" in fc.add("postgres")
    try:
        await mm.get_tool_specs()
    except Exception:
        pass  # start từng server bắt lỗi riêng — không để vỡ turn
    st = {s["name"]: s for s in mm.status()}
    g = next(v for k, v in st.items() if "postgres" in k.lower())
    assert g["status"] == "error", g
    # status hiển thị TEMPLATE $DATABASE_URL nguyên bản (đúng thiết kế — expansion lúc spawn);
    # điều quan trọng: error message rõ ràng, không phải chữ $VAR literal
    assert g["error"] and "$DATABASE_URL" not in g["error"], g
    fc.remove(g["name"])


async def main():
    print(f"=== SUITE v0.27 MCP 6 gói — data tạm: {TMP} ===")
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
