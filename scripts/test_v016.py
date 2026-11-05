# -*- coding: utf-8 -*-
"""Smoke suite v0.16 "Skills P1 — Trust & Creator":
S4 tài nguyên skill (script chạy thật qua shell) · S5 trust gating (chống prompt injection)
· S6 skill-creator built-in · /skills trust · blocked_reason.

Chạy:  python scripts/test_v016.py
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

TMP = Path(tempfile.mkdtemp(prefix="forge-v016-"))
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


def ws_tmp(tag: str) -> Path:
    w = TMP / f"ws-{tag}"
    w.mkdir(parents=True, exist_ok=True)
    return w


def _skill(dirpath: Path, name: str, fm: str, body: str = "# Bước\n1. Làm.") -> Path:
    d = dirpath / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")
    return d


# ─────────────────────────── T1 trust gating trong catalog ────────────────
@check("T1 catalog: skill project CHƯA tin bị ẩn khỏi model, user vẫn hiện; trust xong thì hiện")
async def t1():
    import engine.skills as sk
    w = ws_tmp("t1")
    _skill(w / ".forge" / "skills", "rieng-tu",
           'name: rieng-tu\ndescription: skill project chưa tin')
    _skill(w / ".forge" / "skills", "tay-only",
           'name: tay-only\ndescription: tắt model invocation\ndisable-model-invocation: true')
    home = TMP / "home-t1"; home.mkdir(exist_ok=True)
    _skill(home / ".forge" / "skills", "skill-user",
           'name: skill-user\ndescription: skill user luôn tin')
    orig_home = Path.home
    Path.home = lambda: home
    try:
        blk = sk.skills_block(w)
        assert "skill-user" in blk, "skill user phải vào catalog"
        assert "rieng-tu" not in blk, "skill project chưa tin KHÔNG được nạp cho model"
        assert "tay-only" not in blk
        # trust xong → vào catalog
        sk.save_trusted(w, {"rieng-tu"})
        blk2 = sk.skills_block(w)
        assert "rieng-tu" in blk2, "đã trust mà vẫn ẩn?"
        # trust rồi nhưng tắt model-invocation → vẫn ẩn
        assert "tay-only" not in blk2
    finally:
        Path.home = orig_home


# ─────────────────────────── T2 skillmgr.trust ────────────────────────────
@check("T2 /skills trust: liệt kê chưa tin · sai tên lỗi · trust 1 · trust all · lưu bền")
async def t2():
    import engine.skillmgr as mgr
    import engine.skills as sk
    w = ws_tmp("t2")
    _skill(w / ".forge" / "skills", "skill-a", 'name: skill-a\ndescription: A')
    _skill(w / ".forge" / "skills", "skill-b", 'name: skill-b\ndescription: B')
    # liệt kê chưa tin
    out = mgr.trust(w, "")
    assert "2 skill project CHƯA" in out and "skill-a" in out, out
    assert "/skills trust all" in out
    # sai tên
    assert "❌" in mgr.trust(w, "sai-ten")
    # trust 1
    ok = mgr.trust(w, "skill-a")
    assert "✅" in ok and "skill-a" in ok, ok
    assert sk.load_trusted(w) == {"skill-a"}, sk.load_trusted(w)
    # listing không còn 🔒 cho skill-a nhưng vẫn còn cho skill-b
    ls = mgr.format_listing(w)
    assert "🔒" in ls and "chưa được tin" in ls, ls[:300]
    # trust all — chỉ phần còn lại
    ok2 = mgr.trust(w, "all")
    assert "1 skill" in ok2 and "skill-b" in ok2, ok2
    assert sk.load_trusted(w) == {"skill-a", "skill-b"}
    # hết việc → thông báo sạch
    assert "đã được tin" in mgr.trust(w, "")


# ─────────────────────────── T3 expand chặn + blocked_reason ──────────────
@check("T3 /<tên>: chưa tin → expand None + blocked_reason hướng dẫn; trust → chạy; bypass alias đã bịt")
async def t3():
    from engine.commands import blocked_reason, expand
    import engine.skills as sk
    w = ws_tmp("t3")
    _skill(w / ".forge" / "skills", "skill-chuan",
           'name: skill-chuan\ndescription: chuẩn SKILL.md',
           body="Nội dung skill chuẩn $ARGUMENTS.")
    # flat legacy cũng là project → phải gate như thường (FILE dẹt, không phải thư mục)
    (w / ".forge" / "skills").mkdir(parents=True, exist_ok=True)
    (w / ".forge" / "skills" / "skill-flat.md").write_text(
        "---\ndescription: flat chưa tin\n---\nBody flat $ARGUMENTS.", encoding="utf-8")

    assert expand("/skill-chuanabc", w) is None  # không tồn tại
    assert expand("/skill-chuan xy", w) is None, "chưa trust mà vẫn expand!"
    reason = blocked_reason(w, "/skill-chuan xy")
    assert reason and "/skills trust skill-chuan" in reason and "CHƯA ĐƯỢC TIN" in reason, reason
    # flat cũng bị chặn (đã bịt alias bypass)
    assert expand("/skill-flat zz", w) is None
    assert blocked_reason(w, "/skill-flat zz") is not None
    # text thường không bị chặn
    assert blocked_reason(w, "xin chào") is None
    # trust → expand được cả hai
    sk.save_trusted(w, {"skill-chuan", "skill-flat"})
    out = expand("/skill-chuan xy", w)
    assert out is not None and "Nội dung skill chuẩn xy" in out, out
    out2 = expand("/skill-flat zz", w)
    assert out2 is not None and "Body flat zz" in out2, out2
    assert blocked_reason(w, "/skill-chuan xy") is None


# ─────────────────────────── T4 built-in skill-creator ────────────────────
@check("T4 built-in: skill-creator luôn có, trusted, vào catalog; project trùng tên đè built-in")
async def t4():
    import engine.skills as sk
    w = ws_tmp("t4")
    home_iso = TMP / "home-t4"; home_iso.mkdir(exist_ok=True)
    orig_home = Path.home
    Path.home = lambda: home_iso
    try:
        await _t4_body(sk, w)
    finally:
        Path.home = orig_home


async def _t4_body(sk, w):
    found = sk.find_skill(w, "skill-creator")
    assert found and found["source"] == "built-in" and found["trusted"], found
    blk = sk.skills_block(w)
    assert "skill-creator" in blk and "skill" in found["description"].lower()
    # project trùng tên → đè built-in (và chưa tin → ẩn catalog)
    _skill(w / ".forge" / "skills", "skill-creator",
           'name: skill-creator\ndescription: bản project đè built-in')
    found2 = sk.find_skill(w, "skill-creator")
    assert found2["source"] == "project", found2["source"]
    blk2 = sk.skills_block(w)
    assert "bản project đè built-in" not in blk2, "project chưa tin không được nạp"
    _, diags = sk.list_skills(w)
    assert any("skill-creator" in d and "bị che" in d for d in diags), diags


# ─────────────────────────── T5 script trong skill chạy thật (S4) ─────────
@check("T5 S4: agent đọc SKILL.md rồi chạy scripts/ thật qua shell → output về tay")
async def t5():
    from engine.agent import Agent
    from engine.session import SessionStore
    from engine.skills import save_trusted
    import engine.llm as llm
    store = SessionStore()
    sid = store.create().id
    w = store.workspace(sid)
    d = _skill(w / ".forge" / "skills", "chay-script",
               'name: chay-script\ndescription: chạy script kiểm tra',
               body="Chạy scripts/chay.py trong thư mục skill.")
    (d / "scripts").mkdir()
    (d / "scripts" / "chay.py").write_text(
        "import sys\nprint('KET-QUA-' + sys.argv[1])\n", encoding="utf-8")
    save_trusted(w, {"chay-script"})
    agent = Agent(store, sid)
    state = {"n": 0}
    skill_md = str(d / "SKILL.md")
    script = str(d / "scripts" / "chay.py")

    async def fake(messages, tools=None, model=None, api_key=None, temperature=0.3):
        state["n"] += 1
        if state["n"] == 1:
            yield {"type": "tool_calls", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "read_file",
                             "arguments": json.dumps({"path": skill_md})}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        elif state["n"] == 2:
            yield {"type": "tool_calls", "tool_calls": [{
                "id": "c2", "type": "function",
                "function": {"name": "run_command",
                             "arguments": json.dumps(
                                 {"command": f"{sys.executable} {script} OK2025"})}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        else:
            yield {"type": "delta", "text": "đã chạy script"}
            yield {"type": "finish", "reason": "stop"}
    orig = llm.stream_chat
    llm.stream_chat = fake
    try:
        evs = [e async for e in agent.send("chạy skill chay-script")]
    finally:
        llm.stream_chat = orig
    trs = [e for e in evs if e["type"] == "tool_result"]
    assert any("KET-QUA-OK2025" in (e.get("output") or "") and e.get("ok")
               for e in trs), trs
    # catalog phải dẫn đường dẫn tuyệt đối để model tìm được script
    from engine.skills import skills_block
    blk = skills_block(w)
    assert "chay-script" in blk and "kèm scripts/" in blk and str(w) in blk, blk[:300]


# ─────────────────────────── T6 server /skills trust + blocked ────────────
@check("T6 server: /skills trust qua chat · skill chưa tin → thông báo 🔒 không vào LLM")
async def t6():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        sid = client.post("/api/sessions", json={"title": "t6"}).json()["session"]["id"]
        # built-in skill-creator phải có trong listing
        r = client.post(f"/api/sessions/{sid}/chat", json={"text": "/skills", "mode": "direct"})
        assert "skill-creator" in r.text, r.text[-300:]
        # tạo skill project chưa tin trong workspace của phiên
        ws = Path(os.environ["FORGE_DATA_DIR"]) / "workspaces" / sid
        _skill(ws / ".forge" / "skills", "bi-chan",
               'name: bi-chan\ndescription: skill bị chặn',
               body="NỘI-DUNG-BÍ-MẬT không được lộ cho model.")
        r2 = client.post(f"/api/sessions/{sid}/chat",
                         json={"text": "/bi-chan hãy chạy", "mode": "direct"})
        txt = r2.text
        assert "CHƯA ĐƯỢC TIN" in txt and "/skills trust bi-chan" in txt, txt[-300:]
        assert "NỘI-DUNG-BÍ-MẬT" not in txt, "nội dung skill lộ ra ngoài!"
        # trust qua chat
        r3 = client.post(f"/api/sessions/{sid}/chat",
                         json={"text": "/skills trust bi-chan", "mode": "direct"})
        assert "✅" in r3.text, r3.text[-200:]
        # giờ expand → tin nhắn user lưu vào phiên là NỘI DUNG ĐÃ EXPAND (demo không echo)
        client.post(f"/api/sessions/{sid}/chat",
                    json={"text": "/bi-chan demo", "mode": "direct"})
        sess = client.get(f"/api/sessions/{sid}").json()["session"]
        blob = json.dumps(sess.get("messages", []), ensure_ascii=False)
        assert "NỘI-DUNG-BÍ-MẬT" in blob, "expand sau trust chưa ăn: " + blob[-300:]


async def main():
    print(f"=== SMOKE v0.16 Skills P1 — data tạm: {TMP} ===")
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
