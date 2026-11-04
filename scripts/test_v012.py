# -*- coding: utf-8 -*-
"""Smoke suite v0.12 "Memory & Review":
@imports (AGENTS.md/MEMORY.md) · '#' quick-memory · /memory overview+clear ·
/review + /diff (git repo & checkpoint) · server endpoints.

Chạy:  python scripts/test_v012.py
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v012-"))
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


# ────────────────────────────────────────────── T1 @imports ──────────────
@check("T1 @imports: nạp đệ quy, bỏ qua fence/inline-code, chống vòng, giữ literal, cap 8KB")
async def t1():
    from engine.context_files import load_with_imports
    from engine.agent import _agents_md_block

    ws = TMP / "ws1"; (ws / "docs").mkdir(parents=True)
    (ws / "AGENTS.md").write_text(
        "# Quy tắc dự án\n@docs/extra.md\n"
        "```\n@docs/fence-secret.md\n```\n"
        "Ghi chú `@docs/inline-secret.md` nằm trong code span\n"
        "@docs/khongton-tai.md\n", encoding="utf-8")
    (ws / "docs/extra.md").write_text("QUY_TAC_DAC_BIET=42\n@nested.md\n", encoding="utf-8")
    (ws / "docs/nested.md").write_text("NESTED_OK\n", encoding="utf-8")
    (ws / "docs/fence-secret.md").write_text("FENCE_SECRET_MARKER\n", encoding="utf-8")
    (ws / "docs/inline-secret.md").write_text("INLINE_SECRET_MARKER\n", encoding="utf-8")

    blk = _agents_md_block(ws)
    assert "QUY_TAC_DAC_BIET=42" in blk, blk[:400]
    assert "NESTED_OK" in blk, "import đệ quy (tương đối với file chứa) thất bại"
    assert "FENCE_SECRET_MARKER" not in blk, "không được import trong code fence"
    assert "INLINE_SECRET_MARKER" not in blk, "không được import trong inline code span"
    assert "@docs/khongton-tai.md" in blk, "file không tồn tại → giữ nguyên chữ"

    # vòng lặp
    (ws / "a.md").write_text("A_CONTENT\n@b.md\n", encoding="utf-8")
    (ws / "b.md").write_text("B_CONTENT\n@a.md\n", encoding="utf-8")
    out = load_with_imports(ws / "a.md")
    assert "A_CONTENT" in out and "B_CONTENT" in out, out
    assert "vòng lặp" in out, out

    # cap 8KB cho import lồng
    big = TMP / "ws1" / "big.md"
    big.write_text("X" * 20_000 + "\nBIG_END\n", encoding="utf-8")
    (ws / "usebig.md").write_text("@big.md\n", encoding="utf-8")
    out2 = load_with_imports(ws / "usebig.md")
    assert "cắt ở 8KB" in out2 and "BIG_END" not in out2, out2[-120:]


# ────────────────────────────────────────────── T2 # quick-memory ────────
@check("T2 '# ' quick-memory: ghi MEMORY.md không gọi LLM, chống trùng, demo cũng chạy")
async def t2():
    from engine.session import SessionStore
    from engine.agent import Agent, send_demo
    import engine.llm as llm

    async def boom(*a, **k):
        raise AssertionError("LLM KHÔNG được gọi cho '# ' quick-memory")
    orig = llm.stream_chat
    llm.stream_chat = boom
    try:
        store = SessionStore()
        sid = store.create().id
        agent = Agent(store, sid)
        evs = [e async for e in agent.send("# luôn dùng pytest -q khi chạy test")]
        kinds = [e["type"] for e in evs]
        assert "assistant_message" in kinds and "turn_end" in kinds, kinds
        msg = [e for e in evs if e["type"] == "assistant_message"][0]["content"]
        assert msg.startswith("🧠") and "pytest" in msg, msg
        mem = (agent.workspace / "MEMORY.md").read_text(encoding="utf-8")
        assert "luôn dùng pytest -q" in mem
        # trùng
        evs2 = [e async for e in agent.send("# luôn dùng pytest -q khi chạy test")]
        msg2 = [e for e in evs2 if e["type"] == "assistant_message"][0]["content"]
        assert "bỏ qua trùng" in msg2, msg2
        # text thường KHÔNG bị nhánh # chặn
        state = {"n": 0}

        async def fake_llm(messages, tools=None, model=None, api_key=None, temperature=0.3):
            state["n"] += 1
            yield {"type": "delta", "text": "xin chào"}
            yield {"type": "finish", "reason": "stop"}
        llm.stream_chat = fake_llm
        try:
            evs3 = [e async for e in agent.send("xin chào bình thường")]
        finally:
            llm.stream_chat = boom
        assert state["n"] == 1 and any(e["type"] == "assistant_message" for e in evs3)
        # demo mode cũng chạy #
        store2 = SessionStore()
        sid2 = store2.create().id
        agent2 = Agent(store2, sid2)
        evs4 = [e async for e in send_demo(agent2, "# ghi nhớ demo mode")]
        assert any(e["type"] == "assistant_message" and "🧠" in e.get("content", "")
                   for e in evs4), [e["type"] for e in evs4]
        assert "ghi nhớ demo mode" in (agent2.workspace / "MEMORY.md").read_text(encoding="utf-8")
    finally:
        llm.stream_chat = orig


# ────────────────────────────────────────────── T3 /memory overview+clear ─
@check("T3 /memory: overview đúng số liệu + clear có .bak")
async def t3():
    from engine.memory import append_entry, memory_overview, clear_memory
    from engine import config
    ws = TMP / "ws3"; ws.mkdir()
    append_entry(ws, "quy tắc một")
    append_entry(ws, "quy tắc hai")
    (config.DATA_DIR / "AGENTS.md").write_text("GLOBAL_RULE_X\n", encoding="utf-8")
    ov = memory_overview(ws)
    assert "Quy tắc toàn cục" in ov and "✓" in ov, ov
    assert "2 ghi nhớ" in ov, ov
    assert "quy tắc hai" in ov, "ghi nhớ gần nhất phải hiện"
    cl = clear_memory(ws)
    assert "🗑" in cl and not (ws / "MEMORY.md").exists()
    assert (ws / "MEMORY.md.bak").read_text(encoding="utf-8").count("quy tắc") == 2


# ────────────────────────────────────────────── T4 /review + /diff ───────
def _gitrun(ws, *args):
    subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@check("T4 review/diff: git repo (mặc định, file, ref range) + checkpoint phiên + prompt chuẩn")
async def t4():
    from engine.review import collect_diff, build_prompt
    from engine import checkpoints

    ws = TMP / "ws4"; ws.mkdir()
    _gitrun(ws, "init", "-q")
    (ws / "app.py").write_text("print('base')\n", encoding="utf-8")
    _gitrun(ws, "add", "."); _gitrun(ws, "commit", "-qm", "base")
    (ws / "app.py").write_text("print('base')\nprint('sua moi')\n", encoding="utf-8")
    (ws / "extra.py").write_text("x = 1\n", encoding="utf-8")

    d1, l1 = await collect_diff(ws, None, "")
    assert "sua moi" in d1 and "extra.py" in d1 and "HEAD" in l1
    d2, _ = await collect_diff(ws, None, "app.py")
    assert "sua moi" in d2 and "extra.py" not in d2
    # focus dạng câu → vẫn lấy diff mặc định
    d3, _ = await collect_diff(ws, None, "tập trung vào bảo mật")
    assert "sua moi" in d3

    base_branch = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=ws,
                                 capture_output=True, text=True).stdout.strip()
    _gitrun(ws, "checkout", "-qb", "feature")
    (ws / "feat.py").write_text("y = 2\n", encoding="utf-8")
    _gitrun(ws, "add", "."); _gitrun(ws, "commit", "-qm", "feat")
    d4, l4 = await collect_diff(ws, None, f"{base_branch}...feature")
    assert "feat.py" in d4, (d4[:200], l4)

    prompt = build_prompt(d1, "", l1)
    assert "Verdict" in prompt and "[P0" in prompt and "ƯA" in prompt
    assert "```diff" in prompt and "sua moi" in prompt

    # checkpoint: workspace KHÔNG phải repo, có snapshot đầu phiên
    from engine import config
    ws2 = config.WORKSPACES_DIR / "ws-ckpt"; ws2.mkdir(parents=True, exist_ok=True)
    (ws2 / "doc.txt").write_text("ban dau\n", encoding="utf-8")
    assert await checkpoints.snapshot("sid-t4", ws2, "test") is not None
    (ws2 / "doc.txt").write_text("ban dau\nsua sau snapshot\n", encoding="utf-8")
    (ws2 / "moi.txt").write_text("file them\n", encoding="utf-8")
    dc, lc = await collect_diff(ws2, "sid-t4", "")
    assert "sua sau snapshot" in dc and "moi.txt" in dc and "checkpoint" in lc, lc

    # không repo, không ckpt → lỗi thân thiện
    ws3 = TMP / "ws-trong"; ws3.mkdir()
    try:
        await collect_diff(ws3, None, "")
        raise AssertionError("phải raise ValueError")
    except ValueError as e:
        assert "Không có thay đổi nào" in str(e)


# ────────────────────────────────────────────── T5 server endpoints ──────
@check("T5 server: /memory, '# ' (demo), /diff không repo — synthetic stream đúng")
async def t5():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ok"]
        sid = client.post("/api/sessions", json={"title": "t5"}).json()["session"]["id"]
        r = client.post(f"/api/sessions/{sid}/chat", json={"text": "/memory", "mode": "agent"})
        assert "Bộ nhớ đang nạp" in r.text, r.text[-300:]
        r = client.post(f"/api/sessions/{sid}/chat",
                        json={"text": "# server ghi nhớ này", "mode": "agent"})
        assert "🧠" in r.text, r.text[-300:]
        from engine.session import SessionStore
        ws = SessionStore().workspace(sid)
        assert "server ghi nhớ này" in (ws / "MEMORY.md").read_text(encoding="utf-8")
        r = client.post(f"/api/sessions/{sid}/chat", json={"text": "/diff", "mode": "agent"})
        assert "Không có thay đổi nào" in r.text
        # seed thay đổi qua checkpoint → /review (demo) + /diff có dữ liệu
        from engine import checkpoints
        (ws / "goc.txt").write_text("goc\n", encoding="utf-8")
        assert await checkpoints.snapshot(sid, ws, "t5") is not None
        (ws / "sau.py").write_text("moi = 1\n", encoding="utf-8")
        r = client.post(f"/api/sessions/{sid}/chat", json={"text": "/review", "mode": "agent"})
        assert "demo mode" in r.text, "(demo) /review phải báo cần key, không gọi LLM: " + r.text[-200:]
        r = client.post(f"/api/sessions/{sid}/chat", json={"text": "/diff", "mode": "agent"})
        assert "Diff —" in r.text and "sau.py" in r.text, r.text[-300:]
        assert client.post(f"/api/sessions/{sid}/chat",
                           json={"text": "hi", "mode": "direct"}).status_code == 200


async def main():
    print(f"=== SMOKE v0.12 — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4]:
        await fn()
    # T5 (TestClient) chạy trong TIẾN TRÌNH RIÊNG: loop test này đã dùng
    # create_subprocess_exec — portal của TestClient xung đột child-watcher
    # khi cùng loop → body parse sai. Tách tiến trình là sạch nhất.
    r = subprocess.run([sys.executable, __file__, "--t5"],
                       capture_output=True, text=True, timeout=180)
    tail = (r.stdout + r.stderr).strip().splitlines()
    ok_line = [l for l in tail if l.startswith("T5RESULT:")]
    if r.returncode == 0 and ok_line:
        PASS.append("T5 server (tiến trình riêng)")
        print("  ✓ T5 server: /memory, '# ' (demo), /diff + /review checkpoint — synthetic đúng")
    else:
        err = " | ".join(tail[-3:])[:300]
        FAIL.append(("T5 server", err))
        print(f"  ✗ T5 server: {err}")

    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


async def t5_only():
    await t5()
    print(f"T5RESULT:{PASS[0] if PASS else ''}")
    return 0


if __name__ == "__main__":
    if "--t5" in sys.argv:
        sys.exit(asyncio.run(t5_only()))
    sys.exit(asyncio.run(main()))
