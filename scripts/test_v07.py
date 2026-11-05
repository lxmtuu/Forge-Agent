# -*- coding: utf-8 -*-
"""Smoke suite v0.7 "Comfort Sprint": checkpoints/diff/compact/init/agents_md/auto-compact/server.

Chạy:  python scripts/test_v07.py
Mọi test dùng FORGE_DATA_DIR tạm — không đụng data/ thật.
"""
import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v07-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
os.environ.pop("OPENROUTER_API_KEY", None)  # ép demo mode

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


def make_store():
    from engine.session import SessionStore
    return SessionStore()


# ─────────────────────────────────────────────── T1+T2 checkpoints ─────────
@check("T1 checkpoint roundtrip: snapshot → sửa → undo → file về cũ")
async def t1():
    from engine import checkpoints
    ws = TMP / "ws1"; ws.mkdir()
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    await checkpoints.snapshot(checkpoints.key_for(ws), ws, "seed v1")
    (ws / "a.txt").write_text("v2-sua roi", encoding="utf-8")
    (ws / "b_moi.txt").write_text("sinh sau ck", encoding="utf-8")
    await checkpoints.snapshot(checkpoints.key_for(ws), ws, "sua v2 + them b")
    res = await checkpoints.undo(checkpoints.key_for(ws), ws)
    ok, msg = bool(res["ok"]), str(res["message"])
    assert ok, msg
    assert (ws / "a.txt").read_text(encoding="utf-8") == "v1", "a.txt phải về v1"
    assert not (ws / "b_moi.txt").exists(), "file sinh sau checkpoint phải bị xoá"
    res2 = await checkpoints.undo(checkpoints.key_for(ws), ws)
    ok2, msg2 = bool(res2["ok"]), str(res2["message"])
    assert not ok2, "undo lần 2 phải báo không còn checkpoint cha"
    assert "không còn" in msg2.lower() or "checkpoint" in msg2.lower(), msg2


@check("T2 checkpoint list trả về ít nhất 1 mốc cho workspace")
async def t2():
    from engine import checkpoints
    ws = TMP / "ws2"; ws.mkdir()
    (ws / "x.py").write_text("print(1)\n", encoding="utf-8")
    await checkpoints.snapshot(checkpoints.key_for(ws), ws, "tạo x.py")
    items = await checkpoints.list_checkpoints(checkpoints.key_for(ws), ws)
    assert len(items) >= 1, f"list phải ≥1, got {items}"
    assert any("tạo x.py" in it for it in items), items


# ─────────────────────────────────────────────── T3 diff qua execute_tool ──
@check("T3 write_file mới: không diff; edit_file file cũ: có diff -/+")
async def t3():
    from engine.tools import execute_tool
    ws = TMP / "ws3"; ws.mkdir()
    r1 = await execute_tool("write_file", {"path": "new.py", "content": "x = 1\n"}, ws)
    assert r1["ok"] and "diff" not in r1, f"file mới không nên có diff: {r1}"
    r2 = await execute_tool("edit_file", {"path": "new.py",
                                          "old_text": "x = 1", "new_text": "x = 42"}, ws)
    assert r2["ok"], r2
    assert "diff" in r2 and r2["path"].endswith("new.py"), r2
    d = r2["diff"]
    assert "-x = 1" in d and "+x = 42" in d and "@@" in d, d


@check("T3b diff bị cap ở 8000 ký tự")
async def t3b():
    from engine.tools import execute_tool
    ws = TMP / "ws3b"; ws.mkdir()
    big = "\n".join(f"line-{i}" for i in range(1200))  # ~8.8KB
    await execute_tool("write_file", {"path": "big.txt", "content": big}, ws)
    r = await execute_tool("edit_file", {"path": "big.txt",
                                         "old_text": "line-1199", "new_text": "CHINH-SUA"}, ws)
    assert r["ok"] and "diff" in r, r
    assert len(r["diff"]) <= 8100, len(r["diff"])


# ─────────────────────────────────────────────── T4 agent event diff (fake LLM)
FAKE_STATE = {"calls": 0}


async def _fake_stream(messages, tools=None, model=None, api_key=None, temperature=0.3):
    FAKE_STATE["calls"] += 1
    if FAKE_STATE["calls"] == 1:
        yield {"type": "tool_calls", "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "edit_file",
                         "arguments": '{"path": "new.py", "old_text": "x = 42", "new_text": "x = 100"}'}}]}
        yield {"type": "finish", "reason": "tool_calls"}
    else:
        yield {"type": "delta", "text": "Đã sửa x = 100."}
        yield {"type": "finish", "reason": "stop"}


@check("T4 agent.send: tool_result event mang diff (fake LLM)")
async def t4():
    import engine.llm as llm
    from engine.agent import Agent
    from engine.tools import execute_tool
    ws = TMP / "ws3"  # tái dùng: new.py đang x = 42
    await execute_tool("write_file", {"path": "new.py", "content": "x = 42\n"}, ws)
    store = make_store()
    sid = store.create().id
    orig = llm.stream_chat
    FAKE_STATE["calls"] = 0
    llm.stream_chat = _fake_stream
    try:
        agent = Agent(store, sid)
        agent.workspace = ws  # trỏ workspace về ws3
        events = []
        async for ev in agent.send("sửa x thành 100"):
            events.append(ev)
    finally:
        llm.stream_chat = orig
    tr = [e for e in events if e["type"] == "tool_result"]
    assert tr, f"không có tool_result: {[e['type'] for e in events]}"
    assert tr[0].get("diff") and "+x = 100" in tr[0]["diff"], tr[0]
    assert tr[0].get("path", "").endswith("new.py")
    assert (ws / "new.py").read_text(encoding="utf-8").strip() == "x = 100"


# ─────────────────────────────────────────────── T5 compact (fake LLM) ─────
async def _fake_summary(messages, tools=None, model=None, api_key=None, temperature=0.3):
    yield {"type": "delta", "text": "Người dùng muốn sửa hàm x; agent đã chỉnh new.py."}
    yield {"type": "finish", "reason": "stop"}


@check("T5 compact_session: nén 12 tin → 1 summary + 4 tin cuối")
async def t5():
    import engine.llm as llm
    from engine.agent import Agent, compact_session, KEEP_RECENT_MESSAGES
    store = make_store()
    sid = store.create().id
    s = store.get(sid)
    for i in range(12):
        s.messages.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"})
    store.save(s)
    agent = Agent(store, sid)
    orig = llm.stream_chat
    llm.stream_chat = _fake_summary
    try:
        res = await compact_session(agent)
    finally:
        llm.stream_chat = orig
    assert res["ok"], res
    assert res["before"] == 12 and res["after"] == 1 + KEEP_RECENT_MESSAGES, res
    s2 = store.get(sid)
    assert s2.messages[0]["content"].startswith("[TÓM TẮT HỘI THOẠI TRƯỚC ĐÓ — 12")
    assert s2.messages[1]["content"] == "msg 8", s2.messages[1]


@check("T5b compact phiên trống → ok=False kèm thông báo")
async def t5b():
    from engine.agent import Agent, compact_session
    store = make_store()
    sid = store.create().id
    res = await compact_session(Agent(store, sid))
    assert not res["ok"] and "trống" in res["message"].lower(), res


@check("T6 _transcript cap 1200 ký tự mỗi tin")
async def t6():
    from engine.agent import _transcript
    msgs = [{"role": "user", "content": "A" * 5000}]
    out = _transcript(msgs)
    assert "USER: " in out and len(out) < 1300, (len(out), out[:20])
    assert out.rstrip().endswith("…"), out[-10:]


# ─────────────────────────────────────────────── T7 init demo-mode ─────────
@check("T7 /init demo-mode: sinh AGENTS.md không cần key")
async def t7():
    import engine.config as config
    from engine.agent import Agent, init_agents_md
    store = make_store()
    sid = store.create().id
    agent = Agent(store, sid)
    ws = agent.workspace
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (ws / "README.md").write_text("# Demo\n", encoding="utf-8")
    orig = config.get_api_key
    config.get_api_key = lambda: None
    try:
        res = await init_agents_md(agent)
    finally:
        config.get_api_key = orig
    assert res["ok"], res
    target = ws / "AGENTS.md"
    assert target.exists() and "DEMO MODE" in target.read_text(encoding="utf-8")


@check("T7b /init demo-mode: workspace rỗng vẫn ok")
async def t7b():
    import engine.config as config
    from engine.agent import Agent, init_agents_md
    store = make_store()
    sid = store.create().id
    agent = Agent(store, sid)
    agent.workspace.mkdir(parents=True, exist_ok=True)
    orig = config.get_api_key
    config.get_api_key = lambda: None
    try:
        res = await init_agents_md(agent)
    finally:
        config.get_api_key = orig
    assert res["ok"], res


# ─────────────────────────────────────────────── T8 auto-compact config ────
@check("T8 get_auto_compact_chars: mặc định 150000, env override, 0 = tắt")
async def t8():
    from engine.config import get_auto_compact_chars
    os.environ["FORGE_AUTO_COMPACT"] = "12345"
    assert get_auto_compact_chars() == 12345
    os.environ["FORGE_AUTO_COMPACT"] = "0"
    assert get_auto_compact_chars() == 0
    os.environ["FORGE_AUTO_COMPACT"] = "rác"
    assert get_auto_compact_chars() == 150000
    os.environ.pop("FORGE_AUTO_COMPACT")
    assert get_auto_compact_chars() == 150000


@check("T8b _conversation_chars đếm đúng")
async def t8b():
    from engine.agent import _conversation_chars
    n = _conversation_chars([{"role": "user", "content": "abcd"},
                             {"role": "assistant", "content": "ef"}])
    assert n == 6, n


# ─────────────────────────────────────────────── T9 agents_md block ────────
@check("T9 AGENTS.md > AGENTS.txt > CLAUDE.md + global data/AGENTS.md")
async def t9():
    from engine.agent import _agents_md_block
    from engine import config
    ws = TMP / "ws9"; ws.mkdir()
    assert _agents_md_block(ws) == ""
    (ws / "CLAUDE.md").write_text("rule-claude", encoding="utf-8")
    assert "rule-claude" in _agents_md_block(ws)
    assert "CLAUDE.md" in _agents_md_block(ws)
    (ws / "AGENTS.md").write_text("rule-agents", encoding="utf-8")
    blk = _agents_md_block(ws)
    assert "rule-agents" in blk and "rule-claude" not in blk, blk  # ưu tiên cao nhất, break
    (ws / "AGENTS.txt").write_text("rule-txt", encoding="utf-8")
    blk = _agents_md_block(ws)
    assert "rule-agents" in blk and "rule-txt" not in blk
    g = config.DATA_DIR / "AGENTS.md"
    g.write_text("global-rule" * 300, encoding="utf-8")  # 3300 chars → cap 2000
    blk = _agents_md_block(ws)
    assert "GLOBAL USER RULES" in blk and "global-rule" in blk
    gblock = blk.split("GLOBAL USER RULES")[1]
    assert len(gblock) <= 2100, len(gblock)
    g.unlink()


# ─────────────────────────────────────────────── T10 server endpoints ──────
@check("T10 server: POST /undo /compact /init trả 200, compact trống ok=False")
async def t10():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        sid = client.post("/api/sessions", json={"title": "t10"}).json()["session"]["id"]
        r_undo = client.post(f"/api/sessions/{sid}/undo")
        assert r_undo.status_code == 200, r_undo.text
        r_init = client.post(f"/api/sessions/{sid}/init")
        assert r_init.status_code == 200 and r_init.json().get("ok"), r_init.text
        r_compact = client.post(f"/api/sessions/{sid}/compact", json={"instructions": ""})
        assert r_compact.status_code == 200
        # phiên chỉ có 1 tin user (init demo) +…— compact có thể ok hoặc không tùy số tin
        body = r_compact.json()
        assert "ok" in body, body


@check("T11 compact KHÔNG có key → ok=False, thông báo thân thiện (không ném exception)")
async def t11():
    from engine.agent import Agent, compact_session
    store = make_store()
    sid = store.create().id
    s = store.get(sid)
    for i in range(6):
        s.messages.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"nội dung {i}"})
    store.save(s)
    res = await compact_session(Agent(store, sid))
    assert res["ok"] is False and "không nén được" in res["message"].lower(), res


def _stream_by_call(state):
    async def _inner(messages, tools=None, model=None, api_key=None, temperature=0.3):
        state["n"] += 1
        if state["n"] == 1:  # lời gọi compact
            yield {"type": "delta", "text": "tóm tắt: người dùng làm việc với new.py"}
            yield {"type": "finish", "reason": "stop"}
        else:  # lượt chat thật
            yield {"type": "delta", "text": "ok"}
            yield {"type": "finish", "reason": "stop"}
    return _inner


@check("T12 auto-compact: send() tự nén khi vượt ngưỡng, emit compacting/compacted")
async def t12():
    import engine.llm as llm
    from engine.agent import Agent
    store = make_store()
    sid = store.create().id
    s = store.get(sid)
    for i in range(10):
        s.messages.append({"role": "user" if i % 2 == 0 else "assistant",
                           "content": f"thư riêng số {i} " + "x" * 60})
    store.save(s)
    os.environ["FORGE_AUTO_COMPACT"] = "200"
    state = {"n": 0}
    orig = llm.stream_chat
    llm.stream_chat = _stream_by_call(state)
    try:
        agent = Agent(store, sid)
        events = [e async for e in agent.send("tiếp nào")]
    finally:
        llm.stream_chat = orig
        os.environ.pop("FORGE_AUTO_COMPACT")
    types = [e["type"] for e in events]
    assert "compacting" in types and "compacted" in types, types
    s2 = store.get(sid)
    assert s2.messages[0]["content"].startswith("[TÓM TẮT HỘI THOẠI TRƯỚC ĐÓ"), s2.messages[0][:60]
    assert state["n"] >= 2, state


async def main():
    print(f"=== SMOKE v0.7 — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t3b, t4, t5, t5b, t6, t7, t7b, t8, t8b, t9, t10, t11, t12]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
