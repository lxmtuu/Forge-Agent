# -*- coding: utf-8 -*-
"""Smoke suite v0.19 "Local & Tìm kiếm":
D2 local models (base URL tuỳ chỉnh — chọn endpoint/headers đúng, không ép key)
· E2 /rename · E3 tìm phiên (tiêu đề + nội dung) · settings roundtrip base_url.

Chạy:  python scripts/test_v020.py
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

TMP = Path(tempfile.mkdtemp(prefix="forge-v020-"))
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


# ───────────── T1: endpoint resolution (D2) ─────────────
@check("T1 D2 endpoint: mặc định OpenRouter ép key · base_url local KHÔNG cần key · custom key có Bearer")
async def t1():
    from engine import config as fcfg
    from engine.llm import LLMError, _endpoint
    orig = fcfg.load_config
    try:
        # 1) mặc định: OpenRouter + bắt buộc key
        fcfg.load_config = lambda: {}
        try:
            _endpoint(None)
            raise AssertionError("không có key mà không raise?")
        except LLMError as e:
            assert "OPENROUTER_API_KEY" in str(e)
        url, h = _endpoint("sk-or-v1-abc")
        assert url == "https://openrouter.ai/api/v1/chat/completions"
        assert h["Authorization"] == "Bearer sk-or-v1-abc"
        # 2) base_url local, KHÔNG key nào → được phép, không Authorization
        fcfg.load_config = lambda: {"custom_base_url": "http://localhost:11434/v1/"}
        url, h = _endpoint(None)
        assert url == "http://localhost:11434/v1/chat/completions", url
        assert "Authorization" not in h, "Ollama không cần Bearer"
        assert h["Content-Type"] == "application/json"
        # 3) base_url + custom key → Bearer key đó
        fcfg.load_config = lambda: {"custom_base_url": "http://localhost:1234/v1",
                                    "custom_api_key": "lm-studio-key-1"}
        url, h = _endpoint(None)
        assert url == "http://localhost:1234/v1/chat/completions"
        assert h["Authorization"] == "Bearer lm-studio-key-1"
        # 4) api_key tham số thắng custom key
        url, h = _endpoint("override-key")
        assert h["Authorization"] == "Bearer override-key"
    finally:
        fcfg.load_config = orig


# ───────────── T2: cost ẩn với local ─────────────
@check("T2 cost: base_url local → estimate trả None (không gọi giá OpenRouter)")
async def t2():
    from engine import config as fcfg
    from engine import cost
    orig = fcfg.load_config
    fcfg.load_config = lambda: {"custom_base_url": "http://localhost:11434/v1"}
    try:
        assert await cost.estimate("llama3.2", {"prompt_tokens": 100}) is None
    finally:
        fcfg.load_config = orig


# ───────────── T3: rename + tìm phiên (E2 + E3) ─────────────
@check("T3 E2+E3: store.rename persists · list(q) tìm theo NỘI DUNG + tiêu đề · q rỗng = tất cả")
async def t3():
    from engine.session import SessionStore
    store = SessionStore()
    a = store.create()
    sa = store.get(a.id)
    sa.messages.append({"role": "user", "content": "học phục hồi dữ liệu RAID bằng ddrescue"})
    store.save(sa)
    b = store.create()
    assert store.rename(a.id, "Khôi phục RAID") is True
    assert store.get(a.id).title == "Khôi phục RAID"
    assert store.rename("khong-ton-tai", "x") is False
    # tìm theo NỘI DUNG (không nằm trong title)
    rows = store.list(q="ddrescue")
    assert any(r["id"] == a.id for r in rows), rows
    # tìm theo TIÊU ĐỀ
    rows = store.list(q="khôi phục")
    assert any(r["id"] == a.id for r in rows)
    # q rỗng → tất cả
    assert len(store.list()) >= 2
    assert len(store.list(q="zzz-khong-co")) == 0


# ───────────── T4: server rename + sessions?q= ─────────────
@check("T4 server: POST /rename (200/404) · GET /api/sessions?q= lọc server-side")
async def t4():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        sid = c.post("/api/sessions", json={"title": "t4"}).json()["session"]["id"]
        r = c.post(f"/api/sessions/{sid}/rename", json={"title": "Phiên đã đổi tên"})
        assert r.status_code == 200 and r.json()["ok"], r.text[:150]
        assert c.get(f"/api/sessions/{sid}").json()["session"]["title"] == "Phiên đã đổi tên"
        assert c.post("/api/sessions/khong-co/rename", json={"title": "x"}).status_code == 404
        # q tìm server-side theo nội dung demo đã lưu? tạo nội dung qua ghi file session trực tiếp
        s = c.get(f"/api/sessions/{sid}").json()["session"]
        # q khớp title
        rows = c.get("/api/sessions", params={"q": "đổi tên"}).json()["sessions"]
        assert any(x["id"] == sid for x in rows), rows
        assert all("đổi tên" in x["title"].lower() for x in rows)
        assert c.get("/api/sessions", params={"q": "zzz-khong-co"}).json()["sessions"] == []


# ───────────── T5: settings roundtrip base_url ─────────────
@check("T5 settings: POST custom_base_url (có/không đuôi /) → health phản ánh → llm dùng ngay")
async def t5():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        r = c.post("/api/settings", json={"custom_base_url": "http://localhost:11434/v1/"})
        assert r.status_code == 200
        assert r.json()["custom_base_url"] == "http://localhost:11434/v1", r.json()["custom_base_url"]
        # llm thấy ngay (cùng config.json)
        from engine.llm import _endpoint
        url, h = _endpoint(None)
        assert url == "http://localhost:11434/v1/chat/completions"
        # xoá base_url (chuỗi rỗng) → về OpenRouter
        r = c.post("/api/settings", json={"custom_base_url": ""})
        assert r.json()["custom_base_url"] == ""
        from engine.llm import LLMError
        try:
            _endpoint(None)
            raise AssertionError("về OpenRouter mà không cần key?")
        except LLMError:
            pass


async def main():
    print(f"=== SMOKE v0.19 Local & Tìm kiếm — data tạm: {TMP} ===")
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
