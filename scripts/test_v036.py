"""Suite v0.36 — persistent provider keys/models + diagnosable chat failures.

Không dùng credential thật và không gọi provider/Google. Provider 501 được mock.
Chạy: python scripts/test_v036.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="forge-v036-"))
os.environ["FORGE_DATA_DIR"] = str(TMP / "data")
for name in ("OPENROUTER_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "FORGE_CUSTOM_API_KEY",
             "FORGE_PROVIDER", "FORGE_MODEL", "FORGE_RELEASE_MODE", "FORGE_PUBLIC_URL",
             "FORGE_GOOGLE_CLIENT_ID", "FORGE_GOOGLE_CLIENT_SECRET", "FORGE_COOKIE_SECURE",
             "FORGE_ALLOW_REGISTRATION"):
    os.environ.pop(name, None)

PASSWORD = "v036-fake-password-not-a-real-secret"
OR_KEY = "sk-or-v1-FAKE-V036-not-real"
GOOGLE_KEY = "AIza-FAKE-V036-not-real"
CUSTOM_KEY = "custom-FAKE-V036-not-real"
PASS, FAIL = [], []


def check(name):
    def deco(fn):
        async def run():
            try:
                await fn()
                PASS.append(name)
                print(f"  ✓ {name}", flush=True)
            except Exception as exc:  # noqa: BLE001 — test harness gom đủ lỗi
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


def create_session(client, model: str = "openrouter:openrouter/free") -> str:
    response = client.post("/api/sessions", json={"model": model})
    assert response.status_code == 200, response.text
    return response.json()["session"]["id"]


@check("T1 Lưu tuần tự 3 provider key · reload secret store · blank Save không xoá · không rò secret")
async def t1():
    from fastapi.testclient import TestClient

    from engine import config
    from server.main import app
    admin = make_user("v036-keys-admin", "admin")
    with TestClient(app) as client:
        login(client, admin)
        responses = [
            client.post("/api/settings", json={"provider": "openrouter", "api_key": OR_KEY,
                                                "model": "openrouter:openrouter/free"}),
            client.post("/api/settings", json={"provider": "google", "api_key": GOOGLE_KEY}),
            client.post("/api/settings", json={"provider": "custom", "api_key": CUSTOM_KEY,
                                                "custom_base_url": "http://127.0.0.1:9/v1"}),
        ]
        assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
        assert config.get_api_key() == OR_KEY
        assert config.get_google_api_key() == GOOGLE_KEY
        assert config.get_custom_api_key() == CUSTOM_KEY
        payload = client.get("/api/settings")
        assert payload.status_code == 200
        assert payload.json()["provider_keys"] == {"openrouter": True, "google": True, "custom": True}
        # Save các setting khác với key để trống phải giữ nguyên cả 3 credential.
        unchanged = client.post("/api/settings", json={"provider": "google", "api_key": "",
                                                        "max_tokens": 4096})
        assert unchanged.status_code == 200, unchanged.text
        assert config.get_google_api_key() == GOOGLE_KEY
        combined = "\n".join(r.text for r in [*responses, payload, unchanged])
        combined += config.CONFIG_FILE.read_text(encoding="utf-8")
        for secret in (OR_KEY, GOOGLE_KEY, CUSTOM_KEY, PASSWORD):
            assert secret not in combined


@check("T2 Model session lưu ngay trước prompt/reload · CSRF · invalid không ghi đè · default độc lập")
async def t2():
    from fastapi.testclient import TestClient

    from engine import config
    from server.main import app, model_router
    admin = make_user("v036-model-admin", "admin")
    with TestClient(app) as client:
        login(client, admin)
        sid = create_session(client)
        default_before = model_router.default_model()
        token = client.headers["X-CSRF-Token"]
        client.headers.pop("X-CSRF-Token")
        assert client.patch(f"/api/sessions/{sid}/model", json={"model": "google:gemini-3.8-flash"}).status_code == 403
        client.headers["X-CSRF-Token"] = token
        changed = client.patch(f"/api/sessions/{sid}/model", json={"model": "google:gemini-3.8-flash"})
        assert changed.status_code == 200, changed.text
        assert changed.json()["model"] == "google:gemini-3.8-flash"
        assert client.get(f"/api/sessions/{sid}").json()["session"]["model"] == "google:gemini-3.8-flash"
        # Store mới đọc lại từ disk, không dùng object cache.
        from engine.session import SessionStore
        assert SessionStore().get(sid).model == "google:gemini-3.8-flash"
        assert model_router.default_model() == default_before
        bad = client.patch(f"/api/sessions/{sid}/model", json={"model": "openrouter:"})
        assert bad.status_code == 400, bad.text
        assert SessionStore().get(sid).model == "google:gemini-3.8-flash"
        assert config.get_model() != "google:gemini-3.8-flash"


@check("T3 Model endpoint giữ owner ACL · member đổi phiên mình nhưng không đổi Settings/phiên admin")
async def t3():
    from fastapi.testclient import TestClient

    from server.main import app
    admin = make_user("v036-acl-admin", "admin")
    member = make_user("v036-acl-member")
    with TestClient(app) as a, TestClient(app) as m:
        login(a, admin)
        login(m, member)
        admin_sid = create_session(a)
        member_sid = create_session(m)
        assert m.patch(f"/api/sessions/{admin_sid}/model",
                       json={"model": "google:gemini-3.8-flash"}).status_code == 404
        own = m.patch(f"/api/sessions/{member_sid}/model", json={"model": "google:gemini-3.8-flash"})
        assert own.status_code == 200, own.text
        assert a.get(f"/api/sessions/{member_sid}").status_code == 404
        assert m.post("/api/settings", json={"model": "openrouter:openrouter/free"}).status_code == 403


@check("T4 Web-shaped chat không capability trả SSE 200 · chỉ image-generation contract trả 501 JSON")
async def t4():
    from fastapi.testclient import TestClient

    import server.main as sm
    admin = make_user("v036-chat-admin", "admin")
    original = sm.Agent.send

    async def fake_send(self, text, chat_mode="agent", content=None, append_user=True):
        yield {"type": "assistant_message", "content": f"OK:{self.model}", "tool_calls": None}
        yield {"type": "done"}

    sm.Agent.send = fake_send
    try:
        with TestClient(sm.app) as client:
            login(client, admin)
            sid = create_session(client)
            # Đúng shape web/src/api.ts: không gửi capability.
            response = client.post(f"/api/sessions/{sid}/chat", json={
                "text": "tiếp tục công việc", "mode": "agent",
                "model": "openrouter:openrouter/free", "images": [], "rerun": False,
            })
            assert response.status_code == 200, response.text
            assert "OK:openrouter:openrouter/free" in response.text
            synthetic = client.post(f"/api/sessions/{sid}/chat", json={"text": "/audit"})
            assert synthetic.status_code == 200 and '"type": "done"' in synthetic.text, synthetic.text
            image = client.post(f"/api/sessions/{sid}/chat",
                                json={"text": "make image", "capability": "image_generation"})
            assert image.status_code == 501 and image.json()["detail"], image.text
    finally:
        sm.Agent.send = original


@check("T5 Provider 501 được mock · lỗi actionable cho tools/streaming · secret bị redact")
async def t5():
    from engine import llm
    calls = []

    class FakeResponse:
        status_code = 501
        async def aread(self):
            return f"tools are not implemented; echoed={OR_KEY}".encode()

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
            calls.append((url, headers, json))
            return FakeStream()

    original = llm.httpx.AsyncClient
    llm.httpx.AsyncClient = FakeClient
    try:
        try:
            _ = [event async for event in llm.stream_chat(
                [{"role": "user", "content": "continue"}], tools=[{"type": "function"}],
                model="openrouter:vendor/code-model")]
            raise AssertionError("Provider 501 không raise LLMError")
        except llm.LLMError as exc:
            message = str(exc)
            assert "HTTP 501" in message and "không hỗ trợ" in message.lower(), message
            assert "tool" in message.lower() and "direct" in message.lower(), message
            assert OR_KEY not in message
    finally:
        llm.httpx.AsyncClient = original
    assert calls and calls[0][2]["tools"] == [{"type": "function"}]


@check("T6 Lỗi provider trong lượt agent là SSE error + done · không phải pre-stream HTTP 501")
async def t6():
    from fastapi.testclient import TestClient

    import server.main as sm
    from engine import llm
    admin = make_user("v036-sse-admin", "admin")
    original = sm.Agent.send

    async def fail_send(self, text, chat_mode="agent", content=None, append_user=True):
        raise llm.LLMError("OpenRouter HTTP 501: mocked provider failure")
        yield {}  # pragma: no cover — biến function thành async generator

    sm.Agent.send = fail_send
    try:
        with TestClient(sm.app) as client:
            login(client, admin)
            sid = create_session(client)
            response = client.post(f"/api/sessions/{sid}/chat", json={"text": "continue"})
            assert response.status_code == 200, response.text
            assert '"type": "error"' in response.text and "OpenRouter HTTP 501" in response.text
            assert '"type": "done"' in response.text
    finally:
        sm.Agent.send = original


@check("T7 Ba provider đã lưu route đồng thờI đúng URL/model/key · không mutate global provider")
async def t7():
    from engine import config, llm
    provider_before = config.get_provider()
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
            return [event async for event in llm.stream_chat(
                [{"role": "user", "content": "x"}], model=model)]
        await asyncio.gather(collect("openrouter:vendor/code-model"),
                             collect("google:gemini-3.8-flash"),
                             collect("custom:local-code"))
    finally:
        llm.httpx.AsyncClient = original
    assert len(calls) == 3
    by_url = {row["url"]: row for row in calls}
    assert by_url[llm.OPENROUTER_URL]["json"]["model"] == "vendor/code-model"
    assert by_url[llm.GOOGLE_OPENAI_URL]["json"]["model"] == "gemini-3.8-flash"
    assert by_url["http://127.0.0.1:9/v1/chat/completions"]["json"]["model"] == "local-code"
    assert by_url[llm.OPENROUTER_URL]["headers"]["Authorization"] == f"Bearer {OR_KEY}"
    assert by_url[llm.GOOGLE_OPENAI_URL]["headers"]["Authorization"] == f"Bearer {GOOGLE_KEY}"
    assert by_url["http://127.0.0.1:9/v1/chat/completions"]["headers"]["Authorization"] == f"Bearer {CUSTOM_KEY}"
    assert config.get_provider() == provider_before


@check("T8 Production bundle có trạng thái từng provider · lưu model · lỗi SSE/HTTP không còn ẩn")
async def t8():
    bundles = list((ROOT / "server" / "static" / "assets").glob("*.js"))
    assert bundles
    js = "\n".join(path.read_text(encoding="utf-8") for path in bundles)
    for marker in ("Trạng thái API key các provider", "forge-key-provider",
                   "Server không trả nội dung lỗi", "kết thúc trước", "/model"):
        assert marker in js, marker
    for secret in (OR_KEY, GOOGLE_KEY, CUSTOM_KEY, PASSWORD):
        assert secret not in js


async def main():
    print(f"=== SUITE v0.36 Provider key/model persistence + error diagnostics — data tạm: {TMP} ===")
    for test in (t1, t2, t3, t4, t5, t6, t7, t8):
        await test()
    print(f"\nKẾT QUẢ: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
