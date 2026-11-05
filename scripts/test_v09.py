# -*- coding: utf-8 -*-
"""Smoke suite v0.9: profiles · LSP diagnostics · MCP elicitation.

Chạy:  python scripts/test_v09.py
Cần:   pip install "python-lsp-server[pyflakes,pycodestyle]"  (cho test LSP)
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

TMP = Path(tempfile.mkdtemp(prefix="forge-v09-"))
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


# ────────────────────────────────────────────── T1 profiles ───────────────
@check("T1 profiles: overlay qua env, unknown bỏ qua, set_profile, active_profile")
async def t1():
    from engine import config
    config.ensure_dirs()
    base = config.load_config()
    config.save_config({"profiles": {
        "safe": {"model": "openrouter/free", "approval_mode": "guarded"},
        "yolo": {"model": "anthropic/claude-sonnet-5.5", "approval_mode": "auto"},
    }})
    # chưa chọn profile
    cfg = config.load_config()
    assert "active_profile" not in cfg or cfg.get("active_profile") is None
    assert config.get_model() != "openrouter/free" or cfg.get("model") == "openrouter/free"
    # chọn profile hợp lệ
    assert config.set_profile("safe") is True
    cfg = config.load_config()
    assert cfg["model"] == "openrouter/free" and cfg["approval_mode"] == "guarded", cfg
    assert cfg["active_profile"] == "safe"
    assert config.get_model() == "openrouter/free"
    # đè model trực tiếp vẫn thắng (profile chỉ merge phần còn thiếu? KHÔNG — profile đè)
    # profile không hợp lệ → vẫn dùng profile cũ cho tới khi đổi
    assert config.set_profile("không-tồn-tại") is False
    # gỡ profile
    assert config.set_profile("") is True
    cfg = config.load_config()
    assert "active_profile" not in cfg
    # cấu hình gốc trên đĩa không bị đè
    raw = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))
    assert "profiles" in raw and "active_profile" not in raw


# ────────────────────────────────────────────── T2 LSP ────────────────────
@check("T2 LSP: pylsp phát hiện undefined name + unused import; format_diags")
async def t2():
    import shutil
    if not shutil.which("pylsp"):
        raise AssertionError("pylsp chưa cài — pip install 'python-lsp-server[pyflakes,pycodestyle]'")
    from engine import lsp
    ws = TMP / "ws2"; ws.mkdir()
    bad = ws / "bad.py"
    bad.write_text("import os\n\nx = khong_bien_do\n", encoding="utf-8")
    diags = await lsp.diagnostics_for(ws, bad)
    msgs = " ".join(d["message"] for d in diags).lower()
    assert any(d["severity"] == "error" for d in diags), diags
    assert "khong_bien_do" in msgs, diags
    fmt = lsp.format_diags(diags)
    assert "LSP" in fmt and "⛔" in fmt, fmt
    # file sạch → 0
    bad.write_text("x = 1\n", encoding="utf-8")
    diags2 = await lsp.diagnostics_for(ws, bad)
    assert diags2 == [], diags2
    await lsp.shutdown_all()


@check("T2b LSP: lang_for/available_for đúng; file .txt bị bỏ qua")
async def t2b():
    from engine import lsp
    assert lsp.lang_for(Path("a.py")) == "python"
    assert lsp.lang_for(Path("a.tsx")) == "typescript"
    assert lsp.lang_for(Path("a.txt")) is None
    assert lsp.available_for(Path("a.py")) in (True, False)  # tùy máy có pylsp
    assert lsp.available_for(Path("ghi-chu.txt")) is False


# ────────────────────────────────────────────── T3 tool integration ───────
@check("T3 execute_tool write_file .py lỗi → output có LSP + result.diagnostics")
async def t3():
    import shutil
    from engine.tools import execute_tool
    ws = TMP / "ws3"; ws.mkdir()
    r = await execute_tool("write_file", {"path": "err.py", "content": "y = day_la_loi\n"}, ws)
    if shutil.which("pylsp"):
        assert "LSP" in r["output"], r["output"][:300]
        assert r.get("diagnostics"), r.keys()
        assert any(d["severity"] == "error" for d in r["diagnostics"])
    else:
        assert r["ok"]  # không có pylsp → không đếm gì nhưng vẫn ok
    from engine import lsp as _l
    await _l.shutdown_all()


# ────────────────────────────────────────────── T4 elicitation registry ───
@check("T4 elicitation: accept lọc field lạ, thiếu required → cancel, decline, secret auto-decline")
async def t4():
    from engine import elicitations as el
    schema = {"type": "object",
              "properties": {"name": {"type": "string"}, "age": {"type": "number"}},
              "required": ["name"]}
    eid = el.create("srv", "cho xin tên", schema)
    assert el.resolve(eid, "accept", {"name": "Lan", "hack": "x"})
    # tạo lại để test missing required
    eid2 = el.create("srv", "cho xin tên", schema)
    # resolve trước khi có future resolve → resolve returns True; missing required → cancel result
    fut_entry = el.PENDING[eid2]
    assert el.resolve(eid2, "accept", {"age": 20})  # thiếu name
    # đọc kết quả từ future
    res = await asyncio.wait_for(fut_entry["future"], 1)
    assert res["action"] == "cancel" and res.get("_missing") == ["name"], res
    # secret auto-decline
    eid3 = el.create("srv", "nhập api key", {"type": "object",
                                             "properties": {"api_key": {"type": "string"}}})
    res3 = await asyncio.wait_for(el.PENDING[eid3]["future"], 1)
    assert res3["action"] == "decline", res3
    # snapshot chỉ còn pending
    eid4 = el.create("srv", "câu hỏi", schema)
    snap = el.snapshot()
    assert any(s["id"] == eid4 for s in snap)
    el.resolve(eid4, "decline")
    assert not any(s["id"] == eid4 for s in el.snapshot())


# ────────────────────────────────────────────── T5 MCP e2e elicitation ────
@check("T5 MCP e2e: tools/call → elicitation pending → accept/decline → tool result")
async def t5():
    from engine import config
    config.ensure_dirs()
    # v0.17: tool MCP phải allowlist (hoặc được duyệt) — test này trọng tâm elicitation
    # nên pre-allow toàn bộ tool của server demo
    (config.DATA_DIR / "mcp.json").write_text(json.dumps({"servers": [
        {"name": "demo", "command": sys.executable,
         "args": [str((ROOT / "scripts" / "demo_mcp_server.py").resolve())], "env": {},
          "allowed_tools": "*"}]}),
        encoding="utf-8")
    from engine.mcp import manager as mm
    specs, routing = await mm.get_tool_specs()
    ns = [s["function"]["name"] for s in specs if "ask_preference" in s["function"]["name"]][0]
    from engine import elicitations as el
    task = asyncio.create_task(mm.call_namespaced(routing, ns, {"topic": "database"}))
    eid = None
    for _ in range(80):
        await asyncio.sleep(0.1)
        pend = el.snapshot()
        if pend:
            eid = pend[0]["id"]
            break
    assert eid, "không thấy elicitation pending"
    assert el.resolve(eid, "accept", {"choice": "PostgreSQL", "urgent": True, "lạ": 1})
    res = await task
    assert "PostgreSQL" in res["output"] and "lạ" not in res["output"], res
    # decline
    task2 = asyncio.create_task(mm.call_namespaced(routing, ns, {"topic": "cache"}))
    eid2 = None
    for _ in range(80):
        await asyncio.sleep(0.1)
        pend = el.snapshot()
        if pend:
            eid2 = pend[0]["id"]
            break
    el.resolve(eid2, "decline")
    res2 = await task2
    assert "TỪ CHỐI" in res2["output"], res2


# ────────────────────────────────────────────── T6 agent loop event ───────
FAKE_STATE = {"n": 0}


async def _fake_llm(messages, tools=None, model=None, api_key=None, temperature=0.3):
    FAKE_STATE["n"] += 1
    if FAKE_STATE["n"] == 1:
        ns = [s["function"]["name"] for s in tools or [] if "ask_preference" in s["function"]["name"]][0]
        import json as _j
        yield {"type": "tool_calls", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": ns, "arguments": _j.dumps({"topic": "orm"})}}]}
        yield {"type": "finish", "reason": "tool_calls"}
    else:
        yield {"type": "delta", "text": "đã hỏi xong"}
        yield {"type": "finish", "reason": "stop"}


@check("T6 agent.send: MCP tool kích hoạt elicitation_request event (poll loop)")
async def t6():
    import engine.llm as llm
    from engine.agent import Agent
    from engine import elicitations as el
    store = make_store()
    sid = store.create().id
    orig = llm.stream_chat
    llm.stream_chat = _fake_llm
    FAKE_STATE["n"] = 0
    got_event = None

    async def pump(agent):
        nonlocal got_event
        async for ev in agent.send("hỏi tôi về orm"):
            if ev["type"] == "elicitation_request":
                got_event = ev
                # resolve sau 0.3s (mô phỏng người dùng bấm)
                await asyncio.sleep(0.3)
                el.resolve(ev["id"], "accept", {"choice": "SQLAlchemy"})
            yield ev

    try:
        agent = Agent(store, sid)
        agent._mcp_hook = True  # không có tác dụng, chỉ ghi chú
        # buộc agent thấy MCP tools: mcp.json đã có từ T5
        events = []
        async def run():
            nonlocal events
            async for ev in pump(agent):
                events.append(ev)
        await asyncio.wait_for(run(), 60)
    finally:
        llm.stream_chat = orig
    assert got_event, f"không nhận elicitation_request; types={[e['type'] for e in events][:20]}"
    assert got_event["server"] == "demo"
    outs = [e for e in events if e["type"] == "tool_result"]
    assert outs and "SQLAlchemy" in outs[0]["output"], outs[0]["output"] if outs else None


def make_store():
    from engine.session import SessionStore
    return SessionStore()


# ────────────────────────────────────────────── T7 server ─────────────────
@check("T7 server: /api/elicitations + /api/elicitation/{eid} + health profiles/lsp")
async def t7():
    from fastapi.testclient import TestClient
    from server.main import app
    from engine import elicitations as el
    with TestClient(app) as client:
        h = client.get("/api/settings").json()
        assert "profiles" in h and "lsp_available" in h and "active_profile" in h, h.keys()
        eid = el.create("srv-test", "câu hỏi test",
                        {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]})
        pend = client.get("/api/elicitations").json()["pending"]
        assert any(p["id"] == eid for p in pend), pend
        r = client.post(f"/api/elicitation/{eid}", json={"action": "accept", "content": {"q": "ok"}})
        assert r.status_code == 200 and r.json()["ok"], r.text
        r2 = client.post(f"/api/elicitation/{eid}", json={"action": "accept"})
        assert r2.status_code == 404  # đã xử lý
        assert not any(p["id"] == eid for p in client.get("/api/elicitations").json()["pending"])


async def main():
    print(f"=== SMOKE v0.9 — data tạm: {TMP} ===")
    for fn in [t1, t2, t2b, t3, t4, t5, t6, t7]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
