"""Suite v0.35 — opt-in public signup + auth UX.

Không dùng credential thật, không gọi provider/Google. Chạy: python scripts/test_v035.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="forge-v035-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
for name in ("OPENROUTER_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "FORGE_CUSTOM_API_KEY",
             "FORGE_PROVIDER", "FORGE_MODEL", "FORGE_RELEASE_MODE", "FORGE_PUBLIC_URL",
             "FORGE_GOOGLE_CLIENT_ID", "FORGE_GOOGLE_CLIENT_SECRET", "FORGE_COOKIE_SECURE",
             "FORGE_ALLOW_REGISTRATION"):
    os.environ.pop(name, None)

PASSWORD = "v035-fake-password-not-a-real-secret"
PASS, FAIL = [], []


def check(name):
    def deco(fn):
        async def run():
            try:
                await fn()
                PASS.append(name)
                print(f"  ✓ {name}", flush=True)
            except Exception as exc:  # noqa: BLE001 — gom đủ lỗi trong test harness
                FAIL.append((name, str(exc)))
                print(f"  ✗ {name}: {exc}", flush=True)
                traceback.print_exc(limit=4)
        return run
    return deco


def make_user(label: str, role: str = "member"):
    from server.auth import auth_store
    return auth_store.create_user(f"{label}@forge.local", PASSWORD, label, role)


def csrf(client) -> dict:
    response = client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    data = response.json()
    client.headers["X-CSRF-Token"] = data["csrf_token"]
    return data


def login(client, user) -> None:
    csrf(client)
    response = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def register(client, email: str, password: str = PASSWORD, name: str = "Public", **extra):
    response = client.post("/api/auth/register", json={
        "email": email, "password": password, "name": name, **extra,
    })
    if response.status_code == 201:
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


def policy(enabled: bool) -> None:
    from server import auth as aw
    aw.auth_store.set_registration_enabled(enabled)
    aw._REGISTER_IP_RATE.clear()
    aw._REGISTER_EMAIL_RATE.clear()


def create_session(client, title: str) -> str:
    response = client.post("/api/sessions", json={"title": title})
    assert response.status_code == 200, response.text
    return response.json()["session"]["id"]


@check("T1 Signup cần admin bootstrap · env chỉ là default · DB override tồn tại")
async def t1():
    from fastapi.testclient import TestClient

    from server import auth as aw
    from server.main import app
    os.environ["FORGE_ALLOW_REGISTRATION"] = "1"
    try:
        assert not aw.auth_store.has_users()
        with TestClient(app) as client:
            state = csrf(client)
            assert state["needs_setup"] is True and state["registration_enabled"] is False
            denied = register(client, "too-early@forge.local")
            assert denied.status_code == 503, denied.text
            assert aw.auth_store.get_by_email("too-early@forge.local") is None
        make_user("v035-admin", "admin")
        with TestClient(app) as client:
            assert csrf(client)["registration_enabled"] is True
            aw.auth_store.set_registration_enabled(False)
            assert csrf(client)["registration_enabled"] is False
    finally:
        os.environ.pop("FORGE_ALLOW_REGISTRATION", None)
        policy(False)


@check("T2 Chỉ admin đổi policy · signup tắt + thiếu CSRF đều bị chặn")
async def t2():
    from fastapi.testclient import TestClient

    from server.main import app
    admin = aw_user = make_user("v035-policy-admin", "admin")
    member = make_user("v035-policy-member")
    policy(False)
    with TestClient(app) as a, TestClient(app) as m, TestClient(app) as anon:
        login(m, member)
        assert m.get("/api/auth/registration/config").status_code == 403
        assert m.put("/api/auth/registration/config", json={"enabled": True}).status_code == 403
        assert anon.post("/api/auth/register", json={}).status_code == 403
        csrf(anon)
        assert register(anon, "disabled@forge.local").status_code == 403
        login(a, aw_user)
        assert a.get("/api/auth/registration/config").json() == {"enabled": False}
        changed = a.put("/api/auth/registration/config", json={"enabled": True})
        assert changed.status_code == 200 and changed.json() == {"enabled": True}
        assert csrf(anon)["registration_enabled"] is True
        assert admin.role == "admin"


@check("T3 Public signup validate · member-only · auto-login · duplicate 409 · role injection 422")
async def t3():
    from fastapi.testclient import TestClient

    from engine.auth import SESSION_COOKIE
    from server import auth as aw
    from server.main import app
    policy(True)
    with TestClient(app) as client:
        csrf(client)
        assert register(client, "not-an-email").status_code == 400
        assert register(client, "short-password@forge.local", "short").status_code == 400
        injected = register(client, "role-injection@forge.local", role="admin")
        assert injected.status_code == 422, injected.text
        response = register(client, "public-member@forge.local", name="Public Member")
        assert response.status_code == 201, response.text
        assert PASSWORD not in response.text
        data = response.json()
        assert data["user"]["role"] == "member" and data["user"]["enabled"] is True
        assert "httponly" in response.headers.get("set-cookie", "").lower()
        assert client.cookies.get(SESSION_COOKIE)
        assert client.get("/api/auth/me").json()["user"]["id"] == data["user"]["id"]
        sid = create_session(client, "Owned by public member")
        stored = __import__("engine.session", fromlist=["SessionStore"]).SessionStore().get(sid)
        assert stored.owner_id == data["user"]["id"]
        duplicate = register(client, "public-member@forge.local")
        assert duplicate.status_code == 409, duplicate.text
        assert client.put("/api/auth/registration/config", json={"enabled": False}).status_code == 403
        assert aw.auth_store.get_by_email("public-member@forge.local").role == "member"
    policy(False)


@check("T4 Tắt signup chặn user mới nhưng giữ user cũ · disable vẫn revoke session")
async def t4():
    from fastapi.testclient import TestClient

    from server import auth as aw
    from server.main import app
    admin = aw.auth_store.get_by_email("v035-admin@forge.local")
    member = aw.auth_store.get_by_email("public-member@forge.local")
    policy(True)
    with TestClient(app) as a, TestClient(app) as m, TestClient(app) as anon:
        login(a, admin); login(m, member)
        assert a.put("/api/auth/registration/config", json={"enabled": False}).status_code == 200
        csrf(anon)
        assert register(anon, "after-close@forge.local").status_code == 403
        assert m.get("/api/sessions").status_code == 200
        disabled = a.patch(f"/api/auth/users/{member.id}", json={"enabled": False})
        assert disabled.status_code == 200, disabled.text
        assert m.get("/api/sessions").status_code == 401


@check("T5 Rate-limit theo IP và email · Retry-After · request bị chặn không tạo user")
async def t5():
    from fastapi.testclient import TestClient

    from server import auth as aw
    from server.main import app
    policy(True)
    with TestClient(app) as client:
        csrf(client)
        for index in range(5):
            response = register(client, f"ip-limit-{index}@forge.local", "short")
            assert response.status_code == 400, (index, response.status_code, response.text)
        limited = register(client, "ip-limit-final@forge.local")
        assert limited.status_code == 429, limited.text
        assert int(limited.headers["Retry-After"]) > 0
        assert aw.auth_store.get_by_email("ip-limit-final@forge.local") is None

        aw._REGISTER_IP_RATE.clear(); aw._REGISTER_EMAIL_RATE.clear()
        for _ in range(3):
            assert register(client, "email-limit@forge.local", "short").status_code == 400
        limited = register(client, "email-limit@forge.local")
        assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0
        assert aw.auth_store.get_by_email("email-limit@forge.local") is None
    policy(False)


@check("T6 Google chỉ self-signup khi policy mở · member-only · OIDC scope không đổi")
async def t6():
    from fastapi.testclient import TestClient

    from engine import google_auth
    from server import auth as aw
    from server.main import app
    policy(False)
    aw.auth_store.save_google_config("fake-v035.apps.googleusercontent.com", "fake-oauth-secret",
                                    "http://localhost:8000")
    original_exchange, original_verify = google_auth.exchange_code, google_auth.verify_id_token
    identity = {"sub": "google-public-v035", "email": "google-public@forge.local",
                "name": "Google Public", "picture": ""}

    async def fake_exchange(*args):
        return {"id_token": "fake-id-token", "access_token": "not-stored"}

    async def fake_verify(*args):
        return identity

    google_auth.exchange_code, google_auth.verify_id_token = fake_exchange, fake_verify
    try:
        with TestClient(app) as client:
            def callback():
                start = client.get("/api/auth/google/start", follow_redirects=False)
                assert start.status_code == 302
                query = parse_qs(urlparse(start.headers["location"]).query)
                assert query["scope"] == ["openid email profile"]
                assert query["code_challenge_method"] == ["S256"]
                assert "gmail" not in start.headers["location"].lower()
                return client.get("/api/auth/google/callback",
                                  params={"code": "fake", "state": query["state"][0]},
                                  follow_redirects=False)

            denied = callback()
            assert "error=not_invited" in denied.headers["location"]
            assert aw.auth_store.get_by_email(identity["email"]) is None
            policy(True)
            client.cookies.clear()
            accepted = callback()
            assert accepted.status_code == 303 and accepted.headers["location"] == "/"
            created = aw.auth_store.get_by_email(identity["email"])
            assert created.role == "member" and created.google_linked is True

            policy(False)
            identity = {"sub": "google-closed-v035", "email": "google-closed@forge.local",
                        "name": "Closed", "picture": ""}
            client.cookies.clear()
            denied = callback()
            assert "error=not_invited" in denied.headers["location"]
            assert aw.auth_store.get_by_email(identity["email"]) is None
    finally:
        google_auth.exchange_code, google_auth.verify_id_token = original_exchange, original_verify
        policy(False)


@check("T7 Production bundle có form signup/toggle/trạng thái Google · không còn UX ẩn policy")
async def t7():
    bundles = list((ROOT / "server" / "static" / "assets").glob("*.js"))
    assert bundles
    js = "\n".join(p.read_text(encoding="utf-8") for p in bundles)
    for marker in ("Đăng ký và đăng nhập", "registration_enabled", "/api/auth/register",
                   "Cho phép tự đăng ký tài khoản member", "Google login chưa được admin cấu hình",
                   "Liên hệ admin"):
        assert marker in js, marker
    assert "X-CSRF-Token" in js and "Google OpenID Connect" in js


@check("T8 Hai public member tự đăng ký vẫn bị owner ACL tách session")
async def t8():
    from fastapi.testclient import TestClient

    from server.main import app
    policy(True)
    with TestClient(app) as a, TestClient(app) as b:
        csrf(a); csrf(b)
        ra = register(a, "public-owner-a@forge.local")
        rb = register(b, "public-owner-b@forge.local")
        assert ra.status_code == 201 and rb.status_code == 201
        sid_a = create_session(a, "Public A only")
        sid_b = create_session(b, "Public B only")
        assert a.get(f"/api/sessions/{sid_b}").status_code == 404
        assert b.get(f"/api/sessions/{sid_a}").status_code == 404
        ids_a = {row["id"] for row in a.get("/api/sessions").json()["sessions"]}
        ids_b = {row["id"] for row in b.get("/api/sessions").json()["sessions"]}
        assert sid_a in ids_a and sid_b not in ids_a
        assert sid_b in ids_b and sid_a not in ids_b
    policy(False)


async def main():
    print(f"=== SUITE v0.35 Public signup + auth UX — data tạm: {TMP} ===")
    for test in (t1, t2, t3, t4, t5, t6, t7, t8):
        await test()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
