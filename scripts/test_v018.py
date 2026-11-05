# -*- coding: utf-8 -*-
"""Audit suite v0.17.1 — quét BỀ MẶT server chưa được test trước đây (server/main.py 56%):
settings/keycheck · usage · models · sessions CRUD + undo/compact/init/fork/export ·
approvals + elicitations endpoint · workspace file CRUD + upload + export-zip.

Chạy:  python scripts/test_v018.py
"""
import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v018-"))
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


async def t_all():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        # ── settings + keycheck + models + usage + mcp ──
        r = c.get("/api/settings")
        assert r.status_code == 200 and "approval_mode" in r.text, r.text[:150]
        r = c.post("/api/keycheck", json={"key": "sk-or-v1-test"})
        assert r.status_code == 200 and isinstance(r.json().get("valid"), bool), r.text[:150]
        r = c.get("/api/models")
        assert r.status_code == 200 and r.json(), r.text[:150]
        r = c.get("/api/usage")
        assert r.status_code == 200, r.text[:150]
        r = c.get("/api/mcp")
        assert r.status_code == 200, r.text[:150]

        # ── sessions CRUD ──
        sid = c.post("/api/sessions", json={"title": "audit"}).json()["session"]["id"]
        ws = Path(os.environ["FORGE_DATA_DIR"]) / "workspaces" / sid
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "hello.py").write_text("print('xin chào')\n", encoding="utf-8")

        r = c.get("/api/sessions")
        assert r.status_code == 200, r.text[:150]
        rows = r.json().get("sessions") or (r.json() if isinstance(r.json(), list) else [])
        assert any(x["id"] == sid for x in rows), r.text[:200]
        r = c.get(f"/api/sessions/{sid}")
        assert r.status_code == 200 and r.json()["session"]["id"] == sid

        # ── undo/compact/init (demo-able, không cần LLM) ──
        r = c.post(f"/api/sessions/{sid}/undo", json={})
        assert r.status_code == 200 and "ok" in r.json(), r.text[:150]
        r = c.post(f"/api/sessions/{sid}/compact", json={})
        assert r.status_code == 200, r.text[:200]
        r = c.post(f"/api/sessions/{sid}/init", json={})
        assert r.status_code == 200, r.text[:200]

        # ── fork + export ──
        r = c.post(f"/api/sessions/{sid}/fork", json={})
        assert r.status_code == 200 and r.json().get("session", {}).get("id"), r.text[:200]
        r = c.get(f"/api/sessions/{sid}/export")
        assert r.status_code == 200 and len(r.text) > 10, r.text[:150]

        # ── approvals: tạo request thật rồi resolve qua endpoint ──
        from engine import approvals as ap
        aid = ap.create("echo audit-test", "warn", ["test"])
        r = c.post(f"/api/approvals/{aid}", json={"decision": "approve"})
        assert r.status_code == 200 and r.json().get("ok"), r.text[:150]
        decision = await asyncio.wait_for(ap.wait(aid), timeout=2)
        assert decision == "approve", decision

        # ── elicitations endpoint ──
        r = c.get("/api/elicitations")
        assert r.status_code == 200 and ("pending" in r.json() or "requests" in r.json()), r.text[:150]
        r = c.post("/api/elicitation/khong-ton-tai", json={"action": "decline"})
        assert r.status_code in (200, 404), r.status_code

        # ── workspace: tree / file GET/PUT/DELETE / upload / export ──
        r = c.get("/api/workspace/tree", params={"sid": sid})
        assert r.status_code == 200 and "hello.py" in r.text, r.text[:200]
        r = c.get("/api/workspace/file", params={"sid": sid, "path": "hello.py"})
        assert r.status_code == 200 and "xin chào" in r.text, r.text[:200]
        r = c.put("/api/workspace/file", params={"sid": sid},
                  json={"path": "moi.txt", "content": "nội dung mới"})
        assert r.status_code == 200 and r.json().get("ok"), r.text[:150]
        r = c.get("/api/workspace/file", params={"sid": sid, "path": "moi.txt"})
        assert "nội dung mới" in r.text
        # path traversal phải bị chặn
        r = c.get("/api/workspace/file", params={"sid": sid, "path": "../secret.txt"})
        assert r.status_code in (400, 403, 404), f"traversal không bị chặn: {r.status_code}"
        # upload multipart (đúng API thật: sid query + files multipart)
        r = c.post(f"/api/workspace/upload", params={"sid": sid},
                   files={"files": ("up.txt", "tải lên OK".encode(), "text/plain")})
        assert r.status_code == 200 and "up.txt" in r.json().get("saved", []), r.text[:200]
        assert "tải lên OK" in c.get("/api/workspace/file",
                                     params={"sid": sid, "path": "up.txt"}).text
        r = c.get("/api/workspace/export", params={"sid": sid})
        assert r.status_code == 200 and len(r.content) > 100, "zip export trống?"
        r = c.delete("/api/workspace/file", params={"sid": sid, "path": "moi.txt"})
        assert r.status_code == 200 and r.json().get("ok"), r.text[:150]

        # ── xoá phiên ──
        r = c.delete(f"/api/sessions/{sid}")
        assert r.status_code == 200, r.text[:150]
        assert c.get(f"/api/sessions/{sid}").status_code == 404


@check("T1 server surface: 20+ endpoint settings/usage/models/sessions/undo/compact/init/fork/export/approvals/elicitation/workspace CRUD/upload/export-zip/delete")
async def t_all_wrapped():
    await t_all()


@check("T2 fix hồi quy: cli 'Text' UnboundLocalError đã hết (interactive khởi động được)")
async def t2():
    import cli.main as cm
    src = Path(cm.__file__).read_text(encoding="utf-8")
    # không được còn import Text CỤC BỘ trong hàm interactive (nguyên nhân F823)
    inter = src[src.index("async def interactive"):]
    assert "from rich.text import Text" not in inter, "vẫn còn local import Text trong interactive()"
    assert "Text(BANNER" in src  # vẫn dùng Text module-level


@check("T3 fix hồi quy: MD5 checkpoint dùng usedforsecurity=False (bandit B324)")
async def t3():
    import engine.checkpoints as cp
    src = Path(cp.__file__).read_text(encoding="utf-8")
    assert "usedforsecurity=False" in src
    # chữ ký vẫn hoạt động
    key = cp.key_for(Path("/tmp/xyz"))
    assert isinstance(key, str) and len(key) == 12


@check("T4 fix hồi quy: typo 'Tổng kêeh' đã sửa")
async def t4():
    from engine import memory as fmem
    src = Path(fmem.__file__).read_text(encoding="utf-8")
    assert "kêeh" not in src


@check("T5 fix hồi quy: /skills add KHÔNG khoá event loop (asyncio.to_thread)")
async def t5():
    from server import main as sm
    src = Path(sm.__file__).read_text(encoding="utf-8")
    assert "to_thread(skillmgr.add" in src, "skillmgr.add vẫn chạy blocking trong handler"


async def main():
    print(f"=== AUDIT v0.17.1 — data tạm: {TMP} ===")
    for fn in [t_all_wrapped, t2, t3, t4, t5]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
