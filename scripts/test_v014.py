# -*- coding: utf-8 -*-
"""Smoke suite v0.14 "Autonomy & Cost":
fetch_url (SSRF-safe) · shell nền run/check/kill · todo checklist · chi phí $ · server.

Chạy:  python scripts/test_v014.py
"""
import asyncio
import json
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v014-"))
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


# ────────────────────────────────────────────── T1 fetch_url ─────────────
@check("T1 fetch_url: strip HTML, chặn SSRF (localhost/riêng), fetch thật example.com")
async def t1():
    from engine.tools import _host_is_private, _strip_html, execute_tool
    html = ("<html><head><style>x{}</style><script>evil()</script></head>"
            "<body><h1>Tiêu đề</h1><p>Nội dung&nbsp;chuẩn &amp; đẹp</p>"
            "<script>hack()</script></body></html>")
    txt = _strip_html(html)
    assert "Tiêu đề" in txt and "Nội dung chuẩn & đẹp" in txt, txt
    assert "evil" not in txt and "hack" not in txt and "<" not in txt, txt
    assert _host_is_private("localhost") is True
    assert _host_is_private("127.0.0.1") is True
    assert _host_is_private("192.168.1.5") is True
    assert _host_is_private("10.0.0.2") is True
    assert _host_is_private("169.254.169.254") is True  # metadata cloud
    assert _host_is_private("example.com") is False
    r = await execute_tool("fetch_url", {"url": "http://127.0.0.1:9/x"}, TMP)
    assert not r["ok"] and "SSRF" in r["output"], r
    r2 = await execute_tool("fetch_url", {"url": "ftp://example.com"}, TMP)
    assert not r2["ok"] and "http/https" in r2["output"], r2
    # fetch thật — mạng có thể chập chờn: chấp nhận thành công hoặc lỗi kết nối rõ ràng
    r3 = await execute_tool("fetch_url", {"url": "https://example.com"}, TMP)
    assert r3["ok"] or "không tải được" in r3["output"], r3
    if r3["ok"]:
        assert "example" in r3["output"].lower() and "[200]" in r3["output"], r3["output"][:120]


# ────────────────────────────────────────────── T2 shell nền ─────────────
@check("T2 background: chạy/check incremental/done/kill + guard chặn lệnh danger")
async def t2():
    from engine.tools import execute_tool
    # 2 marker: chữ lệnh KHÔNG chứa chúng nguyên vẹn (OUT""MARK42 → shell in OUTMARK42)
    # → chứng minh: (1) output nền tới tay qua check, (2) incremental KHÔNG lặp output cũ
    # quoting "4"/"9": shell in ra OUTMARK42/TAILMARK99 nhưng header lệnh không chứa nguyên vẹn
    r = await execute_tool("run_background", {"command":
        "echo OUTMARK\"4\"2; sleep 1.2; echo TAILMARK\"9\"9; sleep 1.5"}, TMP)
    assert r["ok"], r
    m = re.search(r"\[(bg-[0-9a-f]{6})\]", r["output"])
    assert m, r["output"][:120]
    tid = m.group(1)

    async def cb():
        return await execute_tool("check_background", {"id": tid}, TMP)

    # (1) marker đầu: có thể đã nằm trong peek 0.3s của run_background
    seen_head = "OUTMARK42" in r["output"]
    c1 = r
    for _ in range(12):
        if seen_head:
            break
        c1 = await cb()
        if "OUTMARK42" in c1["output"]:
            seen_head = True
            break
        if "✅ xong" in c1["output"] or "❌" in c1["output"]:
            break
        await asyncio.sleep(0.3)
    assert seen_head, f"không bao giờ thấy marker đầu: {str(c1['output'])[:200]}"
    # (2) marker đuôi phải tới qua check incremental
    seen_tail = False
    c2 = c1
    for _ in range(30):
        c2 = await cb()
        if "TAILMARK99" in c2["output"]:
            seen_tail = True
            break
        if "✅ xong" in c2["output"]:
            break
        await asyncio.sleep(0.3)
    assert seen_tail, f"không thấy marker đuôi: {str(c2['output'])[:200]}"
    # (3) check thêm lần nữa: KHÔNG lặp gì cả
    c3 = await cb()
    assert "OUTMARK42" not in c3["output"] and "TAILMARK99" not in c3["output"], \
        "output cũ bị lặp: " + c3["output"][:200]
    c3b = c3
    for _ in range(40):  # poll — không dựa vào thời gian cố định (flaky dưới tải)
        if ("✅ xong" in c3b["output"] or "❌" in c3b["output"]
                or "🛑" in c3b["output"]):
            break
        await asyncio.sleep(0.25)
        c3b = await cb()
    assert "✅ xong" in c3b["output"], c3b
    # kill
    r2 = await execute_tool("run_background", {"command": "sleep 30"}, TMP)
    tid2 = re.search(r"\[(bg-[0-9a-f]{6})\]", r2["output"]).group(1)
    k = await execute_tool("kill_background", {"id": tid2}, TMP)
    assert "kill" in k["output"].lower() or "🛑" in k["output"], k
    # guard: lệnh danger ở chế độ guarded bị chặn
    r3 = await execute_tool("run_background", {"command": "rm -rf /"}, TMP)
    assert not r3["ok"] and ("BLOCKED" in r3["output"] or "danger" in r3["output"].lower()
                             or "chặn" in r3["output"].lower()), r3["output"][:150]
    # danh sách khi trống id
    lst = await execute_tool("check_background", {}, TMP)
    assert tid in lst["output"], lst


# ────────────────────────────────────────────── T3 todo checklist ────────
@check("T3 todo_write: file .forge/todo.json + output checklist + event todo_update")
async def t3():
    from engine.tools import execute_tool
    ws = TMP / "ws3"; ws.mkdir()
    items = [{"text": "Phân tích yêu cầu", "status": "done"},
             {"text": "Viết code", "status": "doing"},
             {"text": "Chạy test", "status": "pending"}]
    r = await execute_tool("todo_write", {"items": items}, ws)
    assert r["ok"] and "1/3 xong" in r["output"], r
    assert "▶ Viết code" in r["output"] and "✅ Phân tích" in r["output"], r["output"]
    saved = json.loads((ws / ".forge" / "todo.json").read_text(encoding="utf-8"))
    assert saved[1] == {"text": "Viết code", "status": "doing"}
    # chuỗi thuần → pending
    r2 = await execute_tool("todo_write", {"items": ["việc A", "việc B"]}, ws)
    assert r2["ok"] and "0/2 xong" in r2["output"], r2
    # status lạ → pending
    r3 = await execute_tool("todo_write", {"items": [{"text": "x", "status": "cá-lơ"}]}, ws)
    saved3 = json.loads((ws / ".forge" / "todo.json").read_text(encoding="utf-8"))
    assert saved3[0]["status"] == "pending"

    # agent phát event todo_update
    import engine.llm as llm
    from engine.agent import Agent
    from engine.session import SessionStore
    store = SessionStore()
    sid = store.create().id
    agent = Agent(store, sid)
    state = {"n": 0}

    async def fake(messages, tools=None, model=None, api_key=None, temperature=0.3):
        state["n"] += 1
        if state["n"] == 1:
            yield {"type": "tool_calls", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "todo_write",
                             "arguments": json.dumps({"items": [
                                 {"text": "bước 1", "status": "done"},
                                 {"text": "bước 2", "status": "doing"}]})}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        else:
            yield {"type": "delta", "text": "đã cập nhật tiến độ"}
            yield {"type": "finish", "reason": "stop"}
    orig = llm.stream_chat
    llm.stream_chat = fake
    try:
        evs = [e async for e in agent.send("làm nhiệm vụ có checklist")]
    finally:
        llm.stream_chat = orig
    tu = [e for e in evs if e["type"] == "todo_update"]
    assert tu and len(tu[0]["items"]) == 2 and tu[0]["items"][0]["status"] == "done", tu


# ────────────────────────────────────────────── T4 chi phí $ ─────────────
@check("T4 cost: estimate từ giá model + turn_end cost_usd + cộng dồn phiên")
async def t4():
    from engine import cost
    from engine.agent import Agent
    from engine.session import SessionStore
    import engine.llm as llm

    async def fake_prices():
        return {"test/primary-model": (0.000003, 0.000015)}
    orig_fetch = cost._fetch_prices
    cost._fetch_prices = fake_prices
    try:
        c = await cost.estimate("test/primary-model",
                                {"prompt_tokens": 1000, "completion_tokens": 100})
        assert abs(c - 0.0045) < 1e-9, c
        assert await cost.estimate("model/khong-co-gia", {"prompt_tokens": 10}) is None
        assert await cost.estimate("test/primary-model", {}) is None

        store = SessionStore()
        sid = store.create().id
        agent = Agent(store, sid, model="test/primary-model")
        state = {"n": 0}

        async def fake(messages, tools=None, model=None, api_key=None, temperature=0.3):
            state["n"] += 1
            yield {"type": "delta", "text": "xin chào"}
            yield {"type": "usage", "usage": {"prompt_tokens": 1000,
                                              "completion_tokens": 100,
                                              "total_tokens": 1100}}
            yield {"type": "finish", "reason": "stop"}
        orig = llm.stream_chat
        llm.stream_chat = fake
        try:
            evs = [e async for e in agent.send("chào")]
        finally:
            llm.stream_chat = orig
        te = [e for e in evs if e["type"] == "turn_end"][0]
        assert abs((te.get("cost_usd") or 0) - 0.0045) < 1e-9, te
        assert abs((te["session_usage"].get("cost_usd") or 0) - 0.0045) < 1e-9
    finally:
        cost._fetch_prices = orig_fetch


# ────────────────────────────────────────────── T5 server ────────────────
@check("T5 server: health + chat demo vẫn ổn sau khi thêm 5 tool mới")
async def t5():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ok"]
        sid = client.post("/api/sessions", json={"title": "t5"}).json()["session"]["id"]
        r = client.post(f"/api/sessions/{sid}/chat", json={"text": "hi", "mode": "direct"})
        assert '"done"' in r.text, r.text[-200:]


async def main():
    print(f"=== SMOKE v0.14 — data tạm: {TMP} ===")
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
