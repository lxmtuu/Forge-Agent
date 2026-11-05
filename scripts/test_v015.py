# -*- coding: utf-8 -*-
"""Smoke suite v0.15 "Skills 2.0":
format chuẩn <tên>/SKILL.md + YAML lenient · đa vị trí quét (.forge/.agents/.claude/user)
· precedence + diagnostics · /<tên> expand · /skills add|new|remove · server.

Chạy:  python scripts/test_v015.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v015-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("FORGE_PROFILE", None)
FAKE_HOME = TMP / "home"
FAKE_HOME.mkdir()

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


def _skill(dirpath: Path, name: str, fm: str, body: str = "# Bước\n1. Làm.") -> Path:
    d = dirpath / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")
    return d


def _flat(dirpath: Path, name: str, fm: str, body: str = "# Bước\n1. Làm.") -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / f"{name}.md"
    p.write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")
    return p


def ws_tmp(tag: str) -> Path:
    w = TMP / f"ws-{tag}"
    w.mkdir(parents=True, exist_ok=True)
    return w


# ────────────────────────────── T1 parse + lenient validation ──────────────
@check("T1 SKILL.md: chuẩn mới + name lệch cảnh báo + thiếu desc bỏ + YAML ': ' fallback + flat cũ")
async def t1():
    from engine.skills import list_skills
    w = ws_tmp("t1")
    _skill(w / ".forge" / "skills", "ok-skill",
           'name: ok-skill\ndescription: Làm việc A. Dùng khi cần A.')
    _skill(w / ".forge" / "skills", "lech-ten",
           'name: ten-khac\ndescription: Name lệch thư mục.')
    _skill(w / ".forge" / "skills", "thieu-desc", 'name: thiéu-desc')
    _skill(w / ".forge" / "skills", "colon-skill",
           'name: colon-skill\ndescription: Dùng khi: người dùng hỏi về PDF')  # YAML vỡ kiểu phổ biến
    _flat(w / ".forge" / "skills", "flat-cu",
          'description: skill dẹt từ v0.11 vẫn nạp.')
    _skill(w / ".forge" / "skills", "yaml-vo", 'name: [vô\n  kiểu: {rác')
    _skill(w / ".forge" / "skills", "dai-desc",
           'name: dai-desc\ndescription: ' + "x" * 1200)

    skills, diags = list_skills(w)
    names = [s["name"] for s in skills]
    assert "ok-skill" in names and "colon-skill" in names and "flat-cu" in names, names
    assert "thieu-desc" not in names and "yaml-vo" not in names, names
    assert "lech-ten" in names, names  # lenient: vẫn nạp
    by = {s["name"]: s for s in skills}
    assert by["ok-skill"]["fmt"] == "standard"
    assert by["flat-cu"]["fmt"] == "flat"
    assert by["colon-skill"]["description"] == "Dùng khi: người dùng hỏi về PDF", by["colon-skill"]
    assert len(by["dai-desc"]["description"]) <= 1024
    blob = "\n".join(diags)
    assert "≠ tên" in blob and "BỎ skill" in blob, blob
    assert any("dai-desc" in d and "cắt" in d for d in diags), diags


# ────────────────────────────── T2 đa vị trí + precedence ──────────────────
@check("T2 quét .forge/.agents/.claude/user/legacy, project đè user, ẩn catalog khi tắt model-invocation")
async def t2():
    from engine.skills import list_skills, skills_block
    w = ws_tmp("t2")
    _skill(w / ".agents" / "skills", "tu-agents", 'name: tu-agents\ndescription: từ .agents/skills')
    _skill(w / ".claude" / "skills", "tu-claude", 'name: tu-claude\ndescription: từ .claude/skills')
    # trùng tên: project (.forge) đè user (~/.forge)
    _skill(w / ".forge" / "skills", "trung-ten",
           'name: trung-ten\ndescription: bản PROJECT thắng')
    _skill(FAKE_HOME / ".forge" / "skills", "trung-ten",
           'name: trung-ten\ndescription: bản USER bị che')
    _skill(FAKE_HOME / ".forge" / "skills", "rieng-user",
           'name: rieng-user\ndescription: skill của user')
    # legacy global (data/forge/skills theo FORGE_DATA_DIR)
    _flat(Path(os.environ["FORGE_DATA_DIR"]) / "forge" / "skills", "legacy-global",
          'description: global cũ v0.11')
    # skill tắt model-invocation + skill kèm scripts/
    _skill(w / ".forge" / "skills", "tay-only",
           'name: tay-only\ndescription: chỉ gọi tay\ndisable-model-invocation: true')
    d = _skill(w / ".forge" / "skills", "co-script",
               'name: co-script\ndescription: có kèm script chạy được')
    (d / "scripts").mkdir()
    (d / "scripts" / "chay.sh").write_text("echo hi\n", encoding="utf-8")

    orig_home = Path.home
    Path.home = lambda: FAKE_HOME
    try:
        skills, diags = list_skills(w)
    finally:
        Path.home = orig_home
    by = {s["name"]: s for s in skills}
    assert by["tu-agents"]["source"] == "project" and by["tu-claude"]["source"] == "project"
    assert by["rieng-user"]["source"] == "user"
    assert by["legacy-global"]["source"] == "global-legacy"
    assert "bản PROJECT thắng" in by["trung-ten"]["description"], by["trung-ten"]
    assert by["co-script"]["scripts"] is True, by["co-script"]
    blob = "\n".join(diags)
    assert "bị che" in blob, blob

    from engine.skills import save_trusted
    save_trusted(w, {"trung-ten", "co-script", "tu-agents", "tu-claude"})
    blk = skills_block(w)
    assert "trung-ten" in blk and "co-script" in blk and "kèm scripts/" in blk, blk[:400]
    assert "tay-only" not in blk, "skill tắt model-invocation phải ẩn khỏi catalog"
    assert "THƯ MỤC CỦA SKILL" in blk, "thiếu hướng dẫn giải path tương đối"
    # không có skill nào → khối rỗng (không render catalog trống) — tách cả legacy global
    from engine import config as fconfig
    w0 = ws_tmp("t2-empty")
    empty_home = FAKE_HOME / "trong-rong"
    empty_home.mkdir(exist_ok=True)
    orig_home, orig_data = Path.home, fconfig.DATA_DIR
    Path.home = lambda: empty_home
    fconfig.DATA_DIR = TMP / "data-empty"
    try:
        blk0 = skills_block(w0)
        assert "skill-creator" in blk0, "built-in skill-creator phải luôn sẵn sàng"
    finally:
        Path.home = orig_home
        fconfig.DATA_DIR = orig_data


# ────────────────────────────── T3 /<tên> expand qua chuẩn mới ─────────────
@check("T3 /<tên> gọi skill chuẩn SKILL.md (mọi nguồn) + $ARGUMENTS")
async def t3():
    from engine.commands import expand
    w = ws_tmp("t3")
    _skill(w / ".agents" / "skills", "deploy-staging",
           'name: deploy-staging\ndescription: deploy lên staging',
           body="Deploy lên môi trường $ARGUMENTS theo checklist.")
    # v0.16: skill project chưa trust → expand bị chặn, phải trust trước
    from engine.skills import save_trusted
    assert expand("/deploy-staging sáng thứ 2", w) is None
    save_trusted(w, {"deploy-staging"})
    out = expand("/deploy-staging sáng thứ 2", w)
    assert out is not None and "sáng thứ 2" in out and "Deploy lên" in out, out
    assert expand("/khong-ton-tai", w) is None


# ────────────────────────────── T4 skillmgr: list/add/new/remove ───────────
@check("T4 /skills: listing nhóm nguồn · add từ thư mục local · new scaffold · remove")
async def t4():
    import engine.skillmgr as mgr
    import engine.skills as sk
    w = ws_tmp("t4")
    orig_home = Path.home
    Path.home = lambda: FAKE_HOME
    try:
        # listing ban đầu có hướng dẫn
        s0 = mgr.format_listing(w)
        assert "/skills add" in s0 and "/skills new" in s0
        # add từ thư mục local (sample của repo)
        sample = ROOT / "skills-samples" / "commit-vn"
        assert sample.is_dir(), "thiếu skills-samples/commit-vn"
        out = mgr.add(w, str(sample))
        assert "✅ commit-vn" in out, out
        inst = FAKE_HOME / ".forge" / "skills" / "commit-vn"
        assert (inst / "SKILL.md").is_file() and (inst / "references" / "convention.md").is_file()
        # listing giờ hiện commit-vn ở user scope
        ls = mgr.format_listing(w)
        assert "commit-vn" in ls and "User" in ls, ls[:300]
        # add nguồn không hiểu
        bad = mgr.add(w, "khong-phai-nguon!!")
        assert "❌" in bad, bad
        # add thư mục không có SKILL.md
        empty = TMP / "empty-dir"; empty.mkdir(exist_ok=True)
        bad2 = mgr.add(w, str(empty))
        assert "không thấy SKILL.md" in bad2, bad2
        # new: scaffold + validate sạch + xuất hiện trong listing
        out2 = mgr.new_skill(w, "review-api", "Review API theo chuẩn dự án. Dùng khi khách yêu cầu review API.")
        assert out2.startswith("✅"), out2
        skills, _ = sk.list_skills(w)
        assert any(x["name"] == "review-api" and x["source"] == "project" for x in skills)
        # new: tên bẩn bị chặn
        assert mgr.new_skill(w, "Đại Lộ!").startswith("❌")
        assert mgr.new_skill(w, "review-api").startswith("❌")  # trùng
        # remove: chỉ user scope
        assert mgr.remove(w, "commit-vn").startswith("🗑")
        assert not (FAKE_HOME / ".forge" / "skills" / "commit-vn").exists()
        assert "❌" in mgr.remove(w, "review-api")  # project skill — không gỡ bằng remove
    finally:
        Path.home = orig_home


# ────────────────────────────── T5 agent giữ nguyên hành vi ────────────────
@check("T5 agent: skills_block vẫn vào system prompt, turn/end không hỏng sau khi đổi skills")
async def t5():
    from engine.agent import Agent
    from engine.session import SessionStore
    import engine.llm as llm
    store = SessionStore()
    sid = store.create().id
    w = store.workspace(sid)
    _skill(w / ".forge" / "skills", "nhiem-vu-mau",
           'name: nhiem-vu-mau\ndescription: demo skill cho system prompt')
    agent = Agent(store, sid)
    from engine.skills import save_trusted
    save_trusted(w, {"nhiem-vu-mau"})  # v0.16: cần trust mới vào catalog

    seen = {}

    async def fake(messages, tools=None, model=None, api_key=None, temperature=0.3):
        seen["msgs"] = list(messages)
        yield {"type": "delta", "text": "ok"}
        yield {"type": "finish", "reason": "stop"}
    orig = llm.stream_chat
    llm.stream_chat = fake
    try:
        evs = [e async for e in agent.send("chào")]
    finally:
        llm.stream_chat = orig
    assert [e for e in evs if e["type"] == "turn_end"], evs
    # system prompt gửi cho LLM phải chứa catalog skill
    sys_txt = "\n".join(str(m.get("content")) for m in seen["msgs"])
    assert "nhiem-vu-mau" in sys_txt, sys_txt[:400]


# ────────────────────────────── T6 server /skills ──────────────────────────
@check("T6 server: /skills listing + /skills new không cần LLM (synthetic)")
async def t6():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as client:
        sid = client.post("/api/sessions", json={"title": "t6"}).json()["session"]["id"]
        r = client.post(f"/api/sessions/{sid}/chat",
                        json={"text": "/skills", "mode": "direct"})
        txt = r.text
        assert "🧩 Skills" in txt or "chưa có skill" in txt, txt[-300:]
        r2 = client.post(f"/api/sessions/{sid}/chat",
                         json={"text": "/skills new skill-web Demo skill web",
                               "mode": "direct"})
        assert "✅" in r2.text, r2.text[-300:]
        # skill vừa tạo phải nằm trong workspace của phiên
        r3 = client.post(f"/api/sessions/{sid}/chat",
                         json={"text": "/skills", "mode": "direct"})
        assert "skill-web" in r3.text, r3.text[-400:]


async def main():
    print(f"=== SMOKE v0.15 Skills 2.0 — data tạm: {TMP} ===")
    for fn in [t1, t2, t3, t4, t5, t6]:
        await fn()
    shutil.rmtree(FAKE_HOME, ignore_errors=True)
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
