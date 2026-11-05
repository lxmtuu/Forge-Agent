# -*- coding: utf-8 -*-
"""Smoke suite v0.17 "Connectors":
C1 presets (endpoint chính thức) · C2 /connectors add/auth/allow/deny/remove ·
C3 secrets + MASK (token không được lộ) · C4 approval tool MCP (E2E qua agent).

Chạy:  python scripts/test_v017.py
"""
import asyncio
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import _test_auth
_test_auth.install()

TMP = Path(tempfile.mkdtemp(prefix="forge-v017-"))
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
                print(f"  ✓ {name}")
            except Exception as e:
                FAIL.append((name, f"{e}"))
                print(f"  ✗ {name}: {e}")
                traceback.print_exc(limit=3)
        return run
    return deco


# ─────────────────────────── T1 presets ────────────────────────────────────
@check("T1 presets: endpoint chính thức đúng, auth type hợp lệ")
async def t1():
    from engine.connectors import PRESETS, AUTH_LABEL
    must = {"github", "linear", "postgres", "notion", "composio-hub", "playwright",
            "context7", "figma-desktop", "filesystem", "sequential-thinking"}
    assert must <= set(PRESETS), set(PRESETS)
    gh = PRESETS["github"]
    assert gh["url"] == "https://api.githubcopilot.com/mcp/" and gh["auth"] == "pat", gh
    assert gh["headers"]["Authorization"] == "Bearer {token}"
    ln = PRESETS["linear"]
    assert ln["url"] == "https://mcp.linear.app/mcp" and ln["auth"] == "api-key"
    pg = PRESETS["postgres"]
    assert pg["transport"] == "stdio" and any("$DATABASE_URL" in str(a) for a in pg["args"])
    assert pg["auth"] == "env"
    pw = PRESETS["playwright"]
    assert pw["transport"] == "stdio" and pw["command"] == "npx"
    st = PRESETS["sequential-thinking"]
    assert st["auth"] == "none" and st["transport"] == "stdio"
    for k, p in PRESETS.items():
        assert p["auth"] in AUTH_LABEL, (k, p["auth"])
        assert p["label"] and p["auth_hint"]


# ─────────────────────────── T2 add/auth/remove + MASK ─────────────────────
@check("T2 roundtrip: add → auth (mask, token THẬT không lộ trong listing) → remove")
async def t2():
    from engine import connectors as fc
    from engine.mcp import load_servers
    assert "❌" in fc.add("khong-ton-tai")
    # hub cần URL riêng
    bad = fc.add("composio-hub")
    assert "❌" in bad and "URL" in bad, bad
    ok = fc.add("github")
    assert "✅" in ok and "/connectors auth" in ok, ok
    cfgs = load_servers()
    assert any(c.get("preset") == "github" for c in cfgs), cfgs
    gh = [c for c in cfgs if c.get("preset") == "github"][0]
    assert gh["url"] == "https://api.githubcopilot.com/mcp/"
    # auth → headers thay {token}, secrets lưu bản mask
    tok = "ghp_ABCDEF1234567890xyz"
    ok2 = fc.auth("GitHub", tok)  # tên không phân biệt hoa/thường qua sanitize
    assert "🔑" in ok2 and tok not in ok2, ok2  # token THẬT không được in ra
    assert fc.mask_token(tok) in ok2, ok2
    gh2 = [c for c in load_servers() if c.get("preset") == "github"][0]
    assert gh2["headers"]["Authorization"] == f"Bearer {tok}", gh2["headers"]
    # listing che token
    ls = fc.status_listing()
    assert tok not in ls, "TOKEN LỘ TRONG LISTING!"
    assert fc.mask_token(tok) in ls and "GitHub" in ls, ls[:400]
    # auth rỗng / connector lạ
    assert "❌" in fc.auth("khong-co", "x")
    # postgres preset: add lưu template $DATABASE_URL (resolve lúc spawn), msg cảnh báo env
    ok3 = fc.add("postgres")
    assert "❌" not in ok3 and "DATABASE_URL" in ok3, ok3
    pgc = [c for c in load_servers() if c.get("preset") == "postgres"][0]
    assert any("$DATABASE_URL" in str(a) for a in pgc["args"]), pgc["args"]
    assert "⚠" in ok3, "phải cảnh báo đặt biến môi trường trước"
    # remove
    ok4 = fc.remove("github")
    assert "🗑" in ok4
    assert not any(c.get("preset") == "github" for c in load_servers())
    assert "❌" in fc.remove("github")


# ─────────────────────────── T3 allowlist ──────────────────────────────────
@check("T3 allowlist: mặc định PHẢI duyệt; allow per-tool/*; deny rút phép")
async def t3():
    from engine import connectors as fc
    fc.add("linear")
    assert fc.tool_allowed("Linear", "create_issue") is False, "mặc định phải duyệt!"
    fc.allow("linear", "create_issue")
    assert fc.tool_allowed("linear", "create_issue") is True
    assert fc.tool_allowed("linear", "delete_issue") is False
    fc.allow("linear", "*")
    assert fc.tool_allowed("linear", "bat-ky-tool-gi") is True
    fc.deny("linear", "*")
    assert fc.tool_allowed("linear", "create_issue") is False
    fc.allow("linear", "search_issues")
    fc.deny("linear", "search_issues")
    assert fc.tool_allowed("linear", "search_issues") is False
    assert fc.allow("khong-co", "*").startswith("❌")


# ─────────────────────────── T4 approval gate qua agent ────────────────────
@check("T4 agent: tool MCP chưa allowlist → approval_request; deny chặn; approve_always mở khóa + allowlist")
async def t4():
    import engine.agent as ag_mod
    from engine.agent import Agent
    from engine.session import SessionStore
    from engine import approvals as ap
    import engine.llm as llm

    store = SessionStore()
    sid = store.create().id
    from engine import connectors as _fc0
    _fc0._replace_cfg({"name": "FakeHub", "preset": "test", "enabled": True,
                       "url": "http://localhost:1/mcp", "allowed_tools": []})

    class FakeSrv:
        name = "FakeHub"

    called = {"n": 0}

    async def fake_specs():
        spec = {"type": "function", "function": {
            "name": "mcp_FakeHub_echo", "description": "[MCP:FakeHub] echo",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}}
        return [spec], {"mcp_FakeHub_echo": (FakeSrv(), "echo")}

    async def fake_call(routing, ns, args):
        called["n"] += 1
        return {"ok": True, "output": "FAKE-ECHO-OK"}

    class FakeMgr:
        get_tool_specs = staticmethod(fake_specs)
        call_namespaced = staticmethod(fake_call)

    orig_mgr = ag_mod.mcp_manager
    ag_mod.mcp_manager = FakeMgr()

    state = {"n": 0}

    async def fake_llm(messages, tools=None, model=None, api_key=None, temperature=0.3):
        state["n"] += 1
        yield {"type": "tool_calls", "tool_calls": [{
            "id": f"c{state['n']}", "type": "function",
            "function": {"name": "mcp_FakeHub_echo",
                         "arguments": json.dumps({"text": "hi"})}}]}
        yield {"type": "finish", "reason": "tool_calls"}

    orig = llm.stream_chat

    async def drain_and_resolve(decision: str) -> list[dict]:
        evs: list[dict] = []
        agent = Agent(store, sid)
        gen = agent.send("gọi echo qua FakeHub")
        orig_llm = llm.stream_chat
        turn_state = {"llm": 0}

        async def fake_llm_once(messages, tools=None, model=None, api_key=None, temperature=0.3):
            turn_state["llm"] += 1
            if turn_state["llm"] == 1:
                yield {"type": "tool_calls", "tool_calls": [{
                    "id": f"c{turn_state['llm']}", "type": "function",
                    "function": {"name": "mcp_FakeHub_echo",
                                 "arguments": json.dumps({"text": "hi"})}}]}
                yield {"type": "finish", "reason": "tool_calls"}
            else:
                yield {"type": "delta", "text": "xong"}
                yield {"type": "finish", "reason": "stop"}

        llm.stream_chat = fake_llm_once
        try:
            async for ev in gen:
                evs.append(ev)
                if ev["type"] == "approval_request":
                    await asyncio.sleep(0.05)
                    assert ap.resolve(ev["id"], decision), "resolve thất bại"
        finally:
            llm.stream_chat = orig_llm
        return evs

    try:
        # Lượt 1: DENY → tool không chạy
        evs1 = await drain_and_resolve("deny")
        req = [e for e in evs1 if e["type"] == "approval_request"]
        assert req, "không có approval_request!"
        assert "FakeHub" in req[0]["command"] and "echo" in req[0]["command"]
        tr1 = [e for e in evs1 if e["type"] == "tool_result"]
        assert tr1 and not tr1[0]["ok"] and "DENIED" in tr1[0]["output"], tr1
        assert called["n"] == 0, "tool vẫn bị gọi dù deny!"
        # Lượt 2: approve_always → chạy + lưu allowlist
        evs2 = await drain_and_resolve("approve_always")
        tr2 = [e for e in evs2 if e["type"] == "tool_result"]
        assert tr2 and tr2[0]["ok"] and "FAKE-ECHO-OK" in tr2[0]["output"], tr2
        assert called["n"] == 1
        from engine import connectors as fc
        assert fc.tool_allowed("FakeHub", "echo"), "approve_always phải lưu allowlist"
        # Lượt 3: đã allowlist → KHÔNG còn approval_request
        evs3 = await drain_and_resolve("deny")
        assert not [e for e in evs3 if e["type"] == "approval_request"], "vẫn hỏi dù đã allow!"
        assert called["n"] == 2
        fc.deny("FakeHub", "*")  # dọn allowlist
        _fc0.remove("FakeHub")
    finally:
        ag_mod.mcp_manager = orig_mgr
        llm.stream_chat = orig


# ─────────────────────────── T5 server /connectors ─────────────────────────
@check("T5 server: /connectors listing + add + auth qua chat (token không echo)")
async def t5():
    from fastapi.testclient import TestClient
    from server.main import app
    tok = "lin_api_SECRET9999zz"
    with TestClient(app) as client:
        sid = client.post("/api/sessions", json={"title": "t5"}).json()["session"]["id"]
        r = client.post(f"/api/sessions/{sid}/chat",
                        json={"text": "/connectors", "mode": "direct"})
        assert "Presets sẵn sàng" in r.text and "github" in r.text, r.text[-400:]
        r2 = client.post(f"/api/sessions/{sid}/chat",
                         json={"text": "/connectors add linear", "mode": "direct"})
        assert "✅" in r2.text and "/connectors auth" in r2.text, r2.text[-300:]
        r3 = client.post(f"/api/sessions/{sid}/chat",
                         json={"text": f"/connectors auth linear {tok}", "mode": "direct"})
        assert "🔑" in r3.text, "auth không thành công: " + r3.text[-200:]
        assert tok not in r3.text, "token bị echo trong SSE!"
        r4 = client.post(f"/api/sessions/{sid}/chat",
                         json={"text": "/connectors", "mode": "direct"})
        assert tok not in r4.text, "listing lộ token!"
        assert "Linear" in r4.text, "thiếu connector Linear trong listing"
        client.post(f"/api/sessions/{sid}/chat",
                    json={"text": "/connectors remove linear", "mode": "direct"})


# ─────────────────────────── T6 doctor ─────────────────────────────────────
@check("T6 doctor: có mục Connectors, summary vẫn hợp lệ")
async def t6():
    from engine.diagnostics import doctor
    from engine.session import SessionStore
    store = SessionStore()
    rep = await doctor(store)
    names = {c["name"] for c in rep["checks"]}
    assert "Connectors" in names and "MCP servers" in names, names
    assert "/" in rep["summary"]


async def main():
    print(f"=== SMOKE v0.17 Connectors — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4, t5, t6]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
