# -*- coding: utf-8 -*-
"""Suite v0.26 "Skills trong web" (S8):
set_model_invocable (frontmatter surgery: có/không frontmatter, legacy md)
· REST /api/skills + toggle + trust · toggle hiệu lực ngay trong list_skills.

Chạy:  python scripts/test_v026.py-style:  python scripts/test_v027.py
"""
import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v027-"))
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


def _mk(ws: Path, name: str, body: str) -> Path:
    d = ws / ".forge" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "SKILL.md"
    f.write_text(body, encoding="utf-8")
    return f


@check("T1 frontmatter surgery: tắt → dòng disable + list_skills thấy invocable=False · bật → xoá dòng, True")
async def t1():
    from engine import skillmgr
    from engine.skills import list_skills
    ws = TMP / "ws1"
    ws.mkdir(parents=True, exist_ok=True)
    f = _mk(ws, "demo-skill",
            "---\nname: demo-skill\ndescription: skill test\n---\n\n# Nội dung\n")
    skills, _ = list_skills(ws)
    rec = next(s for s in skills if s["name"] == "demo-skill")
    assert rec["model_invocable"] is True
    msg = skillmgr.set_model_invocable(ws, str(f), False)
    assert "🔕" in msg, msg
    assert "disable-model-invocation: true" in f.read_text(encoding="utf-8")
    skills, _ = list_skills(ws)
    assert next(s for s in skills if s["name"] == "demo-skill")["model_invocable"] is False
    msg2 = skillmgr.set_model_invocable(ws, str(f), True)
    assert "✅" in msg2, msg2
    assert "disable-model-invocation" not in f.read_text(encoding="utf-8")
    skills, _ = list_skills(ws)
    assert next(s for s in skills if s["name"] == "demo-skill")["model_invocable"] is True
    # tắt lần 2 khi đã tắt → dòng không nhân đôi
    skillmgr.set_model_invocable(ws, str(f), False)
    skillmgr.set_model_invocable(ws, str(f), False)
    content = f.read_text(encoding="utf-8")
    assert content.count("disable-model-invocation") == 1, content


@check("T2 legacy md không frontmatter: tắt → tự tạo frontmatter tối thiểu · bật lại không hỏng nội dung")
async def t2():
    from engine import skillmgr
    from engine.skills import list_skills
    ws = TMP / "ws2"
    ws.mkdir(parents=True, exist_ok=True)
    f = ws / ".forge" / "skills" / "ghi-chu.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# Ghi chú nhanh\nNội dung thuần không frontmatter.\n", encoding="utf-8")
    skills, _ = list_skills(ws)
    assert any(s["name"] == "ghi-chu" for s in skills)
    msg = skillmgr.set_model_invocable(ws, str(f), False)
    assert "🔕" in msg, msg
    txt = f.read_text(encoding="utf-8")
    assert txt.startswith("---\n") and "disable-model-invocation: true" in txt
    assert "Nội dung thuần" in txt, "phải giữ nguyên thân file"
    skills, _ = list_skills(ws)
    assert next(s for s in skills if s["name"] == "ghi-chu")["model_invocable"] is False
    msg2 = skillmgr.set_model_invocable(ws, str(f), True)
    assert "✅" in msg2, msg2
    assert "Nội dung thuần" in f.read_text(encoding="utf-8")
    # path lạ → lỗi thân thiện
    msg3 = skillmgr.set_model_invocable(ws, str(ws / "khong-ton-tai" / "SKILL.md"), False)
    assert msg3.startswith("❌"), msg3


@check("T3 REST: GET skills (đúng shape) · toggle roundtrip · trust trả message · 404 sid lạ")
async def t3():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        sid = c.post("/api/sessions", json={}).json()["session"]["id"]
        ws = c.get(f"/api/sessions/{sid}").json()["session"]
        _ = ws  # shape check
        # tạo skill qua workspace thật của phiên
        from engine.session import SessionStore
        store = SessionStore()
        w = store.workspace(sid)
        f = _mk(w, "rest-skill", "---\nname: rest-skill\ndescription: qua REST\n---\n\nx\n")
        r = c.get("/api/skills", params={"sid": sid})
        assert r.status_code == 200
        rows = {x["name"]: x for x in r.json()["skills"]}
        assert "rest-skill" in rows and "diags" in r.json()
        rec = rows["rest-skill"]
        for k in ("path", "source", "model_invocable", "trusted", "allowed_tools", "diags", "fmt"):
            assert k in rec, rec
        # toggle off qua REST
        r = c.post("/api/skills/toggle", params={"sid": sid},
                   json={"path": str(f), "invocable": False})
        assert r.status_code == 200 and r.json()["ok"], r.text[:150]
        rows = {x["name"]: x for x in c.get("/api/skills", params={"sid": sid}).json()["skills"]}
        assert rows["rest-skill"]["model_invocable"] is False
        # trust (skill project mặc định chưa tin? — user-source thì luôn tin; chỉ cần 200 + message)
        r = c.post("/api/skills/trust", params={"sid": sid}, json={"name": "rest-skill"})
        assert r.status_code == 200 and "message" in r.json(), r.text[:150]
        # sid lạ
        assert c.get("/api/skills", params={"sid": "khong-co"}).status_code == 404
        assert c.post("/api/skills/toggle", params={"sid": "khong-co"},
                      json={"path": "x", "invocable": True}).status_code == 404
        # path không thuộc catalog → 400 thân thiện
        r = c.post("/api/skills/toggle", params={"sid": sid},
                   json={"path": "/tmp/xx/SKILL.md", "invocable": True})
        assert r.status_code == 400


@check("T4 chat /skills synthetic vẫn hoạt động (listing không bị hỏng bởi S8)")
async def t4():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        sid = c.post("/api/sessions", json={}).json()["session"]["id"]
        r = c.post(f"/api/sessions/{sid}/chat", json={"text": "/skills", "mode": "direct"})
        assert r.status_code == 200, r.text[:150]
        msgs = [json.loads(ln[5:]) for ln in r.text.splitlines()
                if ln.startswith("data:") and '"assistant_message"' in ln]
        assert msgs, "phải có listing"
        assert "Skills" in msgs[-1]["content"] or "skill" in msgs[-1]["content"].lower()


import json  # noqa: E402  (dùng ở T4)

async def main():
    print(f"=== SUITE v0.26 Skills trong web — data tạm: {TMP} ===")
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
