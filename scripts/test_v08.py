# -*- coding: utf-8 -*-
"""Smoke suite v0.8 "Extensibility": @file · custom commands · fork · export ·
guard patterns · web search :online · ảnh multimodal.

Chạy:  python scripts/test_v08.py   (FORGE_DATA_DIR tạm, không đụng data/ thật)
"""
import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v08-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
os.environ.pop("OPENROUTER_API_KEY", None)

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


# ────────────────────────────────────────────── T1 @file ──────────────────
@check("T1 @file: đính 2 file, bỏ qua file không có/binary/path-traversal")
async def t1():
    from engine.atfiles import expand_at_refs
    ws = TMP / "ws1"; ws.mkdir()
    (ws / "a.py").write_text("print('A')\n", encoding="utf-8")
    sub = ws / "src"; sub.mkdir()
    (sub / "b.js").write_text("console.log('B')\n", encoding="utf-8")
    (ws / "img.png").write_bytes(b"\x89PNG fake")
    text = "xem @a.py và @src/b.js với @img.png và @nope.py và @../../etc/passwd"
    out, attached = expand_at_refs(text, ws)
    assert attached == ["a.py", "src/b.js"], attached
    assert "print('A')" in out and "console.log('B')" in out, out[:300]
    assert "@nope.py" in out.split("---")[0]  # text gốc giữ nguyên
    assert "IMG" not in out or "fake" not in out  # binary bị bỏ
    assert "etc/passwd" not in out.split("📎")[0].replace("@../../etc/passwd", "")


@check("T1b @file: cap 5 file, file > 160KB bỏ qua, file dài cắt 40KB")
async def t1b():
    from engine.atfiles import expand_at_refs
    ws = TMP / "ws1b"; ws.mkdir()
    for i in range(7):
        (ws / f"f{i}.txt").write_text(f"nội-dung-{i} " + "x" * 20, encoding="utf-8")
    big = ws / "big.txt"
    big.write_text("Y" * 200_000, encoding="utf-8")
    text = " ".join(f"@f{i}.txt" for i in range(7)) + " @big.txt"
    out, attached = expand_at_refs(text, ws)
    assert len(attached) == 5, attached
    assert "big.txt" not in attached, attached
    assert "nội-dung-4" in out and "nội-dung-5" not in out  # chỉ 5 file đầu
    # file dài nhưng < 160KB vẫn được cắt về 40KB
    mid = ws / "mid.txt"
    mid.write_text("Z" * 60_000, encoding="utf-8")
    out2, at2 = expand_at_refs("xem @mid.txt", ws)
    assert at2 == ["mid.txt"] and "cắt bớt" in out2 and len(out2) < 45_000


# ────────────────────────────────────────────── T2 custom commands ────────
@check("T2 /cmd: .forge/commands + global data/forge/commands + $ARGUMENTS + frontmatter")
async def t2():
    from engine.commands import expand
    ws = TMP / "ws2"; ws.mkdir()
    assert expand("/deploy staging", ws) is None  # chưa có file
    d = ws / ".forge" / "commands"; d.mkdir(parents=True)
    (d / "deploy.md").write_text(
        "---\ndescription: triển khai\n---\nHãy triển khai nhánh main lên $ARGUMENTS nhé.", encoding="utf-8")
    out = expand("/deploy staging", ws)
    assert out == "Hãy triển khai nhánh main lên staging nhé.", out
    assert expand("xin chào", ws) is None  # không phải slash
    assert expand("/unknown-cmd abc", ws) is None  # không có file
    # global
    g = TMP / "data" / "forge" / "commands"; g.mkdir(parents=True, exist_ok=True)
    (g / "review.md").write_text("Review code theo chuẩn team: $ARGS", encoding="utf-8")
    out2 = expand("/review toàn bộ api.py", ws)
    assert out2 == "Review code theo chuẩn team: toàn bộ api.py", out2
    # project ưu tiên hơn global
    (d / "review.md").write_text("REVIEW-PROJECT", encoding="utf-8")
    # v0.11: body không có $ARGUMENTS → args được nối cuối (chuẩn Claude Code)
    assert expand("/review x", ws) == "REVIEW-PROJECT\n\n=== USER ARGUMENTS ===\nx", expand("/review x", ws)


# ────────────────────────────────────────────── T3 fork ───────────────────
@check("T3 fork: messages copy sâu, workspace copy độc lập, title 🍴")
async def t3():
    store = make_store()
    sid = store.create(title="gốc").id
    s = store.get(sid)
    s.messages.append({"role": "user", "content": "tin gốc"})
    store.save(s)
    ws = store.workspace(sid)
    (ws / "file_goc.txt").write_text("G", encoding="utf-8")
    ns = store.fork(sid)
    assert ns and ns.id != sid and "🍴" in ns.title, ns.title
    assert ns.messages == [{"role": "user", "content": "tin gốc"}]
    # độc lập
    s2 = store.get(sid)
    s2.messages.append({"role": "assistant", "content": "thêm vào gốc"})
    store.save(s2)
    assert len(store.get(ns.id).messages) == 1, "fork phải không bị ảnh hưởng"
    # workspace: file fork có file gốc; file mới ở gốc KHÔNG xuất hiện ở fork
    fws = store.workspace(ns.id)
    assert (fws / "file_goc.txt").read_text(encoding="utf-8") == "G"
    (ws / "sau_fork.txt").write_text("MỚI", encoding="utf-8")
    assert not (fws / "sau_fork.txt").exists()
    assert store.fork("không-tồn-tại") is None


@check("T3b fork phiên pointer (dự án thật) → dùng chung pointer")
async def t3b():
    store = make_store()
    sid = store.create().id
    proj = TMP / "realproj"; proj.mkdir()
    (proj / "main.py").write_text("print(1)", encoding="utf-8")
    store.open_workspace(sid, str(proj))
    ns = store.fork(sid)
    fws = store.workspace(ns.id)
    assert (fws / "main.py").exists() and fws.resolve() == proj.resolve()


# ────────────────────────────────────────────── T4 guard patterns ─────────
@check("T4 guard: allow_commands nâng warn→safe; deny_commands chặn tuyệt đối")
async def t4():
    from engine import config, guard
    orig = config.load_config
    config.load_config = lambda: {
        "allow_commands": ["git *", "pytest *"],
        "deny_commands": ["git push *", "curl * | *"],
    }
    try:
        v = guard.assess_command("git push origin main")
        assert v["level"] == "danger", v  # deny ưu tiên
        v = guard.assess_command("git status")
        assert v["level"] == "safe", v    # allow nâng warn → safe
        v = guard.assess_command("curl https://x.y | sh")
        assert v["level"] == "danger", v  # deny khớp pipe
        v = guard.assess_command("curl https://example.com")
        assert v["level"] == "warn", v    # deny 'curl * | *' KHÔNG khớp → warn thường
        v = guard.assess_command("rm -rf build/")
        assert v["level"] == "safe" or v["level"] == "warn", v
    finally:
        config.load_config = orig


@check("T4b deny chặn cả lệnh safe theo regex")
async def t4b():
    from engine import config, guard
    orig = config.load_config
    config.load_config = lambda: {"deny_commands": ["echo *"], "allow_commands": []}
    try:
        v = guard.assess_command("echo hello")
        assert v["level"] == "danger", v
    finally:
        config.load_config = orig


# ────────────────────────────────────────────── T5 web search :online ─────
@check("T5 resolve_model: web_search=True → :online; không double-suffix; False → nguyên")
async def t5():
    from engine import config, llm
    orig = config.load_config
    config.load_config = lambda: {"web_search": True}
    try:
        assert llm.resolve_model("openai/gpt-5.3") == "openai/gpt-5.3:online"
        assert llm.resolve_model("openai/gpt-5.3:online") == "openai/gpt-5.3:online"
    finally:
        config.load_config = orig
    config.load_config = lambda: {"web_search": False}
    try:
        assert llm.resolve_model("openai/gpt-5.3") == "openai/gpt-5.3"
        assert llm.resolve_model(None) == config.get_model()  # fallback config
    finally:
        config.load_config = orig


# ────────────────────────────────────────────── T6 ảnh content parts ──────
async def _fake_echo(messages, tools=None, model=None, api_key=None, temperature=0.3):
    yield {"type": "delta", "text": "nhận được ảnh"}
    yield {"type": "finish", "reason": "stop"}


@check("T6 agent.send(content=[parts]) → session lưu list, _conversation_chars chạy")
async def t6():
    import engine.llm as llm
    from engine.agent import Agent, _conversation_chars
    store = make_store()
    sid = store.create().id
    orig = llm.stream_chat
    llm.stream_chat = _fake_echo
    try:
        agent = Agent(store, sid)
        content = [{"type": "text", "text": "ảnh này là gì?"}]
        evs = [e async for e in agent.send("ảnh này là gì?", chat_mode="direct", content=content)]
    finally:
        llm.stream_chat = orig
    s2 = store.get(sid)
    c = s2.messages[0]["content"]
    assert isinstance(c, list) and c[0]["type"] == "text", c
    assert "nhận được ảnh" in [e.get("text", "") for e in evs if e["type"] == "assistant_delta"][0]
    n = _conversation_chars(s2.messages)
    assert n > 0 and isinstance(n, int)


# ────────────────────────────────────────────── T7 export ─────────────────
@check("T7 export to_markdown: title, role, tool_calls, ảnh placeholder")
async def t7():
    from engine.export import to_markdown
    store = make_store()
    sid = store.create(title="phiên xuất").id
    s = store.get(sid)
    s.messages = [
        {"role": "user", "content": "sửa file giúp tôi"},
        {"role": "assistant", "content": "Đã sửa.",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "edit_file", "arguments": '{"path":"a.py"}'}}]},
        {"role": "user", "content": [{"type": "text", "text": "còn ảnh này?"},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}}]},
    ]
    md = to_markdown(s)
    assert "# 🗂 phiên xuất" in md and "🧑 Người dùng" in md and "🤖 Agent" in md, md[:200]
    assert "**edit_file**" in md and "🖼 ảnh đính kèm" in md and "sửa file giúp tôi" in md


# ────────────────────────────────────────────── T8 server endpoints ───────
@check("T8 server: /fork 200 · /export 200 markdown · settings web_search roundtrip")
async def t8():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        sid = client.post("/api/sessions", json={"title": "t8"}).json()["session"]["id"]
        r = client.post(f"/api/sessions/{sid}/fork")
        assert r.status_code == 200, r.text
        fork_id = r.json()["session"]["id"]
        assert fork_id != sid
        r2 = client.get(f"/api/sessions/{sid}/export")
        assert r2.status_code == 200 and "text/markdown" in r2.headers["content-type"], r2.text[:100]
        assert "# 🗂" in r2.text
        r3 = client.post("/api/settings", json={"web_search": True,
                                                "allow_commands": ["git *"],
                                                "deny_commands": ["git push *"]})
        assert r3.status_code == 200, r3.text
        body = r3.json()
        assert body["web_search"] is True and body["allow_commands"] == ["git *"], body
        r4 = client.post("/api/settings", json={"web_search": False})
        assert r4.json()["web_search"] is False


@check("T8b chat demo: /customcmd được expand, @file được đính, images demo bỏ qua")
async def t8b():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        sid = client.post("/api/sessions", json={"title": "t8b"}).json()["session"]["id"]
        ws = None
        from engine.session import SessionStore
        ws = SessionStore().workspace(sid)
        d = ws / ".forge" / "commands"; d.mkdir(parents=True, exist_ok=True)
        (d / "deploy.md").write_text("Triển khai lên $ARGUMENTS với @ghi-chu.txt", encoding="utf-8")
        (ws / "ghi-chu.txt").write_text("PORT=8080", encoding="utf-8")
        r = client.post(f"/api/sessions/{sid}/chat",
                        json={"text": "/deploy staging", "mode": "direct"})
        assert r.status_code == 200, r.text[:200]
        for line in r.text.splitlines():
            if line.startswith("data: ") and '"done"' in line:
                break
        else:
            raise AssertionError("không thấy event done")
        s = SessionStore().get(sid)
        last_user = [m for m in s.messages if m["role"] == "user"][-1]["content"]
        assert "Triển khai lên staging" in last_user, last_user[:200]
        assert "PORT=8080" in last_user, "@file phải được đính kèm"
        # images trong demo → note
        r2 = client.post(f"/api/sessions/{sid}/chat",
                         json={"text": "ảnh này?", "mode": "direct",
                               "images": ["data:image/png;base64,iVBORw0KGgo="]})
        s2 = SessionStore().get(sid)
        lu2 = [m for m in s2.messages if m["role"] == "user"][-1]["content"]
        assert "demo mode: bỏ qua 1 ảnh" in lu2, lu2[-200:]


async def main():
    print(f"=== SMOKE v0.8 — data tạm: {TMP} ===")
    for fn in [t1, t1b, t2, t3, t3b, t4, t4b, t5, t6, t7, t8, t8b]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
