# -*- coding: utf-8 -*-
"""Suite v0.25 "Liên phiên & Ký năng rõ phép" (F2 + S7):
bus unit (send/inbox/offset/peek) · agent tool-path send_message/check_inbox
(stub LLM) · INBOX injection vào system prompt · REST messages · S7 allowed-tools.

Chạy:  python scripts/test_v026.py
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

TMP = Path(tempfile.mkdtemp(prefix="forge-v026-"))
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


@check("T1 bus unit: send → inbox (đánh dấu đã đọc) · peek không đổi mốc · truncation 4000")
async def t1():
    from engine import bus as fbus
    fbus.send("a", "b", "xin chào")
    fbus.send("a", "c", "tin thứ hai")
    assert fbus.unread_count("a") == 2
    rows = fbus.peek("a")
    assert len(rows) == 2 and rows[0]["text"] == "xin chào" and rows[0]["from"] == "b"
    assert fbus.unread_count("a") == 2, "peek không được đổi mốc"
    rows = fbus.inbox("a")
    assert len(rows) == 2
    assert fbus.inbox("a") == [], "inbox lần 2 phải rỗng (đã đọc)"
    assert fbus.unread_count("a") == 0
    # truncation
    fbus.send("a", "b", "x" * 9000)
    rows = fbus.inbox("a")
    assert len(rows[0]["text"]) == 4000
    # inbox phiên không tồn tại file
    assert fbus.inbox("khong-co") == [] and fbus.unread_count("khong-co") == 0


@check("T2 agent tool-path: send_message (validate đúng/sai) · check_inbox đọc + tự đánh dấu đã đọc")
async def t2():
    from engine.agent import Agent
    from engine.session import SessionStore
    store = SessionStore()
    sid_a = store.create().id
    sid_b = store.create().id

    async def fake_llm(messages, tools, model):
        calls = fake_llm.calls
        calls.append(1)
        if len(calls) == 1:
            yield {"type": "tool_calls", "tool_calls": [
                {"id": "t1", "function": {"name": "send_message",
                                          "arguments": f'{{"to_session": "{sid_b}", "text": "báo cáo: test xong"}}'}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        elif len(calls) == 2:
            # gửi sai: phiên không tồn tại
            yield {"type": "tool_calls", "tool_calls": [
                {"id": "t2", "function": {"name": "send_message",
                                          "arguments": '{"to_session": "khong-co", "text": "x"}'}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        elif len(calls) == 3:
            yield {"type": "tool_calls", "tool_calls": [
                {"id": "t3", "function": {"name": "check_inbox", "arguments": "{}"}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        else:
            yield {"type": "delta", "text": "xong"}
            yield {"type": "finish", "reason": "stop"}
    fake_llm.calls = []

    ag = Agent(store, sid_a)
    ag._llm_with_fallback = fake_llm
    outputs: dict[str, str] = {}
    async for ev in ag.send("điều phối"):
        if ev["type"] == "tool_result":
            outputs[ev["id"]] = ev["output"]
    # t1: gửi OK — hộp thư b có tin
    assert "Đã gửi tới" in outputs["t1"], outputs.get("t1")
    from engine import bus as fbus
    rows = fbus.inbox(sid_b)
    assert len(rows) == 1 and rows[0]["text"] == "báo cáo: test xong" and rows[0]["from"] == sid_a
    # t2: phiên lạ → lỗi thân thiện
    assert "không có phiên" in outputs["t2"], outputs.get("t2")
    # t3: hộp thư a trống → "(hộp thư trống)"
    assert "hộp thư trống" in outputs["t3"], outputs.get("t3")
    # giờ gửi vào a rồi cho a check_inbox
    fbus.send(sid_a, sid_b, "hello từ B")
    fake_llm.calls.clear()

    async def fake_llm2(messages, tools, model):
        fake_llm2.calls.append(1)
        if len(fake_llm2.calls) == 1:
            yield {"type": "tool_calls", "tool_calls": [
                {"id": "c1", "function": {"name": "check_inbox", "arguments": "{}"}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        else:
            yield {"type": "delta", "text": "đã đọc"}
            yield {"type": "finish", "reason": "stop"}
    fake_llm2.calls = []
    ag2 = Agent(store, sid_a)
    ag2._llm_with_fallback = fake_llm2
    out_c = ""
    async for ev in ag2.send("đọc thư"):
        if ev["type"] == "tool_result" and ev["id"] == "c1":
            out_c = ev["output"]
    assert "hello từ B" in out_c and sid_b in out_c, out_c
    assert fbus.unread_count(sid_a) == 0, "check_inbox phải đánh dấu đã đọc"


@check("T3 INBOX injection: có tin chưa đọc → system prompt có nhắc check_inbox · hết tin → không nhắc")
async def t3():
    from engine.agent import Agent
    from engine.session import SessionStore
    store = SessionStore()
    sid = store.create().id
    seen_contents: list[str] = []

    async def fake_llm(messages, tools, model):
        seen_contents.append(str(messages[0].get("content", "")))
        yield {"type": "delta", "text": "ok"}
        yield {"type": "finish", "reason": "stop"}

    from engine import bus as fbus
    fbus.send(sid, "other", "nhắc việc")
    ag = Agent(store, sid)
    ag._llm_with_fallback = fake_llm
    async for _ in ag.send("lượt 1"):
        pass
    assert "INBOX" in seen_contents[0] and "check_inbox" in seen_contents[0], seen_contents[0][-200:]
    async for _ in ag.send("lượt 2"):  # tin đã đọc ở lượt 1 (model gọi check_inbox? — ở đây chỉ cần mốc)
        pass
    # sau lượt 1, tin vẫn chưa đọc (stub không gọi check_inbox) — gọi inbox thủ công để đọc
    fbus.inbox(sid)
    seen_contents.clear()
    async for _ in ag.send("lượt 3"):
        pass
    assert "INBOX" not in seen_contents[0], "đã đọc rồi mà vẫn nhắc INBOX?"


@check("T4 REST messages: POST → GET (peek không đổi mốc) → GET thật (đọc) → GET lại rỗng · 404")
async def t4():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        sid = c.post("/api/sessions", json={}).json()["session"]["id"]
        source = c.post("/api/sessions", json={}).json()["session"]["id"]
        r = c.post(f"/api/sessions/{sid}/messages", json={"text": "tin từ web", "from_session": source})
        assert r.status_code == 200 and r.json()["ok"], r.text[:120]
        d = c.get(f"/api/sessions/{sid}/messages", params={"peek": "true"}).json()
        assert d["count"] == 1 and d["messages"][0]["text"] == "tin từ web"
        d2 = c.get(f"/api/sessions/{sid}/messages", params={"peek": "true"}).json()
        assert d2["count"] == 1, "peek qua REST cũng không được đổi mốc"
        d3 = c.get(f"/api/sessions/{sid}/messages").json()
        assert d3["count"] == 1
        d4 = c.get(f"/api/sessions/{sid}/messages").json()
        assert d4["count"] == 0, "GET mặc định phải đánh dấu đã đọc"
        assert c.post("/api/sessions/khong-co/messages", json={"text": "x"}).status_code == 404
        assert c.get("/api/sessions/khong-co/messages").status_code == 404
        assert c.post(f"/api/sessions/{sid}/messages", json={"text": "  "}).status_code == 400


@check("T5 S7: skill có allowed-tools → /skills listing hiện 🔑 + danh sách tool")
async def t5():
    from engine import skillmgr
    from engine.session import SessionStore
    store = SessionStore()
    sid = store.create().id
    ws = store.workspace(sid)
    sk = ws / ".forge" / "skills" / "phép-đọc"
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text(
        "---\nname: phép-đọc\ndescription: skill test có giới hạn tool\n"
        "allowed-tools: read_file, list_dir, search_files\n---\n\n# Thân skill\n",
        encoding="utf-8")
    listing = skillmgr.format_listing(ws)
    assert "phép-đọc" in listing
    assert "🔑" in listing and "read_file" in listing, listing
    # skill không có allowed-tools → không có 🔑
    sk2 = ws / ".forge" / "skills" / "tự-do"
    sk2.mkdir(parents=True, exist_ok=True)
    (sk2 / "SKILL.md").write_text("---\nname: tự-do\ndescription: không giới hạn\n---\n\nx\n",
                                  encoding="utf-8")
    listing2 = skillmgr.format_listing(ws)
    assert "tự-do" in listing2


@check("T6 chat synthetic /msg + /inbox: chạy qua /chat không crash, đúng thông điệp (bài học v0.25: biến 'body' che tham số)")
async def t6():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        sa = c.post("/api/sessions", json={}).json()["session"]["id"]
        sb = c.post("/api/sessions", json={}).json()["session"]["id"]

        def last_msg(text, sid_x):
            r = c.post(f"/api/sessions/{sid_x}/chat", json={"text": text, "mode": "direct"})
            assert r.status_code == 200, (text, r.status_code, r.text[:200])
            msgs = [json.loads(ln[5:]) for ln in r.text.splitlines()
                    if ln.startswith("data:") and '"assistant_message"' in ln]
            assert msgs, f"không có assistant_message cho {text!r}"
            return msgs[-1]["content"]

        out = last_msg(f"/msg {sb} chào từ A", sa)
        assert "Đã gửi tới" in out, out
        # peek=true — KHÔNG tiêu thụ hộp thư (GET mặc định sẽ mark-read làm /inbox rỗng)
        assert c.get(f"/api/sessions/{sb}/messages", params={"peek": "true"}).json()["count"] == 1
        out2 = last_msg("/inbox", sb)
        assert "chào từ A" in out2, out2
        out3 = last_msg("/msg khong-co x", sa)
        assert "không có phiên" in out3.lower(), out3


async def main():
    print(f"=== SUITE v0.25 Liên phiên & Ký năng rõ phép — data tạm: {TMP} ===")
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
