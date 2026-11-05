"""Suite v0.34 Phase 1 — private multi-user + multi-provider.

Không dùng compatibility fixture, không đọc credential thật, không gọi provider/Google.
Chạy: python scripts/test_v034.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="forge-v034-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
for name in ("OPENROUTER_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "FORGE_CUSTOM_API_KEY",
             "FORGE_PROVIDER", "FORGE_MODEL", "FORGE_RELEASE_MODE", "FORGE_PUBLIC_URL",
             "FORGE_GOOGLE_CLIENT_ID", "FORGE_GOOGLE_CLIENT_SECRET", "FORGE_COOKIE_SECURE",
             "FORGE_ALLOW_REGISTRATION"):
    os.environ.pop(name, None)

PASSWORD = "phase1-fake-password-not-a-real-secret"
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


def csrf(client) -> str:
    response = client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    token = response.json()["csrf_token"]
    client.headers["X-CSRF-Token"] = token
    return token


def login(client, user) -> None:
    csrf(client)
    response = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def create_session(client, title="Phase 1") -> str:
    response = client.post("/api/sessions", json={"title": title})
    assert response.status_code == 200, response.text
    return response.json()["session"]["id"]


@check("T1 AuthStore: password/session chỉ hash · revoke/disable · OAuth flow dùng một lần")
async def t1():
    import sqlite3

    from engine.auth import AuthStore, token_hash
    db = AuthStore(TMP / "auth-unit.db")
    user = db.create_user("Admin@Example.com", PASSWORD, "Admin", "admin")
    assert db.authenticate("admin@example.com", PASSWORD).id == user.id
    assert db.authenticate("admin@example.com", PASSWORD + "x") is None
    token = db.create_session(user.id)
    assert db.user_for_session(token).id == user.id
    raw = (TMP / "auth-unit.db").read_bytes()
    assert PASSWORD.encode() not in raw and token.encode() not in raw
    with sqlite3.connect(TMP / "auth-unit.db") as conn:
        stored = conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
        assert stored == token_hash(token) and stored != token
    db.revoke_session(token)
    assert db.user_for_session(token) is None
    token2 = db.create_session(user.id)
    db.link_google(user.id, "google-sub-a", user.email)
    assert db.user_by_google("google-sub-a").id == user.id
    try:
        db.link_google(user.id, "google-sub-b", user.email)
        raise AssertionError("Google subject khác bị chấp nhận cho cùng user")
    except ValueError:
        pass
    db.set_enabled(user.id, False)
    assert db.user_for_session(token2) is None
    flow = db.create_oauth_flow()
    assert db.consume_oauth_flow(flow["state"])["nonce"] == flow["nonce"]
    assert db.consume_oauth_flow(flow["state"]) is None


@check("T2 Anonymous + CSRF: health/login UI public · API private · mutation thiếu CSRF 403")
async def t2():
    from fastapi.testclient import TestClient

    from server.main import app
    user = make_user("t2")
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert "key_masked" not in health.json() and "custom_base_url" not in health.json()
        assert client.get("/api/sessions").status_code == 401
        assert client.get("/").status_code == 200
        assert client.post("/api/sessions", json={}).status_code == 403
        csrf(client)
        assert client.post("/api/sessions", json={}).status_code == 401
        login(client, user)
        client.headers.pop("X-CSRF-Token")
        assert client.post("/api/sessions", json={}).status_code == 403
        client.headers["X-CSRF-Token"] = csrf(client)
        assert client.post("/api/sessions", json={}).status_code == 200


@check("T3 Email login: cookie HttpOnly · session rotation · logout revoke · không trả password")
async def t3():
    from fastapi.testclient import TestClient

    from engine.auth import SESSION_COOKIE
    from server.auth import auth_store
    from server.main import app
    user = make_user("t3")
    with TestClient(app) as client:
        csrf(client)
        wrong = client.post("/api/auth/login", json={"email": user.email, "password": "wrong"})
        assert wrong.status_code == 401
        response = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
        assert response.status_code == 200 and PASSWORD not in response.text
        cookie = response.headers.get("set-cookie", "").lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        first = client.cookies.get(SESSION_COOKIE)
        assert auth_store.user_for_session(first).id == user.id
        csrf(client)
        again = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
        second = client.cookies.get(SESSION_COOKIE)
        assert again.status_code == 200 and second != first
        assert auth_store.user_for_session(first) is None
        client.headers["X-CSRF-Token"] = again.json()["csrf_token"]
        assert client.post("/api/auth/logout").status_code == 204
        assert auth_store.user_for_session(second) is None
        assert client.get("/api/settings").status_code == 401


@check("T4 Private team: admin mời/tạo member · member không quản trị · disable revoke · giữ last admin")
async def t4():
    from fastapi.testclient import TestClient

    from server.main import app
    admin = make_user("t4-admin", "admin")
    with TestClient(app) as a, TestClient(app) as m:
        login(a, admin)
        invited = a.post("/api/auth/users", json={"email": "t4-member@forge.local",
                                                  "password": PASSWORD, "role": "member"})
        assert invited.status_code == 200, invited.text
        member_id = invited.json()["id"]
        member = __import__("server.auth", fromlist=["auth_store"]).auth_store.get(member_id)
        login(m, member)
        assert m.get("/api/auth/users").status_code == 403
        assert m.post("/api/settings", json={"model": "openrouter:openrouter/free"}).status_code == 403
        assert m.post("/api/mcp", json={"name": "x", "command": "x"}).status_code == 403
        assert a.post("/api/sessions/no-such/chat", json={"text": "x"}).status_code == 404
        disabled = a.patch(f"/api/auth/users/{member_id}", json={"enabled": False})
        assert disabled.status_code == 200
        assert m.get("/api/sessions").status_code == 401
        assert a.patch(f"/api/auth/users/{admin.id}", json={"enabled": False}).status_code == 400


@check("T5 Owner ACL: session/fork/export/workspace/loop/messages/worktree của user khác đều không truy cập được")
async def t5():
    from fastapi.testclient import TestClient

    from server.main import app
    ua, ub = make_user("t5a"), make_user("t5b")
    with TestClient(app) as a, TestClient(app) as b:
        login(a, ua)
        login(b, ub)
        sid_a = create_session(a, "private A")
        sid_b = create_session(b, "private B")
        assert sid_a not in {r["id"] for r in b.get("/api/sessions").json()["sessions"]}
        assert b.get(f"/api/sessions/{sid_a}").status_code == 404
        assert b.post(f"/api/sessions/{sid_a}/rename", json={"title": "stolen"}).status_code == 404
        assert b.post(f"/api/sessions/{sid_a}/fork").status_code == 404
        assert b.get(f"/api/sessions/{sid_a}/export").status_code == 404
        assert b.get("/api/workspace/tree", params={"sid": sid_a}).status_code == 404
        assert b.get("/api/workspace/file", params={"sid": sid_a, "path": "x"}).status_code == 404
        assert b.put("/api/workspace/file", params={"sid": sid_a},
                     json={"path": "x", "content": "bad"}).status_code == 404
        assert b.post("/api/workspace/exec", params={"sid": sid_a}, json={"command": "pwd"}).status_code == 404
        assert b.post(f"/api/sessions/{sid_a}/loop", json={"text": "x"}).status_code == 404
        assert b.get(f"/api/sessions/{sid_a}/messages").status_code == 404
        assert b.post(f"/api/sessions/{sid_a}/messages", json={"text": "cross"}).status_code == 404
        assert b.post(f"/api/worktrees/{sid_a}/merge", params={"sid": sid_b}).status_code == 404
        assert b.delete(f"/api/worktrees/{sid_a}", params={"sid": sid_b}).status_code == 404
        written = a.put("/api/workspace/file", params={"sid": sid_a},
                        json={"path": "private.txt", "content": "A only"})
        assert written.status_code == 200
        assert a.get("/api/workspace/file", params={"sid": sid_a, "path": "private.txt"}).json()["content"] == "A only"
        forked = a.post(f"/api/sessions/{sid_a}/fork")
        assert forked.status_code == 200
        assert a.get(f"/api/sessions/{forked.json()['session']['id']}").status_code == 200
        b.delete(f"/api/sessions/{sid_a}")
        assert a.get(f"/api/sessions/{sid_a}").status_code == 200


@check("T6 Audit/usage/inbox/approval/elicitation đều scoped theo owner")
async def t6():
    from fastapi.testclient import TestClient

    from engine import approvals, auditlog, elicitations
    from server.main import app
    ua, ub = make_user("t6a"), make_user("t6b")
    with TestClient(app) as a, TestClient(app) as b:
        login(a, ua)
        login(b, ub)
        sid_a, sid_b = create_session(a), create_session(b)
        auditlog.log_tool(sid_a, "write_file", {"path": "a"}, True)
        auditlog.log_tool(sid_b, "write_file", {"path": "b"}, True)
        rows_a = a.get("/api/audit").json()["entries"]
        rows_b = b.get("/api/audit").json()["entries"]
        assert {r["session"] for r in rows_a} == {sid_a}
        assert {r["session"] for r in rows_b} == {sid_b}
        assert a.get("/api/usage").json()["sessions"] == 1
        assert b.get("/api/usage").json()["sessions"] == 1
        assert b.post(f"/api/sessions/{sid_a}/messages", json={"text": "bad"}).status_code == 404
        aid = approvals.create("echo test", "warn", ["test"], owner_id=ua.id)
        assert b.post(f"/api/approvals/{aid}", json={"decision": "approve"}).status_code == 404
        assert a.post(f"/api/approvals/{aid}", json={"decision": "deny"}).status_code == 200
        approvals.PENDING.pop(aid, None)
        tokens = elicitations.bind_session(ua.id, sid_a)
        eid = elicitations.create("fake", "question", {"type": "object", "properties": {}})
        elicitations.reset_session(tokens)
        assert not any(r["id"] == eid for r in b.get("/api/elicitations").json()["pending"])
        assert b.post(f"/api/elicitation/{eid}", json={"action": "accept"}).status_code == 404
        assert any(r["id"] == eid for r in a.get("/api/elicitations").json()["pending"])
        assert a.post(f"/api/elicitation/{eid}", json={"action": "cancel"}).status_code == 200
        elicitations.PENDING.pop(eid, None)


@check("T7 Legacy session owner rỗng không tự lộ; chỉ migration tường minh mới gán owner")
async def t7():
    from engine.session import ScopedSessionStore, SessionStore
    base = SessionStore()
    legacy = base.create(title="legacy")
    user = make_user("t7")
    scoped = ScopedSessionStore(base, user.id)
    assert scoped.get(legacy.id) is None
    assert legacy.id not in {r["id"] for r in scoped.list()}
    from scripts.migrate_sessions import migrate
    count, ids = migrate(user.email)  # dry-run không được tự gán owner
    assert count == 1 and ids == [legacy.id] and base.get(legacy.id).owner_id == ""
    count, ids = migrate(user.email, apply=True)
    assert count == 1 and ids == [legacy.id]
    assert scoped.get(legacy.id).title == "legacy"
    assert migrate(user.email)[0] == 0


@check("T8 Registry: prefix/provider không nhầm google vendor · capability · image adapter fail-closed")
async def t8():
    from engine import llm
    from engine.models import ModelCapabilityError, ModelRegistry
    registry = ModelRegistry()
    direct = registry.get("google:gemini-3.8-flash")
    vendor = registry.get("openrouter:google/gemini-3.8-flash")
    assert direct.provider == "google" and vendor.provider == "openrouter"
    assert direct.id != vendor.id and direct.model != vendor.model
    assert registry.canonical("openai/gpt-5.3-codex", "openrouter") == "openrouter:openai/gpt-5.3-codex"
    assert llm.resolve_model("openrouter:openai/gpt-5.3:online").endswith(":online")
    try:
        registry.route("image_generation")
        raise AssertionError("image adapter không được phép tồn tại trong Phase 1")
    except ModelCapabilityError:
        pass
    override = ModelRegistry.make_spec("openrouter:test/text-only", ["reasoning"])
    try:
        registry.route("vision", override.id)
        raise AssertionError("model không vision mà route vision thành công")
    except ModelCapabilityError:
        pass


@check("T9 Hai call đồng thời route Google/OpenRouter · payload model sạch · không mutate global provider")
async def t9():
    from engine import config, llm
    os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-FAKE-V034-not-real"
    os.environ["GOOGLE_API_KEY"] = "AIza-FAKE-V034-not-real"
    config.save_config({"provider": "openrouter", "model": "openrouter:openrouter/free"})
    calls = []

    class FakeResponse:
        status_code = 200
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}'
            yield "data: [DONE]"

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()
        async def __aexit__(self, *args):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        def stream(self, method, url, headers, json):
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeStream()

    original = llm.httpx.AsyncClient
    llm.httpx.AsyncClient = FakeClient
    try:
        async def collect(model):
            return [e async for e in llm.stream_chat([{"role": "user", "content": "x"}], model=model)]
        await asyncio.gather(collect("openrouter:vendor/code-model"),
                             collect("google:gemini-3.8-flash"))
    finally:
        llm.httpx.AsyncClient = original
        os.environ.pop("OPENROUTER_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
    assert len(calls) == 2
    by_url = {c["url"]: c for c in calls}
    assert by_url[llm.OPENROUTER_URL]["json"]["model"] == "vendor/code-model"
    assert by_url[llm.GOOGLE_OPENAI_URL]["json"]["model"] == "gemini-3.8-flash"
    assert by_url[llm.OPENROUTER_URL]["headers"]["Authorization"].startswith("Bearer sk-or-v1-FAKE")
    assert by_url[llm.GOOGLE_OPENAI_URL]["headers"]["Authorization"].startswith("Bearer AIza-FAKE")
    assert config.get_provider() == "openrouter"


@check("T10 Batch/background path giữ owner và canonical model khi chạy demo thật")
async def t10():
    from engine.agent import run_batch
    from engine.models import router
    from engine.session import ScopedSessionStore, SessionStore
    user = make_user("t10")
    scoped = ScopedSessionStore(SessionStore(), user.id)
    events = [e async for e in run_batch(scoped, [{"prompt": "demo batch", "model": "google:gemini-3.8-flash"}],
                                        demo=True, router=router)]
    created = next(e for e in events if e["type"] == "task_created")
    assert created["model"] == "google:gemini-3.8-flash"
    assert scoped.get(created["session_id"]).owner_id == user.id
    assert any(e["type"] == "batch_done" for e in events)


@check("T11 Google flow: PKCE/state/nonce · scope chỉ OIDC · callback một lần · uninvited bị từ chối")
async def t11():
    from fastapi.testclient import TestClient

    from engine import google_auth
    from engine.auth import OAUTH_COOKIE, SESSION_COOKIE, AuthStore
    from server import auth as aw
    from server.main import app
    try:
        aw.auth_store.db_path.unlink()
    except FileNotFoundError:
        pass
    aw.auth_store = AuthStore()
    aw.auth_store.save_google_config("fake-client.apps.googleusercontent.com", "fake-oauth-secret",
                                    "http://localhost:8000")
    original_exchange, original_verify = google_auth.exchange_code, google_auth.verify_id_token
    identity = {"sub": "google-sub-t11", "email": "google-admin@forge.local",
                "name": "Google Admin", "picture": ""}
    async def fake_exchange(*args):
        return {"id_token": "fake-id-token", "access_token": "not-stored"}
    async def fake_verify(*args):
        return identity
    google_auth.exchange_code, google_auth.verify_id_token = fake_exchange, fake_verify
    try:
        with TestClient(app) as client:
            start = client.get("/api/auth/google/start", follow_redirects=False)
            assert start.status_code == 302
            query = parse_qs(urlparse(start.headers["location"]).query)
            assert query["scope"] == ["openid email profile"]
            assert query["code_challenge_method"] == ["S256"] and query["access_type"] == ["online"]
            assert "gmail" not in start.headers["location"].lower()
            state = query["state"][0]
            assert query["nonce"][0] and query["code_challenge"][0]
            callback = client.get("/api/auth/google/callback", params={"code": "fake", "state": state},
                                  follow_redirects=False)
            assert callback.status_code == 303 and callback.headers["location"] == "/", (callback.status_code, dict(callback.headers), callback.text)
            assert client.cookies.get(SESSION_COOKIE)
            assert aw.auth_store.user_by_google("google-sub-t11").role == "admin"
            # Replay state: cookie bị xoá nên đặt lại đúng state để chắc chắn test tới DB consume.
            client.cookies.set(OAUTH_COOKIE, state, path="/api/auth/google")
            replay = client.get("/api/auth/google/callback", params={"code": "fake", "state": state},
                                follow_redirects=False)
            assert "error=google_replay" in replay.headers["location"]
            # User Google mới sau bootstrap không được public signup.
            identity = {"sub": "google-sub-uninvited", "email": "uninvited@forge.local",
                        "name": "No", "picture": ""}
            client.cookies.clear()
            start2 = client.get("/api/auth/google/start", follow_redirects=False)
            state2 = parse_qs(urlparse(start2.headers["location"]).query)["state"][0]
            denied = client.get("/api/auth/google/callback", params={"code": "fake", "state": state2},
                                follow_redirects=False)
            assert "error=not_invited" in denied.headers["location"], (denied.status_code, dict(denied.headers), denied.text)
    finally:
        google_auth.exchange_code, google_auth.verify_id_token = original_exchange, original_verify


@check("T12 Verify Google JWT RS256 bằng JWKS local · issuer/aud/exp/nonce/email_verified đều bắt buộc")
async def t12():
    from authlib.jose import RSAKey, jwt

    from engine.google_auth import GoogleAuthError, verify_id_token
    key = RSAKey.generate_key(2048, is_private=True)
    public = key.as_dict()
    public.update({"kid": "v034-test", "alg": "RS256", "use": "sig"})
    now = int(time.time())
    payload = {"iss": "https://accounts.google.com", "aud": "fake-client",
               "sub": "stable-google-sub", "email": "oidc@forge.local", "email_verified": True,
               "name": "OIDC", "nonce": "expected-nonce", "iat": now, "exp": now + 300}
    token = jwt.encode({"alg": "RS256", "typ": "JWT", "kid": "v034-test"}, payload, key).decode()
    claims = await verify_id_token(token, "fake-client", "expected-nonce", {"keys": [public]})
    assert claims["sub"] == "stable-google-sub" and claims["email"] == "oidc@forge.local"
    for mutate in ({"nonce": "wrong"}, {"aud": "other-client"}, {"email_verified": False}):
        bad_payload = {**payload, **mutate}
        bad = jwt.encode({"alg": "RS256", "typ": "JWT", "kid": "v034-test"}, bad_payload, key).decode()
        try:
            await verify_id_token(bad, "fake-client", "expected-nonce", {"keys": [public]})
            raise AssertionError(f"claim sai được chấp nhận: {mutate}")
        except GoogleAuthError:
            pass
    try:
        await verify_id_token(token[:-2] + "xx", "fake-client", "expected-nonce", {"keys": [public]})
        raise AssertionError("chữ ký hỏng được chấp nhận")
    except GoogleAuthError:
        pass


@check("T13 Model API không trả endpoint/secret · image capability trả adapter=false · chat image 501")
async def t13():
    from fastapi.testclient import TestClient

    import server.main as sm
    user = make_user("t13")
    sm._MODELS_CACHE = {"ts": time.time(), "data": [{
        "id": "openrouter:fake/model", "provider": "openrouter", "model": "fake/model",
        "name": "Fake", "capabilities": ["code", "reasoning", "tools"], "adapter": "chat",
    }]}
    with TestClient(sm.app) as client:
        login(client, user)
        catalog = client.get("/api/models")
        assert catalog.status_code == 200
        text = catalog.text.lower()
        assert "api_key" not in text and "authorization" not in text and "chat/completions" not in text
        assert any(row["provider"] == "google" for row in catalog.json()["models"])
        image = client.get("/api/models", params={"capability": "image_generation"})
        assert image.status_code == 200 and image.json()["count"] == 0
        assert image.json()["image_generation_adapter"] is False
        sid = create_session(client)
        response = client.post(f"/api/sessions/{sid}/chat",
                               json={"text": "make an image", "capability": "image_generation"})
        assert response.status_code == 501, response.text


@check("T14 setup_auth CLI không echo secret · Web bundle có login/CSRF/Team · image vẫn không quảng bá adapter")
async def t14():
    import argparse
    import contextlib
    import io

    from scripts import setup_auth
    from server import auth as aw
    try:
        aw.auth_store.db_path.unlink()
    except FileNotFoundError:
        pass
    from engine.auth import AuthStore
    aw.auth_store = AuthStore()
    output = io.StringIO()
    original = setup_auth.getpass.getpass
    original_input = getattr(setup_auth, "input", None)
    try:
        setup_auth.input = lambda _prompt: "cli-admin@forge.local"
        setup_auth.getpass.getpass = lambda _prompt: PASSWORD
        with contextlib.redirect_stdout(output):
            rc = setup_auth.create_user(argparse.Namespace(email=None, name="CLI",
                                                             role="admin", google_only=False))
        assert rc == 0
        setup_auth.getpass.getpass = lambda _prompt: "fake-google-client-secret-v034"
        with contextlib.redirect_stdout(output):
            rc = setup_auth.configure_google(argparse.Namespace(client_id="fake-client-id",
                                                                 public_url="http://localhost:8000"))
        assert rc == 0 and setup_auth.check() == 0
    finally:
        setup_auth.getpass.getpass = original
        if original_input is None:
            del setup_auth.input
        else:
            setup_auth.input = original_input
    printed = output.getvalue()
    assert PASSWORD not in printed and "fake-google-client-secret-v034" not in printed
    assert aw.auth_store.google_config()["client_secret"] == "fake-google-client-secret-v034"
    bundles = list((ROOT / "server" / "static" / "assets").glob("*.js"))
    assert bundles
    js = "\n".join(p.read_text(encoding="utf-8") for p in bundles)
    assert "Đăng nhập private team" in js and "X-CSRF-Token" in js
    assert "forge:unauthorized" in js and "Google OpenID Connect" in js
    assert "Gmail scope" in js  # UI nói rõ KHÔNG xin scope, không claim Gmail đã xong


@check("T15 Credential/demo theo model · settings provider tách routing · battle trộn provider · cost/alias đúng provider")
async def t15():
    from fastapi.testclient import TestClient

    from engine import agent as agent_module
    from engine import config, cost
    from engine import secrets as secretstore
    from engine.models import ModelRouter, infer_capabilities
    from server import auth as aw
    from server import main as sm
    admin = aw.auth_store.list_users()[0]
    config.save_config({"provider": "openrouter", "model": "openrouter:vendor/code",
                        "release_mode": False, "model_roles": {},
                        "api_key": "fake-openrouter-old-key", "google_api_key": "fake-google-old-key"})
    with TestClient(sm.app) as client:
        login(client, admin)
        changed = client.post("/api/settings", json={"provider": "google",
                                                      "api_key": "fake-google-new-key"})
        assert changed.status_code == 200, changed.text
        assert config.get_provider() == "openrouter"
        assert config.get_api_key() == "fake-openrouter-old-key"
        assert config.get_google_api_key() == "fake-google-new-key"
        assert "fake-google-new-key" not in changed.text

        # Active OpenRouter không có key, nhưng Gemini direct có key → phải gọi real path.
        secretstore.PROVIDER_FILE.write_text(json.dumps({"google": "fake-google-new-key"}),
                                               encoding="utf-8")
        router = ModelRouter(sm.model_registry)
        parent_google = "google:gemini-3.8-flash"
        assert router.resolve_sub_model("cheap", parent_google) == parent_google
        assert router.resolve_sub_model("strong", parent_google) == parent_google
        assert router.resolve_sub_model("cheap", "openrouter:vendor/code") == "openrouter:openrouter/free"
        assert "vision" not in infer_capabilities("openrouter:anthropic/claude-static")

        original_send = sm.Agent.send
        original_demo = agent_module.send_demo
        async def fake_send(self, text, chat_mode="agent", content=None, append_user=True):
            marker = f"REAL:{self.model}"
            self.session.messages.extend([{"role": "user", "content": text},
                                          {"role": "assistant", "content": marker}])
            self.store.save(self.session)
            yield {"type": "assistant_message", "content": marker, "tool_calls": None}
            yield {"type": "turn_end", "usage": None, "message_count": len(self.session.messages)}

        async def fake_demo(agent, text):
            marker = f"DEMO:{agent.model}"
            agent.session.messages.extend([{"role": "user", "content": text},
                                           {"role": "assistant", "content": marker}])
            agent.store.save(agent.session)
            yield {"type": "assistant_message", "content": marker, "tool_calls": None}
            yield {"type": "turn_end", "usage": None, "message_count": len(agent.session.messages)}

        sm.Agent.send = fake_send
        agent_module.send_demo = fake_demo
        try:
            created = client.post("/api/sessions", json={"model": parent_google})
            sid = created.json()["session"]["id"]
            response = client.post(f"/api/sessions/{sid}/chat", json={"text": "route google"})
            assert response.status_code == 200, response.text
            assert f"REAL:{parent_google}" in response.text and "DEMO:" not in response.text

            before = {row["id"] for row in sm.store.list(admin.id)}
            battle = client.post("/api/battle", json={"prompt": "mixed providers",
                                                       "models": [parent_google, "openrouter:vendor/code"]})
            assert battle.status_code == 200, battle.text
            after = {row["id"]: row for row in sm.store.list(admin.id)}
            new_ids = set(after) - before
            assert len(new_ids) == 2
            markers = {}
            for new_sid in new_ids:
                session = sm.store.get(new_sid)
                assistant = [m.get("content", "") for m in session.messages if m.get("role") == "assistant"]
                markers[session.model] = assistant[-1]
            assert markers[parent_google].startswith("REAL:google:")
            assert markers["openrouter:vendor/code"].startswith("DEMO:openrouter:")
        finally:
            sm.Agent.send = original_send
            agent_module.send_demo = original_demo

    original_prices = cost._fetch_prices
    async def fake_prices():
        return {"vendor/code": (0.001, 0.002)}
    cost._fetch_prices = fake_prices
    try:
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        assert await cost.estimate("openrouter:vendor/code", usage) == 0.02
        assert await cost.estimate(parent_google, usage) is None
    finally:
        cost._fetch_prices = original_prices


@check("T16 Member không nạp MCP credential toàn server · global skill bị chặn · project skill vẫn quản lý được")
async def t16():
    from fastapi.testclient import TestClient

    from engine import agent as agent_module
    from engine import config, skillmgr
    from engine.agent import Agent
    from engine.session import ScopedSessionStore
    from server import auth as aw
    from server import main as sm
    member = aw.auth_store.create_user("member-mcp@forge.local", PASSWORD, "Member MCP", "member")
    scoped = ScopedSessionStore(sm.store, member.id, allow_mcp=False)
    session = scoped.create(model="openrouter:vendor/code", title="Member MCP")
    agent = Agent(scoped, session.id, router=sm.model_router)
    called = {"mcp": False}
    original_specs = agent_module.mcp_manager.get_tool_specs
    original_llm = Agent._llm_with_fallback
    async def forbidden_specs():
        called["mcp"] = True
        return [], {}
    async def fake_llm(self, messages, specs, model):
        yield {"type": "delta", "text": "member-ok"}
    agent_module.mcp_manager.get_tool_specs = forbidden_specs
    Agent._llm_with_fallback = fake_llm
    try:
        events = [event async for event in agent.send("hello", chat_mode="agent")]
        assert any(event.get("type") == "assistant_message" for event in events)
        assert called["mcp"] is False
    finally:
        agent_module.mcp_manager.get_tool_specs = original_specs
        Agent._llm_with_fallback = original_llm

    global_skill = config.DATA_DIR / "forge" / "skills" / "team-global" / "SKILL.md"
    global_skill.parent.mkdir(parents=True, exist_ok=True)
    global_skill.write_text("---\nname: team-global\ndescription: test only\n---\nGlobal\n",
                            encoding="utf-8")
    with TestClient(sm.app) as client:
        login(client, member)
        listing = client.get("/api/skills", params={"sid": session.id})
        assert listing.status_code == 200, listing.text
        global_row = next(row for row in listing.json()["skills"] if row["name"] == "team-global")
        denied = client.post(f"/api/skills/toggle?sid={session.id}",
                             json={"path": global_row["path"], "invocable": False})
        assert denied.status_code == 403, denied.text
        add_global = client.post(f"/api/sessions/{session.id}/chat",
                                 json={"text": "/skills add owner/repo"})
        assert add_global.status_code == 403, add_global.text
        made = skillmgr.new_skill(scoped.workspace(session.id), "member-project", "test")
        assert "✅" in made
        project_path = scoped.workspace(session.id) / ".forge" / "skills" / "member-project" / "SKILL.md"
        allowed = client.post(f"/api/skills/toggle?sid={session.id}",
                              json={"path": str(project_path), "invocable": False})
        assert allowed.status_code == 200, allowed.text
        assert "disable-model-invocation: true" in project_path.read_text(encoding="utf-8")


@check("T17 First-run launcher tự bootstrap admin khi có TTY · non-interactive thiếu user fail-closed")
async def t17():
    import contextlib
    import io
    import types

    from engine.auth import AuthStore
    from scripts import launch, setup_auth
    from server import auth as aw
    try:
        aw.auth_store.db_path.unlink()
    except FileNotFoundError:
        pass
    aw.auth_store = AuthStore()
    original = (sys.argv, sys.stdin, launch.setup_venv, launch.port_busy, launch.wait_port,
                launch.open_browser, launch.subprocess.Popen, setup_auth.getpass.getpass,
                getattr(setup_auth, "input", None))
    created = []
    class FakeProcess:
        def wait(self):
            return 0
        def terminate(self):
            return None
    try:
        launch.setup_venv = lambda: None
        launch.port_busy = lambda: False
        launch.wait_port = lambda timeout=40: True
        launch.open_browser = lambda: None
        launch.subprocess.Popen = lambda *args, **kwargs: created.append(args) or FakeProcess()
        setup_auth.input = lambda _prompt: "launcher-admin@forge.local"
        setup_auth.getpass.getpass = lambda _prompt: PASSWORD
        sys.stdin = types.SimpleNamespace(isatty=lambda: True)
        sys.argv = ["launch.py", "--no-browser"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = launch.main()
        assert rc == 0 and created
        users = AuthStore().list_users()
        assert len(users) == 1 and users[0].email == "launcher-admin@forge.local" and users[0].role == "admin"
        assert PASSWORD not in output.getvalue()

        AuthStore().db_path.unlink()
        sys.stdin = types.SimpleNamespace(isatty=lambda: False)
        created.clear()
        with contextlib.redirect_stdout(output):
            rc = launch.main()
        assert rc == 1 and not created and not AuthStore().has_users()
    finally:
        (sys.argv, sys.stdin, launch.setup_venv, launch.port_busy, launch.wait_port,
         launch.open_browser, launch.subprocess.Popen, setup_auth.getpass.getpass) = original[:8]
        if original[8] is None:
            del setup_auth.input
        else:
            setup_auth.input = original[8]


async def main():
    print(f"=== SUITE v0.34 Private multi-user + multi-provider — data tạm: {TMP} ===")
    for fn in (t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13, t14, t15, t16, t17):
        await fn()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name, err in FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
