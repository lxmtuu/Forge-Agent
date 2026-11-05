"""Compatibility fixture cho suite ≤v0.33 — KHÔNG phải product auth bypass.

Các test cũ kiểm tra tính năng với giả định local shared store. Fixture nâng chúng lên
một admin thật (session cookie + CSRF) và gán legacy owner="" cho admin của test.
Suite v0.34 dùng TestClient gốc để kiểm tra auth/ACL âm, không cài fixture này.
"""
from __future__ import annotations

import fastapi.testclient

_ORIGINAL = fastapi.testclient.TestClient
EMAIL = "legacy-test-admin@forge.local"


def install() -> None:
    if getattr(fastapi.testclient.TestClient, "_forge_legacy_auth", False):
        return

    class LegacyAuthTestClient(_ORIGINAL):
        _forge_legacy_auth = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            from engine.auth import SESSION_COOKIE
            from server.auth import auth_store
            user = auth_store.get_by_email(EMAIL)
            if user is None:
                user = auth_store.create_user(EMAIL, name="Legacy test admin", role="admin")
            self._forge_user_id = user.id
            self.cookies.set(SESSION_COOKIE, auth_store.create_session(user.id))
            response = super().get("/api/auth/me")
            assert response.status_code == 200, response.text
            self.headers["X-CSRF-Token"] = response.json()["csrf_token"]

        def _migrate_legacy(self) -> None:
            # Chỉ chạy trong data dir tạm của test; không đổi session đã có owner khác.
            from engine import approvals, elicitations
            from server.main import store
            for row in store.list():
                session = store.get(row["id"])
                if session and not session.owner_id:
                    session.owner_id = self._forge_user_id
                    store.save(session)
            for entry in approvals.PENDING.values():
                if not entry.get("owner_id"):
                    entry["owner_id"] = self._forge_user_id
            for entry in elicitations.PENDING.values():
                if not entry.get("owner_id"):
                    entry["owner_id"] = self._forge_user_id

        def request(self, method, url, **kwargs):
            self._migrate_legacy()
            return super().request(method, url, **kwargs)

    fastapi.testclient.TestClient = LegacyAuthTestClient
