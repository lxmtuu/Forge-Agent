# -*- coding: utf-8 -*-
"""Suite v0.23 "Nhịp lặp & Xuất audit":
F1 /loop — parse_interval · LoopManager (unit + E2E server với lượt demo thật)
· CSV export audit log (escape chuẩn csv).

Chạy:  python scripts/test_v024.py
"""
import asyncio
import csv
import io
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="forge-v024-"))
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


@check("T1 parse_interval: 45s/30m/2h/1d/số trần/sai → đúng giây + clamp 10s..7d")
async def t1():
    from engine.scheduler import fmt_interval, parse_interval
    assert parse_interval("45s") == 45
    assert parse_interval("30m") == 1800
    assert parse_interval("2h") == 7200
    assert parse_interval("1d") == 86400
    assert parse_interval("5") == 300  # số trần = phút
    assert parse_interval("3s") == 10  # clamp min
    assert parse_interval("99d") == 7 * 24 * 3600  # clamp max
    assert parse_interval("abc") == 1800  # sai → default 30m
    assert parse_interval("") == 1800
    assert fmt_interval(1800) == "30m" and fmt_interval(45) == "45s"


@check("T2 LoopManager unit: chạy ≥2 nhịp (run_fn stub) · stop chặn nhịp sau · status shape")
async def t2():
    from engine.scheduler import LoopManager
    lm = LoopManager()
    calls: list[str] = []

    async def run_fn(sid, text, mode):
        calls.append(f"{sid}:{text}:{mode}")
    st = lm.start("s1", 0.2, "việc X", "agent", run_fn, max_runs=0)
    assert st["running"] and st["every"] == 0.2 or st["every"] == 0  # 0.2s bị clamp? — start nhận đã-parse
    await asyncio.sleep(0.7)
    lm.stop("s1")
    n_when_stopped = len(calls)
    assert n_when_stopped >= 2, f"chỉ chạy {n_when_stopped} nhịp?"
    await asyncio.sleep(0.5)
    assert len(calls) == n_when_stopped, "stop mà vẫn chạy tiếp?"
    assert lm.status("s1")["running"] is False
    assert lm.stop("s1") is False  # không còn gì để dừng
    # max_runs tự kết thúc
    calls2: list[int] = []

    async def run_fn2(sid, text, mode):
        calls2.append(1)
    st2 = lm.start("s2", 0.1, "y", "agent", run_fn2, max_runs=2)
    await asyncio.sleep(0.8)
    assert len(calls2) == 2, calls2
    assert lm.status("s2")["running"] is False, "max_runs mà vẫn chạy?"
    # status shape
    lm.start("s3", 0.2, "z", "agent", run_fn)
    s3 = lm.status("s3")
    for k in ("running", "every", "text", "mode", "runs", "max", "last_ok", "since"):
        assert k in s3, s3
    assert len(lm.status_all()) == 1
    lm.stop("s3")


@check("T3 server loop E2E: POST /loop (lượt demo thật) → session mọc tin · status · DELETE dừng")
async def t3():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        sid = c.post("/api/sessions", json={}).json()["session"]["id"]
        n0 = len(c.get(f"/api/sessions/{sid}").json()["session"]["messages"])
        r = c.post(f"/api/sessions/{sid}/loop",
                   json={"text": "tạo file loop_test.py", "every": "1s", "max_runs": 2})
        assert r.status_code == 200 and r.json()["ok"], r.text[:150]
        assert r.json()["status"]["running"] is True
        # chờ 2 lượt demo (send_demo có sleep mô phỏng tool — 1 lượt có thể tới ~5s)
        for _ in range(60):
            await asyncio.sleep(0.5)
            st = c.get(f"/api/sessions/{sid}/loop").json()
            if not st.get("running"):
                break
        assert st["running"] is False, "max_runs=2 mà vẫn chạy?"
        assert st["runs"] == 2, st
        assert st.get("last_ok") is True, st
        n1 = len(c.get(f"/api/sessions/{sid}").json()["session"]["messages"])
        assert n1 > n0, "lượt loop phải persist vào session (web tải lại là thấy)"
        assert c.delete(f"/api/sessions/{sid}/loop").json()["ok"] is False  # đã tự kết thúc
        # start lại rồi DELETE chủ động
        c.post(f"/api/sessions/{sid}/loop", json={"text": "việc", "every": "1s"})
        assert c.delete(f"/api/sessions/{sid}/loop").json()["ok"] is True
        assert c.get(f"/api/sessions/{sid}/loop").json()["running"] is False
        # validate
        assert c.post("/api/sessions/khong-co/loop", json={"text": "x"}).status_code == 404
        assert c.post(f"/api/sessions/{sid}/loop", json={"text": "  "}).status_code == 400


@check("T4 /api/audit/export CSV: header + dòng dữ liệu · escape đúng giá trị có dấu phẩy")
async def t4():
    from fastapi.testclient import TestClient
    from server.main import app
    from engine import auditlog
    auditlog.log_tool("sess-csv", "run_command",
                      {"command": "git commit -m 'feat: a, b và c'", "flags": "-q"}, True, 123)
    with TestClient(app) as c:
        r = c.get("/api/audit/export")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv"), r.headers["content-type"]
        assert "attachment" in r.headers.get("content-disposition", "")
        text = r.text
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == ["ts", "session", "tool", "source", "ok", "ms", "args", "note"], rows[0]
        target = [r for r in rows if len(r) > 2 and r[2] == "run_command" and r[1] == "sess-csv"]
        assert target, rows[:3]
        row = target[-1]
        assert row[4] == "1" and row[5] == "123"
        args = json.loads(row[6])  # csv đã tách đúng cột dù args chứa dấu phẩy
        assert args["command"] == "git commit -m 'feat: a, b và c'"
        assert args["flags"] == "-q"


async def main():
    print(f"=== SUITE v0.23 Nhịp lặp & Xuất audit — data tạm: {TMP} ===")
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
