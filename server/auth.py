"""HTTP auth routes/dependencies cho account, team và public signup opt-in."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from engine import google_auth
from engine.auth import (
    CSRF_COOKIE,
    OAUTH_COOKIE,
    OAUTH_TTL,
    SESSION_COOKIE,
    SESSION_TTL,
    AuthStore,
    User,
    csrf_valid,
)
from engine.auth import secure_cookies as _secure_cookies_from_env

router = APIRouter(prefix="/api/auth", tags=["auth"])
auth_store = AuthStore()


def secure_cookies() -> bool:
    cfg = auth_store.google_config() or {}
    return _secure_cookies_from_env() or cfg.get("public_url", "").startswith("https://")


_LOGIN_RATE: dict[str, list[float]] = {}
_REGISTER_IP_RATE: dict[str, list[float]] = {}
_REGISTER_EMAIL_RATE: dict[str, list[float]] = {}
_REGISTER_WINDOW = 15 * 60.0
_REGISTER_IP_LIMIT = 5
_REGISTER_EMAIL_LIMIT = 3


class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=512)


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(max_length=512)
    name: str = Field(default="", max_length=120)


class RegistrationConfigBody(BaseModel):
    enabled: bool


class InviteBody(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(default="", max_length=120)
    password: str | None = Field(default=None, max_length=512)
    role: str = "member"
    enabled: bool = True


class EnabledBody(BaseModel):
    enabled: bool


class PasswordBody(BaseModel):
    current_password: str = Field(default="", max_length=512)
    new_password: str = Field(max_length=512)


class GoogleConfigBody(BaseModel):
    client_id: str = Field(max_length=300)
    client_secret: str = Field(default="", max_length=500)
    public_url: str = Field(max_length=500)


def optional_user(request: Request) -> User | None:
    cached = getattr(request.state, "forge_user", None)
    if cached is not None:
        return cached
    token = request.cookies.get(SESSION_COOKIE, "")
    user = auth_store.user_for_session(token) if token else None
    request.state.forge_user = user
    return user


def require_user(request: Request) -> User:
    user = optional_user(request)
    if user is None or not user.enabled:
        raise HTTPException(401, "Cần đăng nhập", headers={"Cache-Control": "no-store"})
    return user


def require_admin(user: User = Depends(require_user)) -> User:  # noqa: B008 — FastAPI DI
    if user.role != "admin":
        raise HTTPException(403, "Cần quyền admin")
    return user


def check_csrf(request: Request) -> None:
    if not csrf_valid(request.headers.get("x-csrf-token"), request.cookies.get(CSRF_COOKIE),
                      request.headers.get("sec-fetch-site")):
        raise HTTPException(403, "CSRF token không hợp lệ")


def issue_csrf(request: Request, response: Response, force: bool = False) -> str:
    old = request.cookies.get(CSRF_COOKIE, "")
    token = "" if force else old
    if not token or len(token) > 256:
        token = secrets.token_urlsafe(32)
    response.set_cookie(CSRF_COOKIE, token, max_age=SESSION_TTL, httponly=False,
                        secure=secure_cookies(), samesite="lax", path="/")
    return token


def set_session(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, httponly=True,
                        secure=secure_cookies(), samesite="lax", path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure_cookies(), samesite="lax")


def _rate_key(request: Request, email: str) -> str:
    host = request.client.host if request.client else "unknown"
    digest = hashlib.sha256(email.strip().casefold().encode("utf-8")).hexdigest()[:16]
    return f"{host}|{digest}"


def _login_throttled(key: str) -> bool:
    now = time.monotonic()
    rows = _LOGIN_RATE.setdefault(key, [])
    rows[:] = [t for t in rows if t > now - 60]
    if len(rows) >= 8:
        return True
    rows.append(now)
    if len(_LOGIN_RATE) > 1000:
        for k in list(_LOGIN_RATE):
            if not _LOGIN_RATE[k] or _LOGIN_RATE[k][-1] <= now - 60:
                _LOGIN_RATE.pop(k, None)
    return False


def _sliding_retry(bucket: dict[str, list[float]], key: str, limit: int) -> int:
    """In-process abuse control for one VPS; use gateway quota when scaling out."""
    now = time.monotonic()
    cutoff = now - _REGISTER_WINDOW
    rows = bucket.setdefault(key, [])
    rows[:] = [t for t in rows if t > cutoff]
    if len(rows) >= limit:
        return max(1, int(rows[0] + _REGISTER_WINDOW - now) + 1)
    rows.append(now)
    if len(bucket) > 1000:
        for old_key in list(bucket):
            if not bucket[old_key] or bucket[old_key][-1] <= cutoff:
                bucket.pop(old_key, None)
    return 0


def _registration_retry(request: Request, email: str) -> int:
    host = request.client.host if request.client else "unknown"
    digest = hashlib.sha256(email.strip().casefold().encode("utf-8")).hexdigest()[:16]
    # Evaluate both buckets so one dimension cannot be used to bypass the other.
    ip_retry = _sliding_retry(_REGISTER_IP_RATE, host, _REGISTER_IP_LIMIT)
    email_retry = _sliding_retry(_REGISTER_EMAIL_RATE, digest, _REGISTER_EMAIL_LIMIT)
    return max(ip_retry, email_retry)


@router.get("/me")
async def me(request: Request, response: Response) -> dict[str, Any]:
    user = optional_user(request)
    has_users = auth_store.has_users()
    return {"user": user.public() if user and user.enabled else None,
            "csrf_token": issue_csrf(request, response),
            "google_enabled": auth_store.google_config() is not None,
            "registration_enabled": has_users and auth_store.registration_enabled(),
            "needs_setup": not has_users}


@router.post("/register", status_code=201)
async def register(request: Request, response: Response, body: RegisterBody) -> dict[str, Any]:
    check_csrf(request)
    if not auth_store.has_users():
        raise HTTPException(503, "Cần bootstrap admin trước khi mở đăng ký")
    if not auth_store.registration_enabled():
        raise HTTPException(403, "Tự đăng ký đang tắt — liên hệ admin")
    retry = _registration_retry(request, body.email)
    if retry:
        raise HTTPException(429, "Quá nhiều lượt đăng ký — thử lại sau",
                            headers={"Retry-After": str(retry)})
    try:
        # Never accept role/enabled from the public payload.
        user = auth_store.create_user(body.email, body.password, body.name, role="member")
    except ValueError as exc:
        status = 409 if str(exc) == "Email đã tồn tại" else 400
        raise HTTPException(status, str(exc)) from exc
    old = request.cookies.get(SESSION_COOKIE, "")
    if old:
        auth_store.revoke_session(old)
    set_session(response, auth_store.create_session(user.id))
    return {"user": user.public(), "csrf_token": issue_csrf(request, response, force=True)}


@router.post("/login")
async def login(request: Request, response: Response, body: LoginBody) -> dict[str, Any]:
    check_csrf(request)
    key = _rate_key(request, body.email)
    if _login_throttled(key):
        raise HTTPException(429, "Quá nhiều lần đăng nhập — thử lại sau",
                            headers={"Retry-After": "60"})
    user = auth_store.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(401, "Email hoặc mật khẩu không đúng")
    _LOGIN_RATE.pop(key, None)
    old = request.cookies.get(SESSION_COOKIE, "")
    if old:
        auth_store.revoke_session(old)
    token = auth_store.create_session(user.id)
    set_session(response, token)
    return {"user": user.public(), "csrf_token": issue_csrf(request, response, force=True)}


@router.post("/logout")
async def logout(request: Request, response: Response) -> Response:
    check_csrf(request)
    auth_store.revoke_session(request.cookies.get(SESSION_COOKIE, ""))
    clear_session(response)
    response.status_code = 204
    return response


@router.get("/google/start")
async def google_start() -> Response:
    cfg = auth_store.google_config()
    if cfg is None:
        raise HTTPException(503, "Google login chưa được cấu hình")
    flow = auth_store.create_oauth_flow()
    redirect_uri = cfg["public_url"] + "/api/auth/google/callback"
    url = google_auth.authorization_url(cfg["client_id"], redirect_uri, flow["state"],
                                        flow["verifier"], flow["nonce"])
    redirect = RedirectResponse(url, status_code=302)
    redirect.set_cookie(OAUTH_COOKIE, flow["state"], max_age=OAUTH_TTL, httponly=True,
                        secure=secure_cookies(), samesite="lax", path="/api/auth/google")
    return redirect


@router.get("/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
    def fail(reason: str) -> RedirectResponse:
        result = RedirectResponse(f"/?login=1&error={reason}", status_code=303)
        result.delete_cookie(OAUTH_COOKIE, path="/api/auth/google")
        return result

    if error:
        return fail("google_denied")
    cookie_state = request.cookies.get(OAUTH_COOKIE, "")
    if not code or not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
        return fail("google_state")
    flow = auth_store.consume_oauth_flow(state)
    if flow is None:
        return fail("google_replay")
    cfg = auth_store.google_config()
    if cfg is None:
        return fail("google_config")
    redirect_uri = cfg["public_url"] + "/api/auth/google/callback"
    try:
        token = await google_auth.exchange_code(cfg["client_id"], cfg["client_secret"],
                                                redirect_uri, code, flow["verifier"])
        identity = await google_auth.verify_id_token(str(token["id_token"]), cfg["client_id"],
                                                      flow["nonce"])
        user = auth_store.user_by_google(identity["sub"])
        if user is None:
            # Email verified chỉ link vào tài khoản đã được admin mời; không public signup.
            user = auth_store.get_by_email(identity["email"])
        if user is None and not auth_store.has_users():
            user = auth_store.create_user(identity["email"], name=identity["name"], role="admin")
        if user is None and auth_store.registration_enabled():
            # Google đã xác minh email; public signup chỉ tạo member sau bootstrap.
            user = auth_store.create_user(identity["email"], name=identity["name"], role="member")
        if user is None:
            return fail("not_invited")
        if not user.enabled:
            return fail("disabled")
        # Nếu account đã link subject khác, link_google từ chối cả trường hợp cùng email.
        auth_store.link_google(user.id, identity["sub"], identity["email"])
        auth_store.update_profile(user.id, identity["name"] or user.name, identity["picture"])
    except (google_auth.GoogleAuthError, ValueError):
        return fail("google_invalid")
    old = request.cookies.get(SESSION_COOKIE, "")
    if old:
        auth_store.revoke_session(old)
    session_token = auth_store.create_session(user.id)
    result = RedirectResponse("/", status_code=303)
    set_session(result, session_token)
    result.delete_cookie(OAUTH_COOKIE, path="/api/auth/google")
    issue_csrf(request, result, force=True)
    return result


@router.get("/users")
async def users(_: User = Depends(require_admin)) -> list[dict[str, Any]]:  # noqa: B008
    return [u.public() for u in auth_store.list_users()]


@router.post("/users")
async def invite(body: InviteBody, admin: User = Depends(require_admin)) -> dict[str, Any]:  # noqa: B008
    try:
        user = auth_store.create_user(body.email, body.password, body.name, body.role, body.enabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return user.public()


@router.patch("/users/{user_id}")
async def set_user_enabled(user_id: str, body: EnabledBody,
                           admin: User = Depends(require_admin)) -> dict[str, Any]:  # noqa: B008
    target = auth_store.get(user_id)
    if target is None:
        raise HTTPException(404, "User không tồn tại")
    if target.id == admin.id and not body.enabled:
        raise HTTPException(400, "Không thể tự vô hiệu hoá tài khoản đang dùng")
    if target.role == "admin" and not body.enabled:
        admins = [u for u in auth_store.list_users() if u.role == "admin" and u.enabled]
        if len(admins) <= 1:
            raise HTTPException(400, "Phải giữ ít nhất một admin đang hoạt động")
    auth_store.set_enabled(user_id, body.enabled)
    updated = auth_store.get(user_id)
    assert updated is not None
    return updated.public()


@router.post("/password")
async def change_password(request: Request, response: Response, body: PasswordBody,
                          user: User = Depends(require_user)) -> dict[str, Any]:  # noqa: B008
    current = auth_store.authenticate(user.email, body.current_password)
    if user.password_set and current is None:
        raise HTTPException(401, "Mật khẩu hiện tại không đúng")
    try:
        auth_store.set_password(user.id, body.new_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    auth_store.revoke_user_sessions(user.id)
    set_session(response, auth_store.create_session(user.id))
    updated = auth_store.get(user.id)
    assert updated is not None
    return {"user": updated.public(), "csrf_token": issue_csrf(request, response, force=True)}


@router.get("/registration/config")
async def get_registration_config(_: User = Depends(require_admin)) -> dict[str, bool]:  # noqa: B008
    return {"enabled": auth_store.registration_enabled()}


@router.put("/registration/config")
async def put_registration_config(body: RegistrationConfigBody,
                                  _: User = Depends(require_admin)) -> dict[str, bool]:  # noqa: B008
    auth_store.set_registration_enabled(body.enabled)
    return {"enabled": body.enabled}


@router.get("/google/config")
async def get_google_config(_: User = Depends(require_admin)) -> dict[str, Any]:  # noqa: B008
    cfg = auth_store.google_config()
    return {"configured": cfg is not None, "client_id": cfg["client_id"] if cfg else "",
            "public_url": cfg["public_url"] if cfg else "", "client_secret_set": bool(cfg)}


@router.put("/google/config")
async def put_google_config(body: GoogleConfigBody,
                            _: User = Depends(require_admin)) -> dict[str, Any]:  # noqa: B008
    old = auth_store.google_config() or {}
    secret = body.client_secret or old.get("client_secret", "")
    try:
        auth_store.save_google_config(body.client_id, secret, body.public_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"configured": True, "client_id": body.client_id,
            "public_url": body.public_url.rstrip("/"), "client_secret_set": True}
