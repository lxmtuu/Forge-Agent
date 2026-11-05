# -*- coding: utf-8 -*-
"""Audit suite v0.18 — P3 closeout:
GET /api/audit (endpoint bảng web) · mask token qua endpoint · n cap · async fixes hồi quy.

Chạy:  python scripts/test_v019.py
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

TMP = Path(tempfile.mkdtemp(prefix="forge-v019-"))
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


@check("T1 GET /api/audit: trả entries mới-nhất-trước · mask token qua endpoint · shape đúng")
async def t1():
    from engine import auditlog as al
    tok = "ghp_ENDPOINTTEST9999zz"
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        sid = c.post("/api/sessions", json={}).json()["session"]["id"]
        al.log_tool(sid, "write_file", {"path": "a.py"}, True, 7)
        al.log_tool(sid, "run_command", {"command": f"curl -H 'Authorization: Bearer {tok}' http://x"},
                    True, 250, source="internal")
        r = c.get("/api/audit")
        assert r.status_code == 200, r.text[:150]
        rows = r.json()["entries"]
        assert isinstance(rows, list) and len(rows) >= 2
        assert rows[0]["tool"] == "run_command", "mới nhất phải trước"
        e = rows[0]
        for k in ("ts", "tool", "source", "ok"):
            assert k in e, e
        blob = json.dumps(rows, ensure_ascii=False)
        assert tok not in blob, "TOKEN LỘ QUA ENDPOINT /api/audit!"
        assert "Bearer" in blob  # đã mask còn nhãn


@check("T2 /api/audit: n cap 1..500 (n=9999 không nổ) + n=0 → vẫn 200")
async def t2():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        for n in (9999, 1, 0):
            r = c.get("/api/audit", params={"n": n})
            assert r.status_code == 200, (n, r.text[:120])
            assert isinstance(r.json()["entries"], list)


@check("T3 hồi quy to_thread: review.collect_diff chạy đúng sau khi đổi async (checkpoint git thật)")
async def t3():
    from engine import review as freview
    from engine.session import SessionStore
    store = SessionStore()
    sid = store.create().id
    ws = store.workspace(sid)
    (ws / "f.txt").write_text("xin chào\n", encoding="utf-8")
    try:
        diff, label = await freview.collect_diff(ws, sid, "")
        assert isinstance(diff, str) and label, (label, diff[:60])
    except ValueError as e:
        # không có gì thay đổi cũng được — miễn KHÔNG phải lỗi to_thread/TypeError
        assert "to_thread" not in str(e) and "coroutine" not in str(e), e


async def main():
    print(f"=== AUDIT v0.18 P3 closeout — data tạm: {TMP} ===")
    for fn in [t1, t2, t3]:
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
