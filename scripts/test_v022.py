# -*- coding: utf-8 -*-
"""Suite v0.21 "Kiến trúc sư & Chỉnh lại":
A6 architect mode (mạnh plan → rẻ code, E2E với LLM stub)
· E5 /rerun (chỉnh tin user → chạy lại) · chat rerun=true (append_user=False)
· C5 install/gỡ preset từ web tab Dịch vụ.

Chạy:  python scripts/test_v022.py
"""
import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import _test_auth
_test_auth.install()

TMP = Path(tempfile.mkdtemp(prefix="forge-v022-"))
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


def make_agent():
    """Agent + stub LLM ghi lại (messages, tools, model) mỗi lần gọi."""
    from engine.agent import Agent
    from engine.session import SessionStore
    store = SessionStore()
    sid = store.create().id
    ag = Agent(store, sid)
    calls: list[dict] = []

    async def fake_llm(messages, tools, model):
        calls.append({"n_msgs": len(messages), "tools": tools, "model": model,
                      "last_role": messages[-1]["role"],
                      "last_content": str(messages[-1].get("content", ""))[:80]})
        n = len(calls)
        if n == 1:
            yield {"type": "delta", "text": "KẾ HOẠCH: 1) tạo file a.py 2) chạy test"}
            yield {"type": "usage", "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
            yield {"type": "finish", "reason": "stop"}
        else:
            yield {"type": "delta", "text": f"ĐÃ-THI-CÔNG-{n}"}
            yield {"type": "usage", "usage": {"prompt_tokens": 20, "completion_tokens": 8}}
            yield {"type": "finish", "reason": "stop"}

    ag._llm_with_fallback = fake_llm
    return store, sid, ag, calls


@check("T1 A6 architect: phase plan (model strong, không tool) → phase execute (model cheap, đủ tool) → 2 assistant msg")
async def t1():
    from engine import llm as fllm
    from engine.tools import TOOL_SPECS
    store, sid, ag, calls = make_agent()
    evs = []
    async for ev in ag.send("làm tính năng X", chat_mode="architect"):
        evs.append(ev)
    types = [e["type"] for e in evs]
    assert "phase" in types, types
    phases = [e for e in evs if e["type"] == "phase"]
    assert phases[0]["phase"] == "plan" and phases[0]["model"] == fllm.resolve_model("strong"), phases[0]
    assert phases[1]["phase"] == "execute" and phases[1]["model"] == fllm.resolve_model("cheap"), phases[1]
    assert phases[1]["plan_chars"] > 0
    # 2 lần gọi LLM: (1) plan — không tool, prompt kế hoạch là tin CUỐI; (2) execute — đủ tool
    assert len(calls) == 2, len(calls)
    assert calls[0]["model"] == fllm.resolve_model("strong") and calls[0]["tools"] is None
    assert "KẾ HOẠCH" in calls[0]["last_content"] or "lập KẾ HOẠCH" in calls[0]["last_content"]
    assert calls[1]["model"] == fllm.resolve_model("cheap")
    assert calls[1]["tools"] == TOOL_SPECS, "lượt thực thi phải có đủ tool"
    assert "Thực hiện NGAY" in calls[1]["last_content"], calls[1]["last_content"]
    # session: [user, assistant(plan), assistant(thi công)]
    s = store.get(sid)
    assert [m["role"] for m in s.messages] == ["user", "assistant", "assistant"]
    assert s.messages[1]["content"].startswith("KẾ HOẠCH")
    assert s.messages[2]["content"] == "ĐÃ-THI-CÔNG-2"
    assert "turn_end" in types


@check("T2 E5 /rerun: cắt + thay tin user · index sai/assistant/ngoài phạm vi → 400 · sid lạ → 404")
async def t2():
    from fastapi.testclient import TestClient
    from server.main import app
    from engine.session import SessionStore
    store = SessionStore()
    sid = store.create().id
    st = store.get(sid)
    st.messages = [{"role": "user", "content": "m1"},
                   {"role": "assistant", "content": "a1"},
                   {"role": "user", "content": "m2"},
                   {"role": "assistant", "content": "a2"}]
    store.save(st)
    with TestClient(app) as c:
        r = c.post(f"/api/sessions/{sid}/rerun", json={"index": 2, "text": "m2 ĐÃ SỬA"})
        assert r.status_code == 200 and r.json()["ok"], r.text[:120]
        st = store.get(sid)
        assert len(st.messages) == 3
        assert st.messages[2] == {"role": "user", "content": "m2 ĐÃ SỬA"}
        assert c.post(f"/api/sessions/{sid}/rerun", json={"index": 99, "text": "x"}).status_code == 400
        assert c.post(f"/api/sessions/{sid}/rerun", json={"index": 1, "text": "x"}).status_code == 400
        assert c.post("/api/sessions/khong-co/rerun", json={"index": 0, "text": "x"}).status_code == 404


@check("T3 chat rerun=true → agent.send(append_user=False): KHÔNG thêm tin user (tiêu đề cũng giữ)")
async def t3():
    store, sid, ag, calls = make_agent()
    before_users = 0
    async for _ in ag.send("tin đầu", chat_mode="direct"):
        pass
    before_users = sum(1 for m in store.get(sid).messages if m["role"] == "user")
    before_len = len(store.get(sid).messages)
    title_before = store.get(sid).title
    # mô phỏng flow E5: tin user đã có sẵn — gọi với append_user=False
    async for _ in ag.send("", chat_mode="direct", append_user=False):
        pass
    st = store.get(sid)
    assert sum(1 for m in st.messages if m["role"] == "user") == before_users, "thêm tin user?!"
    assert len(st.messages) == before_len + 1, "chỉ được thêm 1 assistant"
    assert st.messages[-1]["content"] == "ĐÃ-THI-CÔNG-2"
    assert st.title == title_before


@check("T4 C5 install/gỡ preset từ web: install github → presets installed=true · gỡ → false · preset lạ → 404")
async def t4():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        r = c.post("/api/connectors/install", params={"id": "github"}, json={})
        assert r.status_code == 200 and r.json()["ok"], r.text[:150]
        assert "github" in r.json()["message"].lower() or "GitHub" in r.json()["message"]
        rows = {x["id"]: x for x in c.get("/api/connectors/presets").json()["presets"]}
        assert rows["github"]["installed"] is True
        r2 = c.delete("/api/connectors/github/installed")
        assert r2.status_code == 200 and r2.json()["ok"]
        rows = {x["id"]: x for x in c.get("/api/connectors/presets").json()["presets"]}
        assert rows["github"]["installed"] is False
        assert c.post("/api/connectors/install", params={"id": "zzz-khong-co"}, json={}).status_code == 404
        assert c.delete("/api/connectors/zzz-khong-co/installed").status_code == 404


async def main():
    print(f"=== SUITE v0.21 Kiến trúc sư & Chỉnh lại — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
