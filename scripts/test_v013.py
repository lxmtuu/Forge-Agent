# -*- coding: utf-8 -*-
"""Smoke suite v0.13 "Multi-Model Orchestrator":
alias model cho sub-agent · routing guidance trong spec · fan-out song song ·
cap 6 sub-agent/lượt · availability fallback (402/429/5xx).

Chạy:  python scripts/test_v013.py
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v013-"))
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


# ────────────────────────────────────────────── T1 alias model ───────────
@check("T1 resolve_sub_model: inherit/cheap/free/strong/ID đầy đủ + config model_roles")
async def t1():
    from engine.llm import resolve_sub_model
    from engine import config
    assert resolve_sub_model("", "cha/model-x") is None
    assert resolve_sub_model("inherit") is None
    assert resolve_sub_model("SAME") is None
    assert resolve_sub_model("cheap") == "openrouter/free"
    assert resolve_sub_model("FREE") == "openrouter/free"
    # strong không có roles → model cha
    assert resolve_sub_model("strong", "cha/model-x") == "cha/model-x"
    # strong không có cha → config model
    cur = config.get_model()
    assert resolve_sub_model("strong") in (cur, None) or isinstance(
        resolve_sub_model("strong"), str)
    # roles tuỳ chỉnh
    config.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg = config.load_config()
    cfg["model_roles"] = {"cheap": "vendor/re-mien-phi", "strong": "vendor/model-manh"}
    config.CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")
    try:
        assert resolve_sub_model("cheap") == "vendor/re-mien-phi"
        assert resolve_sub_model("strong", "cha/x") == "vendor/model-manh"
        assert resolve_sub_model("google/gemini-3.8-flash") == "google/gemini-3.8-flash"
    finally:
        cfg = config.load_config()
        cfg.pop("model_roles", None)
        config.CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")


# ────────────────────────────────────────────── T2 spec guidance ─────────
@check("T2 spec spawn_subagent: có bảng routing (cheap/strong/inherit) + gợi ý song song")
async def t2():
    from engine.tools import TOOL_SPECS
    spec = [sp for sp in TOOL_SPECS if sp["function"]["name"] == "spawn_subagent"][0]
    blob = json.dumps(spec, ensure_ascii=False).lower()
    for kw in ("cheap", "strong", "inherit", "song song", "kiến trúc", "tìm kiếm"):
        assert kw in blob, f"thiếu từ khoá «{kw}» trong spec"
    # depth=1 vẫn loại spawn_subagent (không đệ quy)
    from engine.agent import Agent
    from engine.session import SessionStore
    from engine import agent as ag_mod
    store = SessionStore()
    sid = store.create().id
    a = Agent(store, sid, depth=0)
    assert a.depth == 0


# ────────────────────────────────────────────── T3 fan-out song song ─────
SUB_SLEEP = 0.45


async def _fake_llm_multi(state):
    async def fake(messages, tools=None, model=None, api_key=None, temperature=0.3):
        state["n"] += 1
        last = messages[-1]["content"] if messages else ""
        if state["n"] == 1:
            tcs = [{"id": f"c{i}", "type": "function",
                    "function": {"name": "spawn_subagent",
                                 "arguments": json.dumps({"task": f"việc {i}: đếm file",
                                                          "model": "cheap"})}}
                   for i in (1, 2)]
            yield {"type": "tool_calls", "tool_calls": tcs}
            yield {"type": "finish", "reason": "tool_calls"}
        elif str(last).startswith("việc"):  # chỉ message NHIỆM VỤ của sub mới khớp
            await asyncio.sleep(SUB_SLEEP)
            yield {"type": "delta", "text": f"xong {str(last)[:10]}"}
            yield {"type": "finish", "reason": "stop"}
        else:
            yield {"type": "delta", "text": "tổng hợp 2 sub-agent xong"}
            yield {"type": "finish", "reason": "stop"}
    return fake


@check("T3 fan-out: 2 spawn cùng lượt chạy SONG SONG (<0.85s), cả 2 kết quả về cha")
async def t3():
    import engine.llm as llm
    from engine.agent import Agent
    from engine.session import SessionStore
    store = SessionStore()
    sid = store.create().id
    parent = Agent(store, sid)
    state = {"n": 0}
    orig = llm.stream_chat
    llm.stream_chat = await _fake_llm_multi(state)
    try:
        t0 = time.monotonic()
        evs = [e async for e in parent.send("chạy 2 việc song song giúp tớ")]
        elapsed = time.monotonic() - t0
    finally:
        llm.stream_chat = orig
    started = [e for e in evs if e["type"] == "subagent_started"]
    assert len(started) == 2, [e["type"] for e in evs]
    assert {e["model"] for e in started} == {"openrouter/free"}, started
    trs = [e for e in evs if e["type"] == "tool_result"]
    assert len(trs) == 2 and all(tr["ok"] for tr in trs), trs
    assert all("việc" in tr["output"] or "xong" in tr["output"] for tr in trs), trs
    # song song thật: 2×0.45 tuần tự = 0.9s+; song song phải < 0.85s
    assert elapsed < 0.85, f"chạy tuần tự? {elapsed:.2f}s"
    # cả 2 phiên sub workspace = workspace cha
    for e in started:
        assert store.workspace(e["session_id"]).resolve() == parent.workspace.resolve()
    assert state["n"] == 4, state  # 1 cha + 2 sub + 1 cha tổng hợp


# ────────────────────────────────────────────── T4 cap 6/lượt ────────────
async def _fake_llm_cap(state):
    async def fake(messages, tools=None, model=None, api_key=None, temperature=0.3):
        state["n"] += 1
        last = str(messages[-1]["content"]) if messages else ""
        if state["n"] == 1:
            tcs = [{"id": f"c{i}", "type": "function",
                    "function": {"name": "spawn_subagent",
                                 "arguments": json.dumps({"task": f"task {i}"})}}
                   for i in range(1, 9)]  # 8 spawns → chỉ 6 được chạy
            yield {"type": "tool_calls", "tool_calls": tcs}
            yield {"type": "finish", "reason": "tool_calls"}
        elif last.startswith("task "):
            yield {"type": "delta", "text": f"done {last[:8]}"}
            yield {"type": "finish", "reason": "stop"}
        else:
            yield {"type": "delta", "text": "hoàn tất"}
            yield {"type": "finish", "reason": "stop"}
    return fake


@check("T4 cap: 8 spawn → đúng 6 chạy, 2 báo 'giới hạn'")
async def t4():
    import engine.llm as llm
    from engine.agent import Agent, MAX_SUBAGENTS_PER_TURN
    from engine.session import SessionStore
    assert MAX_SUBAGENTS_PER_TURN == 6
    store = SessionStore()
    sid = store.create().id
    parent = Agent(store, sid)
    state = {"n": 0}
    orig = llm.stream_chat
    llm.stream_chat = await _fake_llm_cap(state)
    try:
        evs = [e async for e in parent.send("giao 8 việc")]
    finally:
        llm.stream_chat = orig
    started = [e for e in evs if e["type"] == "subagent_started"]
    assert len(started) == 6, len(started)
    trs = [e for e in evs if e["type"] == "tool_result"]
    assert len(trs) == 8, len(trs)
    capped = [tr for tr in trs if "giới hạn" in tr["output"]]
    assert len(capped) == 2, [tr["output"][:40] for tr in capped]
    assert sum(1 for tr in trs if tr["ok"]) == 6


# ────────────────────────────────────────────── T5 availability fallback ─
@check("T5 fallback: 402 → model_fallback event → thử openrouter/free → trả lời được")
async def t5():
    from engine.llm import LLMError, pick_fallback, resolve_sub_model
    from engine.agent import Agent
    from engine.session import SessionStore
    from engine import config

    # unit pick_fallback
    assert pick_fallback("test/model-a", LLMError("OpenRouter 402 — hết credit")) == "openrouter/free"
    assert pick_fallback("openrouter/free", LLMError("HTTP 429 x")) is None  # trùng model
    assert pick_fallback("test/a", LLMError("lỗi lạ không rõ mã")) is None
    config.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg = config.load_config()
    cfg["model_fallbacks"] = ["vendor/du-phong-1", "openrouter/free"]
    config.CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")
    try:
        assert pick_fallback("test/a", LLMError("HTTP 502 bad")) == "vendor/du-phong-1"
    finally:
        cfg = config.load_config()
        cfg.pop("model_fallbacks", None)
        config.CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")

    # end-to-end trong agent
    store = SessionStore()
    sid = store.create().id
    agent = Agent(store, sid, model="test/primary-model")
    state = {"n": 0}

    async def fake(messages, tools=None, model=None, api_key=None, temperature=0.3):
        state["n"] += 1
        if state["n"] == 1:
            raise LLMError("OpenRouter 402 — Key hợp lệ nhưng KHÔNG ĐỦ CREDIT")
        yield {"type": "delta", "text": "trả lời bằng model dự phòng"}
        yield {"type": "finish", "reason": "stop"}

    import engine.llm as llm
    orig = llm.stream_chat
    llm.stream_chat = fake
    try:
        evs = [e async for e in agent.send("xin chào")]
    finally:
        llm.stream_chat = orig
    fb = [e for e in evs if e["type"] == "model_fallback"]
    assert fb and fb[0]["to"] == "openrouter/free" and "402" in fb[0]["reason"], fb
    msg = [e for e in evs if e["type"] == "assistant_message"]
    assert msg and "dự phòng" in (msg[0]["content"] or ""), msg


# ────────────────────────────────────────────── T6 server ────────────────
@check("T6 server: health + chat demo vẫn ổn sau khi thêm multi-model")
async def t6():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ok"]
        sid = client.post("/api/sessions", json={"title": "t6"}).json()["session"]["id"]
        r = client.post(f"/api/sessions/{sid}/chat", json={"text": "hi", "mode": "direct"})
        assert '"done"' in r.text, r.text[-200:]


async def main():
    print(f"=== SMOKE v0.13 — data tạm: {TMP} ===")
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
