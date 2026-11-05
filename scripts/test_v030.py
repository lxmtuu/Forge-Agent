# -*- coding: utf-8 -*-
"""Suite v0.30 "Audit UI v2" — nâng cấp tab 📘 Audit (P3 đã đóng từ v0.18/f60e42a —
claim backlog stale; v0.30 thêm quick-filter ✅/❌, cột phiên, click dòng xem args đầy đủ).

Kiểm: shape entry đủ `session` (cột phiên mới) · mask vẫn chặt qua REST ·
UI build artifact chứa các thành phần mới · n cap không vỡ.

Chạy:  python scripts/test_v030.py
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

TMP = Path(tempfile.mkdtemp(prefix="forge-v030-"))
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


@check("T1 entry có `session` (cột phiên mới) + mask chặt · quick-filter cần ok boolean chuẩn")
async def t1():
    from engine import auditlog as al
    tok = "sk-UIV2TEST9999secretzz"
    al.log_tool("sid-20261105-abcdef", "write_file", {"path": "a.py"}, True, 7)
    al.log_tool("sid-20261105-abcdef", "run_command",
                {"command": f"curl -H 'Authorization: Bearer {tok}' http://x"}, False, 250,
                source="internal", note="fail có chủ đích cho test")
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        r = c.get("/api/audit")
        assert r.status_code == 200, r.text[:150]
        rows = r.json()["entries"]
        assert len(rows) >= 2
        e = rows[0]
        for k in ("ts", "session", "tool", "source", "ok", "ms", "args"):
            assert k in e, f"thiếu '{k}' — UI cột/quick-filter sẽ vỡ: {e}"
        assert isinstance(e["ok"], bool)
        assert e["session"].startswith("sid-20261105"), e["session"]
        blob = json.dumps(rows, ensure_ascii=False)
        assert tok not in blob, "TOKEN LỘ QUA /api/audit!"
        assert rows[0]["ok"] is False and rows[1]["ok"] is True  # nguyên liệu cho quick-filter ✅/❌


@check("T2 CSV export vẫn nguyên vẹn sau nâng cấp UI (header + dòng + không lộ secret)")
async def t2():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        r = c.get("/api/audit/export")
        assert r.status_code == 200
        body = r.text
        lines = [l for l in body.strip().splitlines() if l.strip()]
        assert len(lines) >= 3, lines[:3]           # header + ≥2 entry
        assert "tool" in lines[0].lower() and "session" in lines[0].lower(), lines[0]
        assert "sk-UIV2TEST9999secretzz" not in body, "SECRET LỘ QUA CSV!"


@check("T3 web build artifact chứa thành phần UI mới (audit-chip/audit-detail/audit-sid) — chống quên build")
async def t3():
    static = ROOT / "server" / "static" / "assets"
    if not static.is_dir():
        print("    (skip — chưa build web; chạy npm run build trong web/)")
        return
    js = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                   for p in static.glob("*.js"))
    for needle in ("audit-chip", "audit-detail", "audit-sid"):
        assert needle in js, f"build thiếu '{needle}' — đã sửa TSX nhưng quên npm run build?"
    css = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                    for p in static.glob("*.css"))
    assert ".audit-detail" in css, "CSS thiếu .audit-detail"


@check("T4 n cap 1..500 không vỡ sau nâng cấp (9999/1/0 đều 200)")
async def t4():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        for n in (9999, 1, 0):
            r = c.get("/api/audit", params={"n": n})
            assert r.status_code == 200, (n, r.text[:120])
            assert isinstance(r.json()["entries"], list)


async def main():
    print(f"=== SUITE v0.30 Audit UI v2 — data tạm: {TMP} ===")
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
