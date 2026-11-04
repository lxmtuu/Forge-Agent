# -*- coding: utf-8 -*-
"""Smoke suite v0.10 "Gap Closer": memory · LSP tools · hooks · custom agents ·
network kill-switch · /context · /doctor · /run · --json · diff TUI.

Chạy:  python scripts/test_v010.py
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

TMP = Path(tempfile.mkdtemp(prefix="forge-v010-"))
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


# ────────────────────────────────────────────── T1 auto-memory ────────────
@check("T1 memory_save: ghi MEMORY.md, nạp vào system prompt, chống trùng, cap 8KB")
async def t1():
    from engine.tools import execute_tool
    ws = TMP / "ws1"; ws.mkdir()
    r = await execute_tool("memory_save", {"content": "Dự án dùng pytest; chạy: pytest -q"}, ws)
    assert r["ok"] and "MEMORY.md" in r["output"], r
    mem = ws / "MEMORY.md"
    assert mem.exists() and "pytest -q" in mem.read_text(encoding="utf-8")
    # trùng → bỏ qua
    r2 = await execute_tool("memory_save", {"content": "Dự án dùng pytest; chạy: pytest -q"}, ws)
    assert "trùng" in r2["output"], r2
    # nạp vào system prompt
    from engine.session import SessionStore
    from engine.agent import Agent
    store = SessionStore()
    sid = store.create().id
    agent = Agent(store, sid)
    agent.workspace = ws
    sysc = agent._system_message()["content"]
    assert "LONG-TERM MEMORY" in sysc and "pytest -q" in sysc
    # cap 8KB: ghi nhiều entry dài → file ≤ ~8.5KB, entry mới nhất còn
    for i in range(30):
        await execute_tool("memory_save", {"content": f"ý {i}: " + "x" * 400}, ws)
    size = mem.stat().st_size
    assert size < 9000, size
    assert "ý 29" in mem.read_text(encoding="utf-8"), "entry mới nhất phải được giữ"
    # context_stats phản ánh memory
    st = agent.context_stats()
    assert st["memory"] is True and st["chars"] > 0


# ────────────────────────────────────────────── T2 LSP tools ──────────────
@check("T2 lsp_symbols + lsp_diagnostics qua execute_tool (pylsp)")
async def t2():
    import shutil
    if not shutil.which("pylsp"):
        raise AssertionError("pylsp chưa cài")
    from engine.tools import execute_tool
    ws = TMP / "ws2"; ws.mkdir()
    f = ws / "mod.py"
    f.write_text("class XinChao:\n    def chao(self):\n        return 'hi'\n\n\ndef ham_tu_do():\n    pass\n",
                 encoding="utf-8")
    r1 = await execute_tool("lsp_symbols", {"path": "mod.py"}, ws)
    assert r1["ok"], r1
    out1 = r1["output"]
    assert "XinChao" in out1 and "ham_tu_do" in out1 and "Class" in out1, out1
    bad = ws / "bad.py"
    bad.write_text("y = khong_bien_do\n", encoding="utf-8")
    r2 = await execute_tool("lsp_diagnostics", {"path": "bad.py"}, ws)
    assert r2["ok"] and "⛔" in r2["output"] and "khong_bien_do" in r2["output"], r2
    r3 = await execute_tool("lsp_diagnostics", {"path": "khongco.py"}, ws)
    assert not r3["ok"]
    (ws / "ghi-chu.txt").write_text("chú thích", encoding="utf-8")
    r4 = await execute_tool("lsp_diagnostics", {"path": "ghi-chu.txt"}, ws)
    assert r4["ok"] and "không phải file code" in r4["output"], r4
    from engine import lsp
    await lsp.shutdown_all()


# ────────────────────────────────────────────── T3 hook on_file_change ────
@check("T3 hook on_file_change: chạy sau write_file, output được nối vào kết quả")
async def t3():
    from engine import config
    from engine.tools import execute_tool
    config.save_config({"on_file_change": f"echo hook-nhan-file:$FORGE_CHANGED_FILE"})
    try:
        ws = TMP / "ws3"; ws.mkdir()
        r = await execute_tool("write_file", {"path": "a.py", "content": "x = 1\n"}, ws)
        assert "Hook on_file_change" in r["output"], r["output"][-200:]
        assert "hook-nhan-file:a.py" in r["output"], r["output"][-200:]
        # hook cho memory_save KHÔNG chạy
        r2 = await execute_tool("memory_save", {"content": "ghi nhớ test hook"}, ws)
        assert "Hook" not in r2["output"], r2
    finally:
        config.save_config({"on_file_change": None})
        cfg = config.load_config(); cfg.pop("on_file_change", None)
        config.CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")


# ────────────────────────────────────────────── T4 custom agents ──────────
@check("T4 custom agents: frontmatter model/mode, expand /run, list_agents, ưu tiên project")
async def t4():
    from engine.agents import expand, list_agents
    ws = TMP / "ws4"; ws.mkdir()
    d = ws / ".forge" / "agents"; d.mkdir(parents=True)
    (d / "reviewer.md").write_text(
        "---\ndescription: Review code kỹ\nmodel: openrouter/free\nmode: plan\n---\n"
        "Bạn là reviewer khắt khe. Luôn liệt kê vấn đề theo mức độ nghiêm trọng.", encoding="utf-8")
    g = TMP / "data" / "forge" / "agents"; g.mkdir(parents=True, exist_ok=True)
    (g / "helper.md").write_text("Bạn là trợ lý nhanh.", encoding="utf-8")
    exp = expand("/run reviewer kiểm tra api.py", ws)
    assert exp is not None
    text, model, mode = exp
    assert model == "openrouter/free" and mode == "plan", (model, mode)
    assert "reviewer khắt khe" in text and "kiểm tra api.py" in text and "AGENT RULES" in text
    assert expand("/run khongco x", ws) is None
    assert expand("bình thường", ws) is None
    rows = list_agents(ws)
    names = {r["name"] for r in rows}
    assert {"reviewer", "helper"} <= names, names
    assert any(r["description"] == "Review code kỹ" for r in rows)
    # project đè global
    (d / "helper.md").write_text("PROJECT-HELPER", encoding="utf-8")
    rows2 = {r["name"]: r for r in list_agents(ws)}
    exp2 = expand("/run helper làm việc", ws)
    assert "PROJECT-HELPER" in exp2[0]


# ────────────────────────────────────────────── T5 network kill-switch ────
@check("T5 block_network: curl/pip/git push → danger; echo vẫn safe")
async def t5():
    from engine import config, guard
    orig = config.load_config
    config.load_config = lambda: {"block_network": True}
    try:
        for cmd in ("curl https://x.com", "pip install requests", "git push origin",
                    "npm install left-pad", "wget http://a.b"):
            v = guard.assess_command(cmd)
            assert v["level"] == "danger", (cmd, v)
        v = guard.assess_command("echo safe")
        assert v["level"] == "safe", v
    finally:
        config.load_config = orig
    config.load_config = lambda: {}
    try:
        assert guard.assess_command("curl https://x.com")["level"] == "warn"
    finally:
        config.load_config = orig


# ────────────────────────────────────────────── T6 /context ───────────────
@check("T6 context_stats: chars/percent/messages + server endpoint")
async def t6():
    from engine.agent import Agent
    from engine.session import SessionStore
    store = SessionStore()
    sid = store.create().id
    sess = store.get(sid)
    for i in range(6):
        sess.messages.append({"role": "user" if i % 2 == 0 else "assistant",
                              "content": "nội dung " * 30})
    store.save(sess)
    ctx = Agent(store, sid).context_stats()
    assert ctx["messages"] == 6 and ctx["chars"] > 500 and ctx["est_tokens"] > 100, ctx
    assert ctx["limit"] == 150000 and ctx["percent"] is not None and 0 < ctx["percent"] < 5, ctx
    # server
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        r = client.get(f"/api/sessions/{sid}/context")
        assert r.status_code == 200 and r.json()["messages"] == 6, r.text
        rd = client.get("/api/doctor")
        assert rd.status_code == 200, rd.text
        rep = rd.json()
        names = {c["name"] for c in rep["checks"]}
        assert {"Python", "API key OpenRouter", "git + checkpoints", "Auto-compact",
                "MCP servers", "Guard", "Dữ liệu"} <= names, names
        assert "/" in rep["summary"]


# ────────────────────────────────────────────── T7 /run qua server ────────
@check("T7 server chat /run: AGENT RULES vào message (demo) + mode override")
async def t7():
    from fastapi.testclient import TestClient
    from server.main import app
    from engine.session import SessionStore
    with TestClient(app) as client:
        sid = client.post("/api/sessions", json={"title": "t7"}).json()["session"]["id"]
        ws = SessionStore().workspace(sid)
        d = ws / ".forge" / "agents"; d.mkdir(parents=True, exist_ok=True)
        (d / "reviewer.md").write_text(
            "---\ndescription: Review\nmode: direct\n---\nBạn là reviewer.", encoding="utf-8")
        r = client.post(f"/api/sessions/{sid}/chat",
                        json={"text": "/run reviewer soi code giúp", "mode": "agent"})
        assert r.status_code == 200, r.text[:200]
        s = SessionStore().get(sid)
        last = [m for m in s.messages if m["role"] == "user"][-1]["content"]
        assert "AGENT RULES" in last and "Bạn là reviewer" in last and "soi code giúp" in last, last[:200]


# ────────────────────────────────────────────── T8 --json headless ────────
@check("T8 forge --once --json: đầu ra JSON hợp lệ (text/tools/usage)")
async def t8():
    env = {**os.environ, "FORGE_DATA_DIR": str(TMP / "data-json")}
    env.pop("OPENROUTER_API_KEY", None)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "cli" / "main.py"),
        "--once", "xin chào json", "--json",
        cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        raise AssertionError("timeout")
    out_s = out.decode("utf-8", "replace")
    assert proc.returncode == 0, (proc.returncode, out_s[-300:], err.decode()[-300:])
    data = json.loads(out_s[out_s.index("{"):])
    assert data["session"], data.keys()
    assert "text" in data and "tools" in data and "usage" in data, data.keys()
    assert len(data["text"]) > 10, data["text"][:100]  # demo text


# ────────────────────────────────────────────── T9 diff rich TUI ──────────
@check("T9 _diff_rich: green/red/cyan styles + cap 40 dòng")
async def t9():
    from tui.app import _diff_rich
    diff = "--- a/f.py\n+++ b/f.py\n@@ -1,2 +1,2 @@\n-x = 1\n+x = 2\n context\n"
    t = _diff_rich(diff)
    plain = t.plain
    assert "+x = 2" in plain and "-x = 1" in plain
    # nhiều dòng → cap
    big = "\n".join(f"+dòng {i}" for i in range(100))
    t2 = _diff_rich(big)
    assert "còn 60 dòng" in t2.plain
    # spans có màu
    styles = {sp.style for sp in t.spans}
    assert any("green" in str(sty) for sty in styles), styles


async def main():
    print(f"=== SMOKE v0.10 — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4, t5, t6, t7, t8, t9]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
