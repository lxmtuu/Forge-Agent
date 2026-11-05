# -*- coding: utf-8 -*-
"""Suite v0.29 "MCP mở rộng theo research" — 7 preset mới:
Stripe · Atlassian · Vercel · Supabase (remote chính thức) · Memory · Fetch · Brave Search
+ spawn THẬT memory (npx) / fetch (uvx, skip nếu máy thiếu uv).

Chạy:  python scripts/test_v029.py
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

TMP = Path(tempfile.mkdtemp(prefix="forge-v029-"))
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


@check("T1 7 preset mới theo research: endpoint/env ĐÚNG nguồn chính thức · tổng 18 preset")
async def t1():
    from engine.connectors import PRESETS, AUTH_LABEL
    st = PRESETS["stripe"]
    assert st["transport"] == "http" and st["url"] == "https://mcp.stripe.com"
    assert st["auth"] == "api-key" and st["headers"]["Authorization"] == "Bearer {token}"
    at = PRESETS["atlassian"]
    assert at["url"] == "https://mcp.atlassian.com/v2/mcp" and at["auth"] == "oauth-pending"
    ve = PRESETS["vercel"]
    assert ve["url"] == "https://mcp.vercel.com" and ve["auth"] == "oauth-pending"
    sb = PRESETS["supabase"]
    assert sb["url"].startswith("https://mcp.supabase.com/mcp") and "read_only=true" in sb["url"]
    me = PRESETS["memory"]
    assert me["transport"] == "stdio" and me["command"] == "npx"
    assert "@modelcontextprotocol/server-memory" in me["args"]
    fe = PRESETS["fetch"]
    assert fe["command"] == "uvx" and fe["args"] == ["mcp-server-fetch"]
    br = PRESETS["brave-search"]
    assert "@brave/brave-search-mcp-server" in br["args"] and br["auth"] == "env"
    # bản stdio brave ARCHIVED không được quay lại
    assert "@modelcontextprotocol/server-brave-search" not in str(br["args"])
    assert len(PRESETS) == 18, sorted(PRESETS)
    for k, pv in PRESETS.items():
        assert pv["auth"] in AUTH_LABEL, (k, pv["auth"])
        assert pv["label"] and pv["auth_hint"]


@check("T2 add 7 preset: msg ✅ đúng hướng dẫn theo loại auth (api-key→auth cmd · env→⚠ · oauth-pending→hub) · remove sạch")
async def t2():
    from engine import connectors as fc
    from engine.mcp import load_servers
    # stripe (api-key)
    m = fc.add("stripe")
    assert "✅" in m and "/connectors auth Stripe" in m, m
    # brave-search (env)
    m = fc.add("brave-search")
    assert "✅" in m and "⚠" in m and "BRAVE_API_KEY" in m, m
    # 4 oauth-pending/hub — chỉ dẫn hub
    for pid in ("atlassian", "vercel", "supabase"):
        m = fc.add(pid)
        assert "✅" in m, (pid, m)
    # memory + fetch (none)
    for pid in ("memory", "fetch"):
        m = fc.add(pid)
        assert "✅" in m and "⚠" not in m, (pid, m)
    cfgs = load_servers()
    assert len(cfgs) == 7, [c["name"] for c in cfgs]
    assert {c["preset"] for c in cfgs} == {"stripe", "brave-search", "atlassian",
                                           "vercel", "supabase", "memory", "fetch"}
    # remote stripe giữ template {token} trước auth
    stc = next(c for c in cfgs if c["preset"] == "stripe")
    assert stc["headers"]["Authorization"] == "Bearer {token}"
    # remove hết theo tên hiển thị
    for c in list(cfgs):
        assert "🗑" in fc.remove(c["name"]), c["name"]
    assert not load_servers()


@check("T4 stripe auth roundtrip: Bearer thay {token} · token THẬT không lộ trong listing (masked)")
async def t4():
    from engine import connectors as fc
    from engine.mcp import load_servers
    assert "✅" in fc.add("stripe")
    tok = "rk_live_ABCDEF1234567890xyz"
    m = fc.auth("Stripe", tok)
    assert "🔑" in m and tok not in m, m
    cfg = next(c for c in load_servers() if c["preset"] == "stripe")
    assert cfg["headers"]["Authorization"] == f"Bearer {tok}", cfg["headers"]
    ls = fc.status_listing()
    assert tok not in ls, "TOKEN LỘ TRONG LISTING!"
    assert fc.mask_token(tok) in ls
    fc.remove("Stripe")


@check("T3 spawn THẬT memory qua npx → tool create_entities… vào specs (skip nếu thiếu npx)")
async def t3():
    if shutil.which("npx") is None:
        print("    (skip — không có npx)")
        return
    from engine import connectors as fc
    from engine.mcp import manager as mm
    assert "✅" in fc.add("memory")
    specs, routing = await mm.get_tool_specs()
    names = [sp["function"]["name"] for sp in specs]
    assert any("Memory" in n and "create_entities" in n for n in names), names[:5]
    assert any("search_nodes" in n for n in names), "phải có search_nodes"
    fc.remove("Memory")


@check("T5 spawn THẬT fetch qua uvx → tool fetch vào specs (skip nếu máy thiếu uvx)")
async def t5():
    if shutil.which("uvx") is None:
        print("    (skip — không có uvx; cài uv để dùng preset fetch)")
        return
    from engine import connectors as fc
    from engine.mcp import manager as mm
    assert "✅" in fc.add("fetch")
    specs, _ = await mm.get_tool_specs()
    names = [sp["function"]["name"] for sp in specs]
    assert any("Fetch" in n and "fetch" in n.lower() for n in names), names[:5]
    fc.remove("Fetch")


async def main():
    print(f"=== SUITE v0.29 MCP mở rộng — data tạm: {TMP} ===")
    for fn in [t1, t2, t4, t3, t5]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
