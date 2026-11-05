# -*- coding: utf-8 -*-
"""Suite v0.32 "Autonomy nâng cao":
A5 repo map (regex symbols + rank refs + budget + auto-nạp) ·
C1 hook events mới (user_prompt_submit chặn / stop / pre_compact chặn nén / notification) ·
A4 sub-agent NỀN (spawn_background → lead không chặn, xong tự nhét hộp thư + agent_completed).

Chạy:  python scripts/test_v032.py
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

TMP = Path(tempfile.mkdtemp(prefix="forge-v032-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
os.environ.pop("OPENROUTER_API_KEY", None)   # demo mode — turn chạy thật không tốn key
os.environ.pop("FORGE_PROFILE", None)

PASS, FAIL = [], []
PY = f'"{sys.executable}"'


def install_mock_llm():
    """Demo trajectory nằm ở SERVER — engine send() cần key thật. Mock stream_chat
    (factory hàm THƯỜNG trả async-gen — bài học v0.23)."""
    import engine.llm as fllm

    def fake_stream(messages, tools=None, model=None, temperature=None, **kw):
        async def _gen():
            yield {"type": "delta", "text": "Đã ghi nhận (mock v032)."}
            yield {"type": "done"}
        return _gen()

    fllm.stream_chat = fake_stream


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


def mk_ws() -> Path:
    ws = Path(tempfile.mkdtemp(prefix="ws032-", dir=TMP))
    return ws


def set_hooks(ws: Path, hooks: dict) -> None:
    d = ws / ".forge"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")


@check("T1 A5 repo map: symbol đúng · rank theo refs chéo (core trước app) · cache · budget cắt · >60 file không auto-nạp")
async def t1():
    from engine import repomap as frm
    ws = mk_ws()
    (ws / "core.py").write_text("class Engine:\n    def start(self):\n        pass\n"
                                "\n\ndef helper():\n    return Engine\n", encoding="utf-8")
    (ws / "app.py").write_text("from core import Engine, helper\n\n"
                               "def main():\n    e = Engine()\n    helper()\n    return e\n", encoding="utf-8")
    (ws / "docs.md").write_text("# notes\nEngine được nhắc ở đây\n", encoding="utf-8")
    r = frm.build(ws)
    assert r["files"] == 3 and r["symbols"] >= 3, r
    lines = r["map"].splitlines()
    assert any(ln.startswith("core.py") and "(2 refs)" in ln for ln in lines), lines
    assert lines[1].startswith("core.py"), f"rank sai — core phải trước: {lines[:3]}"
    r2 = frm.build(ws)
    assert r2["cached"] is True, "cache phải hit khi file không đổi"
    # budget cắt
    r3 = frm.build(ws, budget=30)
    assert r3["truncated"] is True and len(r3["map"]) < 200, r3
    # >60 file → auto_context rỗng (không đốt token)
    big = mk_ws()
    for i in range(65):
        (big / f"f{i:02}.txt").write_text("x" * 10, encoding="utf-8")
    assert frm.auto_context(big) == "", "workspace lớn KHÔNG được tự nạp"
    assert frm.auto_context(mk_ws()) == "", "workspace rỗng KHÔNG được tự nạp header 0-file"
    assert "Bản đồ workspace" in frm.auto_context(ws)
    # mọi file được quét (không chỉ 200 file đầu) phải làm cache mất hiệu lực khi đổi
    wide = mk_ws()
    for i in range(205):
        (wide / f"f{i:03}.txt").write_text(f"noi dung {i}", encoding="utf-8")
    assert frm.build(wide)["cached"] is False
    assert frm.build(wide)["cached"] is True
    tail = wide / "f204.txt"
    st = tail.stat()
    tail.write_text("noi dung 204 DA DOI", encoding="utf-8")
    os.utime(tail, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert frm.build(wide)["cached"] is False, "file sau phần tử 200 đổi nhưng cache vẫn hit"


@check("T2 tools mới trong TOOLS_LIST (đủ wrapper) + method Agent tồn tại + map vào system prompt workspace nhỏ")
async def t2():
    from engine import tools as ft
    names = {sp["function"]["name"] for sp in ft.TOOL_SPECS}
    for n in ("repo_map", "spawn_background_agent", "check_background_agents"):
        assert n in names, f"thiếu spec {n}"
    for sp in ft.TOOL_SPECS:
        assert sp.get("type") == "function" and "parameters" in sp["function"]
    from engine.agent import Agent, READ_ONLY_TOOLS, _BG_AGENTS, MAX_BG_AGENTS_PER_LEAD
    assert {"repo_map", "check_background_agents"} <= READ_ONLY_TOOLS
    assert "spawn_background_agent" not in READ_ONLY_TOOLS, "tool tạo tác vụ không thuộc Plan read-only"
    for meth in ("spawn_background", "bg_status", "_bg_agent_run", "_repomap_block", "_notify"):
        assert hasattr(Agent, meth), f"Agent thiếu {meth}"
    assert MAX_BG_AGENTS_PER_LEAD == 3
    from cli.main import HELP
    assert "/repomap" in HELP, "lệnh mới phải hiện trong CLI help"
    assert "/repomap [budget]" in (ROOT / "tui" / "app.py").read_text(encoding="utf-8")
    # system prompt workspace nhỏ phải chứa map; depth>0 (sub) thì không
    from engine.session import SessionStore
    store = SessionStore()
    ws = mk_ws()
    (ws / "a.py").write_text("def top_level_fn():\n    pass\n", encoding="utf-8")
    sid = store.create().id
    (store.workspace(sid)).mkdir(parents=True, exist_ok=True)
    (store.workspace(sid) / "a.py").write_text("def top_level_fn():\n    pass\n", encoding="utf-8")
    ag = Agent(store, sid)
    sys_txt = ag._system_message()["content"]
    assert "Bản đồ workspace (repo map" in sys_txt, sys_txt[-300:]
    ag.depth = 1
    assert "Bản đồ workspace" not in ag._system_message()["content"]


@check("T3 C1 user_prompt_submit: exit 2 CHẶN prompt (không gọi LLM) · exit 0 đi qua + hook nhận đủ payload")
async def t3():
    from engine.agent import Agent
    from engine.session import SessionStore
    store = SessionStore()
    ws_block = mk_ws()
    sid = store.create().id
    set_hooks(store.workspace(sid), {"user_prompt_submit": [
        {"command": f'{PY} -c "import sys; sys.exit(2)"'}]})
    ag = Agent(store, sid)
    events = [e async for e in ag.send("xin chào", chat_mode="direct")]
    kinds = [e["type"] for e in events]
    assert "assistant_message" in kinds and "turn_end" in kinds, kinds
    assert not any(k in kinds for k in ("tool_start", "tool_result", "error")), kinds
    msg = next(e["content"] for e in events if e["type"] == "assistant_message")
    assert "chặn" in msg.lower(), msg
    # exit 0 + ghi payload ra file
    ws_pass = mk_ws()
    sid2 = store.create().id
    out_file = ws_pass / "ups_payload.json"
    set_hooks(store.workspace(sid2), {"user_prompt_submit": [
        {"command": f'{PY} -c "import json,sys; json.dump(json.load(sys.stdin), open(r\'{out_file}\', \'w\', encoding=\'utf-8\'))"'}]})
    ag2 = Agent(store, sid2)
    ev2 = [e async for e in ag2.send("câu hỏi thật", chat_mode="direct")]
    assert any(e["type"] == "assistant_message" for e in ev2), ev2
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["hook_event_name"] == "user_prompt_submit"
    assert "câu hỏi thật" in payload["prompt"] and payload["session_id"] == sid2


@check("T4 C1 pre_compact exit 2 chặn nén · stop hook chạy cuối lượt (payload có mode)")
async def t4():
    from engine.agent import Agent, compact_session
    from engine.session import SessionStore
    store = SessionStore()
    ws = mk_ws()
    sid = store.create().id
    out_pc = ws / "pc_payload.json"
    out_stop = ws / "stop_payload.json"
    set_hooks(store.workspace(sid), {
        "pre_compact": [{"command": f'{PY} -c "import sys; sys.exit(2)"'}],
        "stop": [{"command": f'{PY} -c "import json,sys; json.dump(json.load(sys.stdin), open(r\'{out_stop}\', \'w\', encoding=\'utf-8\'))"'}],
    })
    ag = Agent(store, sid)
    s = ag.session
    for i in range(6):
        s.messages.append({"role": "user", "content": f"tin {i}"})
        s.messages.append({"role": "assistant", "content": "trả lời"})
    store.save(s)
    res = await compact_session(ag)
    assert res["ok"] is False and "chặn" in res["message"], res
    # stop hook: chạy 1 lượt demo direct → file phải xuất hiện
    ev = [e async for e in ag.send("kiểm tra stop hook", chat_mode="direct")]
    assert any(e["type"] == "turn_end" for e in ev)
    assert out_stop.exists(), "stop hook không chạy!"
    payload = json.loads(out_stop.read_text(encoding="utf-8"))
    assert payload["hook_event_name"] == "stop" and payload["mode"] == "direct"


@check("T5 A4 bg-agent THẬT (demo mode): spawn trả NGAY running → done · tóm tắt tự vào hộp thư lead · notification agent_completed")
async def t5():
    from engine import bus as fbus
    from engine.agent import Agent, _BG_AGENTS
    from engine.session import SessionStore
    store = SessionStore()
    ws = mk_ws()
    sid = store.create().id
    out_n = ws / "notif_payload.json"
    set_hooks(store.workspace(sid), {"notification": [
        {"command": f'{PY} -c "import json,sys; json.dump(json.load(sys.stdin), open(r\'{out_n}\', \'w\', encoding=\'utf-8\'))"'}]})
    lead = Agent(store, sid)
    spawn = await lead.spawn_background("tạo file bg_kiem.py chứa hàm hello()", None, "shared")
    assert spawn["ok"], spawn
    bg_id, sub_sid = spawn["bg_id"], spawn["sub_sid"]
    assert _BG_AGENTS[bg_id]["status"] == "running"
    assert _BG_AGENTS[bg_id]["lead_sid"] == sid
    import time as _t
    deadline = _t.monotonic() + 60
    while _BG_AGENTS[bg_id]["status"] == "running":
        await asyncio.sleep(0.15)
        assert _t.monotonic() < deadline, "bg-agent quá 60s"
    entry = _BG_AGENTS[bg_id]
    assert entry["status"] in ("done", "error"), entry
    # hộp thư lead nhận tóm tắt tự động (F2 + A4 bắt tay)
    inbox = fbus.peek(sid)
    assert any("bg-agent" in r["text"] and bg_id in r["text"] for r in inbox), inbox[:2]
    # notification hook nhận agent_completed
    import time as _t2
    deadline2 = _t2.monotonic() + 10
    while not out_n.exists():
        await asyncio.sleep(0.1)
        assert _t2.monotonic() < deadline2
    payload = json.loads(out_n.read_text(encoding="utf-8"))
    assert payload["notification_type"] == "agent_completed" and payload["bg_id"] == bg_id
    # bg_status là nguồn cho check_background_agents
    rows = lead.bg_status()
    assert rows and rows[0]["bg_id"] == bg_id and rows[0]["sub_sid"] == sub_sid


async def main():
    print(f"=== SUITE v0.32 Autonomy nâng cao — data tạm: {TMP} ===")
    install_mock_llm()
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
