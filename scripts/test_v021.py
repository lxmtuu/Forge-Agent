# -*- coding: utf-8 -*-
"""OAuth 2.1 suite (C6): PKCE vector RFC 7636 · state CSRF · exchange/refresh
· flow E2E loopback (fake provider) · sai state bị từ chối · endpoint server.

Chạy:  python scripts/test_v021.py
"""
import asyncio
import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import _test_auth
_test_auth.install()

TMP = Path(tempfile.mkdtemp(prefix="forge-v021-"))
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


class FakeTokenServer:
    """Token endpoint giả — ghi lại form/header để assert, trả token JSON."""

    def __init__(self):
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                ln = int(self.headers.get("Content-Length", 0))
                form = dict(urllib.parse.parse_qsl(self.rfile.read(ln).decode()))
                outer.requests.append({
                    "form": form,
                    "auth": self.headers.get("Authorization"),
                    "path": self.path,
                })
                body = json.dumps({
                    "access_token": f"FAKE-ACCESS-{len(outer.requests)}",
                    "refresh_token": f"FAKE-REFRESH-{len(outer.requests)}",
                    "expires_in": 3600, "scope": "test.read",
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/token"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


@check("T1 PKCE: vector chính thức RFC 7636 Appendix B (S256)")
async def t1():
    from engine.oauth import pkce_pair
    # code_verifier mẫu của RFC → challenge mẫu của RFC
    import engine.oauth as fo
    digest = hashlib.sha256(b"dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk").digest()
    expect = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert expect == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM", expect
    v, c = pkce_pair()
    assert 43 <= len(v) <= 128
    assert all(ch.isalnum() or ch in "-._~" for ch in v), "verifier sai charset RFC"
    # nhất quán nội bộ: challenge(verifier) luôn khớp
    d = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    assert d == c and len(c) == 43


@check("T2 state: mỗi lần 1 giá trị, đủ dài (≥24 ký tự) — chống CSRF")
async def t2():
    from engine.oauth import new_state
    a, b = new_state(), new_state()
    assert a != b and len(a) >= 24 and len(b) >= 24


@check("T3 exchange_code: form đúng (code_verifier/redirect_uri/client_id) · style=basic gửi Basic Auth · save/mask/has_auth")
async def t3():
    from engine import connectors as fc
    from engine import oauth as fo
    ts = FakeTokenServer()
    try:
        v, c = fo.pkce_pair()
        toks = fo.exchange_code(ts.url, "CODE123", v, "http://127.0.0.1:9999/callback",
                                "my-client", "my-secret", "post")
        r = ts.requests[-1]
        assert r["form"]["grant_type"] == "authorization_code"
        assert r["form"]["code"] == "CODE123" and r["form"]["code_verifier"] == v
        assert r["form"]["redirect_uri"] == "http://127.0.0.1:9999/callback"
        assert r["form"]["client_id"] == "my-client" and r["form"]["client_secret"] == "my-secret"
        # style=basic → Authorization Basic base64(id:secret), secret KHÔNG nằm trong form
        fo.exchange_code(ts.url, "C2", v, "http://x/cb", "nid", "nsec", "basic")
        r = ts.requests[-1]
        import base64 as b64
        assert r["auth"] == "Basic " + b64.b64encode(b"nid:nsec").decode(), r["auth"]
        assert "client_secret" not in r["form"]
        # lưu token → has_oauth/masked/has_auth + token thật KHÔNG lộ ở masked
        fo.save_tokens("fakeprov", toks)
        assert fo.has_oauth("fakeprov") and fc.has_auth("fakeprov")
        m = fo.masked("fakeprov")
        assert m and "FAKE-ACCESS" not in m, m
        raw = json.loads((TMP / "data" / "secrets.json").read_text())["fakeprov"]
        assert raw["oauth"]["access_token"] == toks["access_token"]  # file 600 lưu raw
        # token chưa hết hạn → trả ngay, KHÔNG gọi refresh
        n_before = len(ts.requests)
        assert fo.get_access_token("fakeprov") == toks["access_token"]
        assert len(ts.requests) == n_before
    finally:
        ts.stop()


@check("T4 refresh ngầm: token hết hạn → get_access_token tự refresh 1 lần và lưu token mới")
async def t4():
    from engine import connectors as fc
    from engine import oauth as fo
    ts = FakeTokenServer()
    from engine import connectors as _fc
    _fc.PRESETS["refprov"] = {"label": "Ref — test", "transport": "http", "url": "",
                              "auth": "oauth", "auth_hint": "test",
                              "oauth": {"authorize": "https://x/authorize", "token": ts.url,
                                        "scope": "x", "style": "post", "loopback_port": 0},
                              "headers": {}}
    try:
        fo.save_creds("refprov", "cid-r", "csec-r")
        fo.save_tokens("refprov", {"access_token": "OLD", "refresh_token": "RT",
                                   "expires_in": -100, "scope": "x"})  # đã hết hạn
        tok = fo.get_access_token("refprov")
        r = ts.requests[-1]
        assert r["form"]["grant_type"] == "refresh_token" and r["form"]["refresh_token"] == "RT"
        assert r["form"]["client_id"] == "cid-r"
        assert tok == "FAKE-ACCESS-1"
        ent = fc._load_secrets()["refprov"]["oauth"]
        assert ent["access_token"] == "FAKE-ACCESS-1" and ent["expires_at"] > time.time()
        # refresh hỏng → None, không ném
        fc.PRESETS["refprov"]["oauth"]["token"] = "http://127.0.0.1:1/token"
        fo.save_tokens("refprov", {"access_token": "OLD2", "refresh_token": "RT2",
                                   "expires_in": -100, "scope": "x"})
        assert fo.get_access_token("refprov") is None
    finally:
        ts.stop()
        _fc.PRESETS.pop("refprov", None)


@check("T5 E2E flow: loopback nhận code → PKCE khớp → đổi token → 'connected'; sai state bị TỪ CHỐI")
async def t5():
    import httpx
    from engine import connectors as fc
    from engine import oauth as fo
    ts = FakeTokenServer()
    fc.PRESETS["fakeprov"] = {
        "label": "Fake — test OAuth", "transport": "http", "url": "http://example.invalid/mcp",
        "auth": "oauth", "auth_hint": "test",
        "oauth": {"authorize": "https://auth.example/authorize", "token": ts.url,
                  "scope": "test.read", "style": "post", "loopback_port": 0},
        "headers": {},
    }
    try:
        def make_open(force_state: str | None = None, expect_cid: str = "cid-t5"):
            def _open(url: str) -> bool:
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
                assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
                assert q["response_type"] == "code" and q["client_id"] == expect_cid
                red = q["redirect_uri"]
                st = force_state or q["state"]
                httpx.get(f"{red}?code=TESTCODE&state={st}", timeout=5)
                t5.last_q = q
                return True
            return _open

        # (a) flow ĐÚNG state
        fo.save_creds("fakeprov", "cid-t5", "")
        msg = fo.connect("fakeprov", open_browser=False, _open=make_open())
        assert "✅" in msg and fo.flow_status("fakeprov")["status"] == "connected", msg
        q = t5.last_q
        ver = ts.requests[-1]["form"]["code_verifier"]
        calc = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).decode().rstrip("=")
        assert calc == q["code_challenge"], "code_verifier không khớp challenge trên authorize URL!"
        assert ts.requests[-1]["form"]["code"] == "TESTCODE"
        assert fo.masked("fakeprov")

        # (b) flow SAI state → từ chối, KHÔNG gọi token endpoint
        fc.PRESETS["fakeprov2"] = dict(fc.PRESETS["fakeprov"])
        fo.save_creds("fakeprov2", "cid-t5b", "")
        n_tok_calls = len(ts.requests)
        msg2 = fo.connect("fakeprov2", open_browser=False, _open=make_open("STATE-X", "cid-t5b"))
        assert "state không khớp" in msg2 and "❌" in msg2, msg2
        assert fo.flow_status("fakeprov2")["status"] == "error"
        assert len(ts.requests) == n_tok_calls, "sai state mà vẫn đổi token?!"
        assert not fo.has_oauth("fakeprov2")

        # (c) forget
        assert fo.forget("fakeprov") and not fo.has_oauth("fakeprov")
        assert not fo.forget("fakeprov2")  # không có gì để xoá
    finally:
        ts.stop()
        fc.PRESETS.pop("fakeprov", None)
        fc.PRESETS.pop("fakeprov2", None)


@check("T6 server: /api/connectors/presets shape · oauth/status idle · start preset lạ → 404")
async def t6():
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as c:
        r = c.get("/api/connectors/presets")
        assert r.status_code == 200
        rows = r.json()["presets"]
        ids = {x["id"] for x in rows}
        assert {"github", "notion", "linear", "sentry"} <= ids
        notion = next(x for x in rows if x["id"] == "notion")
        assert notion["oauth"] is True and notion["connected"] is False
        for k in ("label", "auth_hint", "installed", "masked"):
            assert k in notion
        st = c.get("/api/connectors/notion/oauth/status").json()
        assert st["status"] in ("idle", "pending", "connected", "error")
        assert c.post("/api/connectors/github-oops/oauth/start", json={}).status_code == 404
        assert c.get("/api/connectors/github-oops/oauth/status").status_code == 404


async def main():
    print(f"=== OAUTH 2.1 suite v0.21 — data tạm: {TMP} ===")
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
