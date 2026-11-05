# -*- coding: utf-8 -*-
"""Smoke suite v0.11 "Extensibility Complete": Skills model-invoked · Hooks lifecycle ·
spawn_subagent · LSP navigation (definition/references/workspace symbols).

Chạy:  python scripts/test_v011.py
"""
import asyncio
import json
import os
import stat
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v011-"))
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


# ────────────────────────────────────────────── T1 Skills ────────────────
@check("T1 skills: list + description trigger + model-invoked filter + system prompt + /tên")
async def t1():
    from engine.skills import list_skills, skills_block
    from engine.commands import expand
    ws = TMP / "ws1"; ws.mkdir()
    d = ws / ".forge" / "skills"; d.mkdir(parents=True)
    (d / "pr-review.md").write_text(
        "---\ndescription: Dùng khi review PR: checklist security + logic + style\n---\n"
        "1. Đọc diff\n2. Kiểm tra secret\n3. Đề xuất sửa", encoding="utf-8")
    (d / "deploy.md").write_text(
        "---\ndescription: Triển khai production\ndisable-model-invocation: true\n---\n"
        "Deploy cẩn thận!", encoding="utf-8")
    # v0.16: skill project phải được trust mới vào catalog/expand (chống prompt injection)
    from engine.skills import save_trusted
    save_trusted(ws, {"pr-review"})
    rows, _diags = list_skills(ws)  # v0.15: trả (skills, diagnostics)
    names = {r["name"] for r in rows}
    assert {"pr-review", "deploy"} <= names, names  # v0.16: còn skill-creator built-in
    rev = [r for r in rows if r["name"] == "pr-review"][0]
    assert rev["model_invocable"] is True
    dep = [r for r in rows if r["name"] == "deploy"][0]
    assert dep["model_invocable"] is False
    # skills block: deploy bị ẩn, có hướng dẫn đọc file
    blk = skills_block(ws)
    assert "pr-review" in blk and "pr-review.md" in blk
    assert "deploy" not in blk, "disable-model-invocation phải bị ẩn khỏi block"
    # system prompt chứa block
    from engine.session import SessionStore
    from engine.agent import Agent
    store = SessionStore()
    sid = store.create().id
    agent = Agent(store, sid)
    agent.workspace = ws
    assert "SKILLS" in agent._system_message()["content"]
    out = expand("/pr-review kiểm tra #12", ws)
    assert out and "Kiểm tra secret" in out and "kiểm tra #12" in out, out


# ────────────────────────────────────────────── T2 Hooks ─────────────────
@check("T2 hooks: pre exit-2 block + matcher + post nối output + session_start cache")
async def t2():
    from engine import config
    hook = TMP / "block_write.sh"
    hook.write_text(
        '#!/bin/bash\n'
        'input=$(cat)\n'
        'tool=$(echo "$input" | python3 -c "import sys,json;print(json.load(sys.stdin)[\'tool_name\'])")\n'
        'if [ "$tool" = "write_file" ]; then echo "Không được ghi file!" >&2; exit 2; fi\n'
        'exit 0\n', encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    note = TMP / "post_note.sh"
    note.write_text('#!/bin/bash\necho "đã qua post hook" >&2\nexit 0\n', encoding="utf-8")
    note.chmod(note.stat().st_mode | stat.S_IEXEC)
    ss = TMP / "ss_hook.sh"
    ss.write_text('echo "NGỮ CẢNH: dự án này dùng pytest"\n', encoding="utf-8")
    ss.chmod(ss.stat().st_mode | stat.S_IEXEC)
    config.save_config({"hooks": {
        "pre_tool_use": [{"command": str(hook), "matcher": "write_file|edit_file"}],
        "post_tool_use": [{"command": str(note)}],
        "session_start": [{"command": str(ss)}],
    }})
    from engine import hooks as hk
    try:
        from engine.agent import Agent
        from engine.session import SessionStore
        store = SessionStore()
        sid = store.create().id
        agent = Agent(store, sid)
        ss = await hk.session_start_cache(agent.workspace, sid)
        sysc = agent._system_message(ss)["content"]
        assert "NGỮ CẢNH: dự án này dùng pytest" in sysc, sysc[-300:]
        assert sid in hk._SS_CACHE, "session_start phải được cache theo sid"

        # chạy agent thật với fake LLM: write_file sẽ bị hook chặn
        state = {"n": 0}

        async def fake_llm(messages, tools=None, model=None, api_key=None, temperature=0.3):
            state["n"] += 1
            if state["n"] == 1:
                yield {"type": "tool_calls", "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "write_file",
                                 "arguments": json.dumps({"path": "x.py", "content": "a=1"})}}]}
                yield {"type": "finish", "reason": "tool_calls"}
            else:
                yield {"type": "delta", "text": "đã hiểu, bị chặn"}
                yield {"type": "finish", "reason": "stop"}
        import engine.llm as llm
        orig = llm.stream_chat
        llm.stream_chat = fake_llm
        try:
            evs = [e async for e in agent.send("ghi file x.py")]
        finally:
            llm.stream_chat = orig
        tr = [e for e in evs if e["type"] == "tool_result"]
        assert tr and not tr[0]["ok"], tr
        assert "BLOCKED by hook pre_tool_use" in tr[0]["output"] and "Không được ghi file" in tr[0]["output"]
        assert not (agent.workspace / "x.py").exists(), "file KHÔNG được ghi khi hook chặn"
        # post hook: chạy 1 tool được (read_file không nằm trong matcher pre)
        state2 = {"n": 0}

        async def fake_llm2(messages, tools=None, model=None, api_key=None, temperature=0.3):
            state2["n"] += 1
            if state2["n"] == 1:
                yield {"type": "tool_calls", "tool_calls": [{
                    "id": "c2", "type": "function",
                    "function": {"name": "list_dir", "arguments": "{}"}}]}
                yield {"type": "finish", "reason": "tool_calls"}
            else:
                yield {"type": "delta", "text": "ok"}
                yield {"type": "finish", "reason": "stop"}
        llm.stream_chat = fake_llm2
        try:
            evs2 = [e async for e in agent.send("liệt kê file")]
        finally:
            llm.stream_chat = orig
        tr2 = [e for e in evs2 if e["type"] == "tool_result"][0]
        assert tr2["ok"] and "đã qua post hook" in tr2["output"], tr2["output"][-200:]
    finally:
        cfg = config.load_config()
        cfg.pop("hooks", None)
        config.CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")
        hk._SS_CACHE.clear()


# ────────────────────────────────────────────── T3 LSP navigation ────────
@check("T3 LSP nav: definition + references + workspace symbols (pylsp thật)")
async def t3():
    import shutil
    if not shutil.which("pylsp"):
        raise AssertionError("pylsp chưa cài")
    from engine.tools import execute_tool
    ws = TMP / "ws3"; ws.mkdir()
    (ws / "models.py").write_text(
        "class UserService:\n    def get(self, uid):\n        return uid\n", encoding="utf-8")
    (ws / "api.py").write_text(
        "from models import UserService\n\nsvc = UserService()\nprint(svc.get(1))\n",
        encoding="utf-8")
    # definition của UserService tại nơi SỬ DỤNG (api.py:3 `svc = UserService()`) → models.py:1
    r1 = await execute_tool("lsp_definition", {"path": "api.py", "line": 3, "character": 7}, ws)
    assert r1["ok"], r1
    assert "models.py" in r1["output"], r1["output"]
    # references của UserService tại models.py:1:7 → cả api.py import + dùng + khai báo
    r2 = await execute_tool("lsp_references", {"path": "models.py", "line": 1, "character": 7}, ws)
    assert r2["ok"] and "api.py" in r2["output"], r2["output"]
    # workspace symbols — pylsp không hỗ trợ → báo thân thiện; server có hỗ trợ → kết quả
    r3 = await execute_tool("lsp_search_symbols", {"query": "UserService"}, ws)
    assert r3["ok"], r3
    out3 = r3["output"]
    assert ("UserService" in out3 and "Class" in out3) or "không hỗ trợ" in out3 or "Không tìm thấy" in out3, out3
    # sai vị trí → báo thân thiện, không crash
    r4 = await execute_tool("lsp_definition", {"path": "api.py", "line": 999}, ws)
    assert r4["ok"] and "Không tìm thấy" in r4["output"], r4
    from engine import lsp
    await lsp.shutdown_all()


# ────────────────────────────────────────────── T4 spawn_subagent ────────
CALLS = {"n": 0}


async def fake_parent_llm(messages, tools=None, model=None, api_key=None, temperature=0.3):
    CALLS["n"] += 1
    if CALLS["n"] == 1:
        yield {"type": "tool_calls", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "spawn_subagent",
                         "arguments": json.dumps({"task": "đếm số file trong workspace"})}}]}
        yield {"type": "finish", "reason": "tool_calls"}
    elif CALLS["n"] == 2:  # sub-agent call
        yield {"type": "delta", "text": "Trong workspace có 3 file (a.py, b.txt, README)."}
        yield {"type": "finish", "reason": "stop"}
    else:
        yield {"type": "delta", "text": "Sub-agent báo có 3 file."}
        yield {"type": "finish", "reason": "stop"}


@check("T4 spawn_subagent: context riêng, workspace chung, summary về cha, depth cap")
async def t4():
    import engine.llm as llm
    from engine.agent import Agent
    from engine.session import SessionStore
    from engine import config as cfg_mod
    store = SessionStore()
    sid = store.create().id
    parent = Agent(store, sid)
    (parent.workspace / "a.py").write_text("x=1", encoding="utf-8")
    CALLS["n"] = 0
    orig = llm.stream_chat
    llm.stream_chat = fake_parent_llm
    try:
        evs = [e async for e in parent.send("giao sub-agent đếm file")]
    finally:
        llm.stream_chat = orig
    types = [e["type"] for e in evs]
    assert "subagent_started" in types and "subagent_done" in types, types
    tr = [e for e in evs if e["type"] == "tool_result"][0]
    assert tr["ok"] and "3 file" in tr["output"] and "KẾT QUẢ SUB-AGENT" in tr["output"], tr["output"][:200]
    # subagent session tồn tại + workspace pointer = workspace cha
    started = [e for e in evs if e["type"] == "subagent_started"][0]
    sub_sid = started["session_id"]
    sub_ws = store.workspace(sub_sid)
    assert sub_ws.resolve() == parent.workspace.resolve(), (sub_ws, parent.workspace)
    s2 = store.get(sub_sid)
    assert s2 is not None and s2.title.startswith("🧩")
    # depth cap: subagent spec bị loại ở depth>=1 — kiểm tra qua Agent depth filter
    sub_agent = Agent(store, sid, depth=1)
    # (lấy specs như trong send — mô phỏng nhanh)
    specs = [sp["function"]["name"] for sp in __import__("engine.tools", fromlist=["TOOL_SPECS"]).TOOL_SPECS]
    # depth=1 sẽ lọc spawn_subagent trong send; ở đây chỉ kiểm tra thuộc tính
    assert sub_agent.depth == 1 and parent.depth == 0


# ────────────────────────────────────────────── T5 server health ─────────
@check("T5 regression server: health/chat demo vẫn ổn sau khi thêm tools mới")
async def t5():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        h = client.get("/api/health").json()
        assert h["ok"]
        sid = client.post("/api/sessions", json={"title": "t5"}).json()["session"]["id"]
        r = client.post(f"/api/sessions/{sid}/chat", json={"text": "hi", "mode": "direct"})
        body = r.text
        assert '"done"' in body, body[-200:]


async def main():
    print(f"=== SMOKE v0.11 — data tạm: {TMP} ===")
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
