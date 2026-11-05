"""Forge Agent — FastAPI server: SSE agent streaming, sessions, workspace files, static web UI.

Run:  uvicorn server.main:app --host 0.0.0.0 --port 8000
"""
# ruff: noqa: B008 — FastAPI Depends trong default là DI idiom của toàn bộ routes.
import asyncio
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import config, guard, llm, tools
from engine.agent import Agent, run_batch, run_battle, send_demo
from engine.auth import CSRF_COOKIE, User, csrf_valid
from engine.mcp import load_servers, save_servers
from engine.mcp import manager as mcp_manager
from engine.models import CAPABILITIES, ModelCapabilityError
from engine.models import registry as model_registry
from engine.models import router as model_router
from engine.session import ScopedSessionStore, SessionStore
from server import auth as auth_web
from server.auth import require_admin, require_user

app = FastAPI(title="Forge Agent", version="0.35.0")
app.include_router(auth_web.router)
# Development giữ CORS mở cho tooling; release mặc định same-origin. Muốn mở
# cross-origin phải liệt kê rõ FORGE_CORS_ORIGINS=https://app.example,...
_cors = [x.strip() for x in os.environ.get("FORGE_CORS_ORIGINS", "").split(",") if x.strip()]
if config.is_release_mode() and "*" in _cors:
    raise RuntimeError("FORGE_CORS_ORIGINS không được chứa '*' ở release mode")
if _cors or not config.is_release_mode():
    app.add_middleware(
        CORSMiddleware, allow_origins=_cors or ["*"], allow_methods=["*"], allow_headers=["*"],
        allow_credentials=bool(_cors),
    )
store = SessionStore()


def _db(user: User) -> ScopedSessionStore:
    return ScopedSessionStore(store, user.id, allow_mcp=user.role == "admin")

STATIC_DIR = ROOT / "server" / "static"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ChatBody(BaseModel):
    text: str
    model: str | None = None
    mode: str = "agent"  # direct | agent | plan | architect
    capability: str = "code"  # code | reasoning | vision | design | tools
    images: list[str] = []  # data URI image/png|jpeg|webp|gif (tối đa 4)
    rerun: bool = False  # true: chạy lại từ tin user đã sửa (qua /rerun) — không append tin mới


class BattleBody(BaseModel):
    prompt: str
    models: list[str] = []


class ExecBody(BaseModel):
    command: str


class OpenWorkspaceBody(BaseModel):
    path: str


class SettingsBody(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    approval_mode: str | None = None
    docker_sandbox: bool | None = None
    max_tokens: int | None = None
    web_search: bool | None = None
    allow_commands: list[str] | None = None
    deny_commands: list[str] | None = None
    custom_base_url: str | None = None
    custom_api_key: str | None = None
    auto_commit: bool | None = None
    reasoning_effort: str | None = None


class FileSaveBody(BaseModel):
    path: str
    content: str


class McpServerBody(BaseModel):
    name: str
    command: str
    args: list[str] = []


class BatchBody(BaseModel):
    prompts: list[str]
    model: str | None = None


class ApprovalBody(BaseModel):
    decision: str  # "approve" | "approve_always" | "deny"


def sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


_MODELS_CACHE: dict[str, Any] = {"ts": 0.0, "data": []}
_LLM_RATE: dict[str, list[float]] = {}


def _rate_retry(identity: str, limit: int,
                bucket: dict[str, list[float]] | None = None) -> int:
    """Sliding window 60s theo user; in-process cho deployment một VPS."""
    now = time.monotonic()
    rates = _LLM_RATE if bucket is None else bucket
    rows = rates.setdefault(identity, [])
    cutoff = now - 60.0
    rows[:] = [t for t in rows if t > cutoff]
    if len(rows) >= limit:
        return max(1, int(60.0 - (now - rows[0])) + 1)
    rows.append(now)
    if len(rates) > 1000:
        for key in list(rates):
            if not rates[key] or rates[key][-1] <= cutoff:
                rates.pop(key, None)
    return 0


def _security_error(status: int, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer", **(headers or {})})


@app.middleware("http")
async def release_security(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        user = auth_web.optional_user(request)
        if (request.method in {"POST", "PUT", "PATCH", "DELETE"}
                and not csrf_valid(request.headers.get("x-csrf-token"),
                                   request.cookies.get(CSRF_COOKIE),
                                   request.headers.get("sec-fetch-site"))):
            return _security_error(403, "CSRF token không hợp lệ")
        public = path == "/api/health" or path.startswith("/api/auth/")
        if not public and user is None and request.method != "OPTIONS":
            return _security_error(401, "Cần đăng nhập")
        expensive = (
            path in {"/api/battle", "/api/batch"}
            or (path.startswith("/api/sessions/")
                and path.rsplit("/", 1)[-1] in {"chat", "compact", "init", "loop"})
        )
        if user and request.method == "POST" and expensive:
            host = request.client.host if request.client else "unknown"
            retry = _rate_retry(f"{user.id}|{host}", config.get_rate_limit_per_min())
            if retry:
                return _security_error(429, "Quá nhiều request LLM — thử lại sau",
                                       {"Retry-After": str(retry)})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Health / settings
# ---------------------------------------------------------------------------
def _pkg_version() -> str:
    """Đọc version pyproject 1 LẦN lúc import (không I/O trong request handler)."""
    try:
        import tomllib
        return tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]["version"]
    except Exception:  # noqa: BLE001 — thiếu version không được làm chết health
        return "?"


APP_VERSION = _pkg_version()


@app.get("/api/health")
async def health():
    """Public liveness: không trả model/key/settings hay dữ liệu user."""
    return {"ok": True, "version": APP_VERSION, "demo": not config.has_any_llm_credentials(),
            "release_mode": config.is_release_mode(), "multi_user": True,
            "auth": "google_or_email"}


async def _settings_payload():
    provider = config.get_provider()
    key = config.get_active_api_key()
    cfg = config.load_config()
    release = config.is_release_mode()
    return {
        "ok": True,
        "version": APP_VERSION,
        "demo": not config.has_any_llm_credentials(),
        "provider": provider,
        "release_mode": release,
        "settings_locked": release,
        "web_key_input": not release,
        "model": model_router.default_model(),
        "key_masked": "••••••••" if key else "",
        "provider_keys": {"openrouter": bool(config.get_api_key()),
                          "google": bool(config.get_google_api_key()),
                          "custom": bool(config.get_custom_api_key())},
        "default_models": [spec.id for spec in model_registry.list()],
        "approval_mode": cfg.get("approval_mode", "guarded"),
        "docker_sandbox": bool(cfg.get("docker_sandbox")),
        "docker_available": guard.DOCKER_AVAILABLE,
        "max_tokens": config.get_max_tokens(),
        "web_search": bool(cfg.get("web_search")),
        "allow_commands": cfg.get("allow_commands") or [],
        "deny_commands": cfg.get("deny_commands") or [],
        "active_profile": cfg.get("active_profile"),
        "profiles": sorted(config.list_profiles().keys()),
        "custom_base_url": config.get_base_url(),
        "auto_commit": config.get_auto_commit(),
        "reasoning_effort": config.get_reasoning_effort(),
        "lsp_available": _lsp_available(),
    }


def _lsp_available() -> dict:
    """Ngôn ngữ nào có language server trên PATH (để UI hiển thị trạng thái)."""
    import shutil
    return {
        "python": shutil.which("pylsp") is not None or shutil.which("pyright-langserver") is not None,
        "typescript": shutil.which("typescript-language-server") is not None,
    }


@app.get("/api/settings")
async def get_settings(user: User = Depends(require_user)):
    payload = await _settings_payload()
    if user.role != "admin":
        payload.update({"settings_locked": True, "web_key_input": False,
                        "key_masked": "", "custom_base_url": ""})
        payload.pop("provider_keys", None)
    return payload


class KeyCheckBody(BaseModel):
    provider: str = "openrouter"
    api_key: str | None = None


@app.post("/api/keycheck")
async def keycheck(body: KeyCheckBody | None = None, user: User = Depends(require_admin)):
    """Verify key theo provider; release khóa endpoint để Settings chỉ qua terminal."""
    if config.is_release_mode():
        raise HTTPException(403, "Release mode: key chỉ được quản lý qua terminal")
    provider = (body.provider if body else "openrouter").strip().lower()
    if provider not in ("openrouter", "google"):
        raise HTTPException(400, "Key check hỗ trợ openrouter hoặc google")
    provided = body.api_key.strip() if (body and body.api_key) else None
    return await llm.check_key(provided, provider=provider)


@app.post("/api/settings")
async def set_settings(body: SettingsBody, user: User = Depends(require_admin)):
    if config.is_release_mode():
        raise HTTPException(403, "Release mode: Settings bị khóa — cấu hình qua scripts/setup_keys.py")
    patch: dict = {}
    if body.api_key is not None and body.api_key.strip():
        # Provider của key độc lập với default routing; không ghi nhầm vào active provider.
        key_provider = (body.provider or config.get_provider()).strip().lower()
        key_fields = {"openrouter": "api_key", "google": "google_api_key",
                      "custom": "custom_api_key"}
        if key_provider not in key_fields:
            raise HTTPException(400, "Provider của API key không hợp lệ")
        patch[key_fields[key_provider]] = body.api_key.strip()
    if body.model is not None and body.model.strip():
        try:
            patch["model"] = model_registry.route("code", body.model).id
        except (ValueError, ModelCapabilityError) as exc:
            raise HTTPException(400, str(exc)) from exc
    if body.approval_mode is not None and body.approval_mode in ("guarded", "ask", "auto"):
        patch["approval_mode"] = body.approval_mode
    if body.docker_sandbox is not None:
        patch["docker_sandbox"] = body.docker_sandbox
    if body.max_tokens is not None and 256 <= int(body.max_tokens) <= 65536:
        patch["max_tokens"] = int(body.max_tokens)
    if body.web_search is not None:
        patch["web_search"] = bool(body.web_search)
    if body.allow_commands is not None:
        patch["allow_commands"] = [x.strip() for x in body.allow_commands if x.strip()][:50]
    if body.deny_commands is not None:
        patch["deny_commands"] = [x.strip() for x in body.deny_commands if x.strip()][:50]
    if body.custom_base_url is not None:  # chuỗi rỗng = quay lại OpenRouter
        patch["custom_base_url"] = body.custom_base_url.strip().rstrip("/")
    if body.custom_api_key is not None and body.custom_api_key.strip():
        patch["custom_api_key"] = body.custom_api_key.strip()
    if body.auto_commit is not None:
        patch["auto_commit"] = bool(body.auto_commit)
    if body.reasoning_effort is not None:  # sai giá trị → về mặc định (không gửi)
        e = body.reasoning_effort.strip().lower()
        patch["reasoning_effort"] = e if e in ("low", "medium", "high") else ""
    config.save_config(patch)
    return await _settings_payload()


# ---------------------------------------------------------------------------
# Connectors OAuth 2.1 (C6) — flow chạy nền, web poll /status
# ---------------------------------------------------------------------------
class OAuthStartBody(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None


@app.get("/api/connectors/presets")
async def connector_presets(user: User = Depends(require_admin)):
    from engine import connectors as fc
    from engine import oauth as fo
    installed = {fc._sanitize_name(c.get("preset", "")) for c in fc.load_servers()}
    out = []
    for pid, p in fc.PRESETS.items():
        out.append({
            "id": pid, "label": p["label"], "auth": p["auth"],
            "auth_hint": p["auth_hint"], "installed": pid in installed,
            "oauth": bool(p.get("oauth")),
            "connected": fo.has_oauth(pid), "masked": fo.masked(pid),
        })
    return {"presets": out}


class InstallBody(BaseModel):
    url: str = ""
    write: bool = False


@app.post("/api/connectors/install")
async def connector_install(body: InstallBody, id: str, user: User = Depends(require_admin)):
    from engine import connectors as fc
    pid = (id or "").strip().lower()
    if pid not in fc.PRESETS:
        raise HTTPException(404, f"Không có preset '{id}'")
    msg = fc.add(pid, body.url, body.write)
    if msg.startswith("❌"):
        raise HTTPException(400, msg)
    name = fc.PRESETS[pid]["label"].split(" — ")[0].split(" (")[0]
    return {"ok": True, "message": msg, "name": name}


@app.delete("/api/connectors/{id}/installed")
async def connector_uninstall(id: str, user: User = Depends(require_admin)):
    from engine import connectors as fc
    pid = (id or "").strip().lower()
    for cfg in fc.load_servers():
        if cfg.get("preset", "") == pid:
            return {"ok": True, "message": fc.remove(cfg["name"])}
    raise HTTPException(404, f"Preset '{id}' chưa cài")


@app.post("/api/connectors/{name}/oauth/start")
async def oauth_start(name: str, body: OAuthStartBody, user: User = Depends(require_admin)):
    from engine import connectors as fc
    from engine import oauth as fo
    pid = (name or "").strip().lower()
    if pid not in fc.PRESETS or not fc.PRESETS[pid].get("oauth"):
        raise HTTPException(404, f"Preset '{name}' không hỗ trợ OAuth")
    if body.client_id:
        fo.save_creds(pid, body.client_id, body.client_secret or "")
    import threading
    threading.Thread(target=fo.connect, args=(pid,), daemon=True).start()
    return {"ok": True, "note": "Đang chờ duyệt trong trình duyệt — hỏi /status cho tới connected/error"}


@app.get("/api/connectors/{name}/oauth/status")
async def oauth_status(name: str, user: User = Depends(require_admin)):
    from engine import connectors as fc
    from engine import oauth as fo
    if (name or "").strip().lower() not in fc.PRESETS:
        raise HTTPException(404, "Unknown preset")
    return fo.flow_status(name.strip().lower())


@app.delete("/api/connectors/{name}/oauth")
async def oauth_disconnect(name: str, user: User = Depends(require_admin)):
    from engine import oauth as fo
    return {"ok": fo.forget(name)}


# ---------------------------------------------------------------------------
# MCP servers management
# ---------------------------------------------------------------------------
@app.get("/api/mcp")
async def mcp_status(user: User = Depends(require_admin)):
    return {"servers": mcp_manager.status()}


@app.post("/api/mcp")
async def mcp_add(body: McpServerBody, user: User = Depends(require_admin)):
    servers = load_servers()
    if any(s["name"] == body.name for s in servers):
        raise HTTPException(400, f"Server '{body.name}' đã tồn tại")
    servers.append({"name": body.name, "command": body.command, "args": body.args, "enabled": True})
    save_servers(servers)
    return {"servers": mcp_manager.status()}


@app.post("/api/mcp/{name}/refresh")
async def mcp_refresh(name: str, user: User = Depends(require_admin)):
    await mcp_manager.refresh(name if name != "all" else None)
    return {"servers": mcp_manager.status()}


@app.delete("/api/mcp/{name}")
async def mcp_remove(name: str, user: User = Depends(require_admin)):
    servers = load_servers()
    kept = [s for s in servers if s["name"] != name]
    if len(kept) == len(servers):
        raise HTTPException(404, f"Không tìm thấy server '{name}'")
    save_servers(kept)
    # stop the process if running
    from engine.mcp import _sanitize_name
    srv = mcp_manager._servers.pop(_sanitize_name(name), None)
    if srv:
        await srv.stop_quiet()
    return {"servers": mcp_manager.status()}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
@app.get("/api/sessions")
async def list_sessions(q: str = "", user: User = Depends(require_user)):
    db = _db(user)
    return {"sessions": db.list(q=q)}


class RenameBody(BaseModel):
    title: str


@app.post("/api/sessions/{sid}/rename")
async def rename_session(sid: str, body: RenameBody, user: User = Depends(require_user)):
    db = _db(user)
    if not db.rename(sid, body.title):
        raise HTTPException(404, "Session not found")
    return {"ok": True, "title": body.title.strip()[:80]}


@app.post("/api/sessions")
async def create_session(body: dict | None = None, user: User = Depends(require_user)):
    db = _db(user)
    model = (body or {}).get("model")
    try:
        canonical = model_router.canonical(str(model)) if model else model_router.default_model()
        model_registry.route("code", canonical)
    except (ValueError, ModelCapabilityError) as exc:
        raise HTTPException(400, str(exc)) from exc
    s = db.create(model=canonical)
    return {"session": {"id": s.id, "title": s.title, "model": s.model,
                        "message_count": 0, "updated_at": s.updated_at}}


@app.get("/api/sessions/{sid}")
async def get_session(sid: str, user: User = Depends(require_user)):
    db = _db(user)
    s = db.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    return {"session": s.to_dict()}


@app.get("/api/usage")
async def usage_totals(user: User = Depends(require_user)):
    db = _db(user)
    tot = {"sessions": 0, "prompt_tokens": 0, "completion_tokens": 0,
           "total_tokens": 0, "cost": 0.0}
    for meta in db.list():
        tot["sessions"] += 1
        u = meta.get("usage") or {}
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            tot[k] += u.get(k, 0) or 0
        tot["cost"] += u.get("cost", 0.0) or 0.0
    tot["cost"] = round(tot["cost"], 4)
    return tot


# ---------------------------------------------------------------------------
# Interactive command approvals ("ask" mode)
# ---------------------------------------------------------------------------
@app.post("/api/approvals/{aid}")
async def resolve_approval(aid: str, body: ApprovalBody, user: User = Depends(require_user)):
    from engine import approvals
    ok = approvals.resolve(aid, body.decision, owner_id=user.id)
    if not ok:
        raise HTTPException(404, "Yêu cầu phê duyệt không tồn tại hoặc đã xử lý")
    return {"ok": True, "decision": body.decision}


class ElicitBody(BaseModel):
    action: str = "cancel"          # accept | decline | cancel
    content: dict | None = None


@app.get("/api/elicitations")
async def pending_elicitations(user: User = Depends(require_user)):
    """Danh sách elicitation MCP đang chờ người dùng (poll fallback cho UI)."""
    from engine import elicitations
    return {"pending": elicitations.snapshot(owner_id=user.id)}


@app.post("/api/elicitation/{eid}")
async def resolve_elicitation(eid: str, body: ElicitBody, user: User = Depends(require_user)):
    """Trả lời elicitation MCP (spec: action = accept|decline|cancel + content)."""
    from engine import elicitations
    ok = elicitations.resolve(eid, body.action, body.content, owner_id=user.id)
    if not ok:
        raise HTTPException(404, "Elicitation không tồn tại hoặc đã xử lý")
    return {"ok": True, "action": body.action}


@app.get("/api/models")
async def list_models(user: User = Depends(require_user), provider: str | None = None,
                      capability: str | None = None):
    """Model catalog nhiều provider; client nhận ID/metadata, không nhận endpoint/key."""
    if capability is not None and capability not in CAPABILITIES:
        raise HTTPException(400, "Capability không hợp lệ")
    if capability == "image_generation":
        return {"models": [], "count": 0, "image_generation_adapter": False,
                "detail": "Capability contract đã có; image adapter thuộc phase sau"}
    if provider is not None and provider not in ("openrouter", "google", "custom"):
        raise HTTPException(400, "Provider không hợp lệ")
    if time.time() - _MODELS_CACHE["ts"] > 3600 or not _MODELS_CACHE["data"]:
        try:
            async with httpx.AsyncClient(timeout=25) as c:
                r = await c.get("https://openrouter.ai/api/v1/models")
                r.raise_for_status()
                items = r.json().get("data", [])
            data = []
            for m in items:
                model_id = str(m.get("id", "")).strip()
                if not model_id:
                    continue
                pr = m.get("pricing") or {}
                try:
                    prompt_p = float(pr.get("prompt") or 0)
                    comp_p = float(pr.get("completion") or 0)
                except (TypeError, ValueError):
                    prompt_p = comp_p = 0.0
                spec = model_registry.get(f"openrouter:{model_id}")
                capabilities = set(spec.capabilities)
                modalities = (m.get("architecture") or {}).get("input_modalities") or []
                if "image" in modalities:
                    capabilities.update({"vision", "design"})
                data.append({"id": spec.id, "provider": "openrouter", "model": model_id,
                             "name": m.get("name", model_id), "label": m.get("name", model_id),
                             "capabilities": sorted(capabilities), "adapter": "chat",
                             "context": m.get("context_length"), "prompt_price": prompt_p,
                             "completion_price": comp_p, "free": prompt_p == 0 and comp_p == 0})
            data.sort(key=lambda x: x["id"])
            _MODELS_CACHE["data"] = data
            _MODELS_CACHE["ts"] = time.time()
        except Exception:
            # Catalog tĩnh vẫn dùng được khi mất mạng; không chặn Google direct.
            if not _MODELS_CACHE["data"]:
                _MODELS_CACHE["ts"] = 0
    rows = list(_MODELS_CACHE["data"])
    known = {row["id"] for row in rows}
    for spec in model_registry.list():
        if spec.id not in known:
            rows.append({**spec.public(), "name": spec.label, "context": None,
                         "prompt_price": 0.0, "completion_price": 0.0, "free": False})
            known.add(spec.id)
    if config.get_provider() == "custom":
        spec = model_registry.get(model_registry.canonical(config.get_model(), "custom"))
        if spec.id not in known:
            rows.append({**spec.public(), "name": spec.label, "context": None,
                         "prompt_price": 0.0, "completion_price": 0.0, "free": True})
    rows = [row for row in rows if (provider is None or row["provider"] == provider)
            and (capability is None or capability in row.get("capabilities", []))]
    rows.sort(key=lambda x: x["id"])
    return {"models": rows, "count": len(rows), "image_generation_adapter": False,
            "capabilities": sorted(CAPABILITIES)}


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str, user: User = Depends(require_user)):
    db = _db(user)
    ok = db.delete(sid)
    return {"ok": ok}


# ----------------------------------------------------- S8: Skills catalog (web tab)
@app.get("/api/skills")
async def skills_list(sid: str, user: User = Depends(require_user)):
    db = _db(user)
    if not db.get(sid):
        raise HTTPException(404, "Session not found")
    from engine.skills import list_skills
    skills, diags = list_skills(db.workspace(sid))
    rows = []
    for x in skills:
        rows.append({
            "name": x["name"], "description": x.get("description", ""),
            "path": str(x.get("path")), "source": x.get("source", ""),
            "fmt": x.get("fmt", ""), "model_invocable": bool(x.get("model_invocable", True)),
            "trusted": bool(x.get("trusted", True)),
            "allowed_tools": x.get("allowed_tools", ""),
            "diags": x.get("diags") or [],
        })
    return {"skills": rows, "diags": diags[:15]}


class SkillToggleBody(BaseModel):
    path: str
    invocable: bool


@app.post("/api/skills/toggle")
async def skills_toggle(sid: str, body: SkillToggleBody, user: User = Depends(require_user)):
    db = _db(user)
    from engine import skillmgr
    if not db.get(sid):
        raise HTTPException(404, "Session not found")
    ws = db.workspace(sid)
    if user.role != "admin":
        from engine.skills import list_skills
        skills, _ = list_skills(ws)
        match = next((x for x in skills if str(x.get("path")) == str(Path(body.path))), None)
        if match is not None and match.get("source") != "project":
            raise HTTPException(403, "Member chỉ đổi skill trong project workspace của mình")
    msg = skillmgr.set_model_invocable(ws, body.path, body.invocable)
    code = 400 if msg.startswith("❌") else 200
    if code == 400:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg}


class SkillTrustBody(BaseModel):
    name: str


@app.post("/api/skills/trust")
async def skills_trust(sid: str, body: SkillTrustBody, user: User = Depends(require_user)):
    db = _db(user)
    from engine import skillmgr
    if not db.get(sid):
        raise HTTPException(404, "Session not found")
    msg = skillmgr.trust(db.workspace(sid), body.name)
    code = 400 if msg.startswith("❌") else 200
    if code == 400:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg}


# ----------------------------------------------------- F2: cross-session messaging
class MessageBody(BaseModel):
    text: str
    from_session: str = "web"


@app.post("/api/sessions/{sid}/messages")
async def message_send(sid: str, body: MessageBody, user: User = Depends(require_user)):
    db = _db(user)
    from engine import bus as fbus
    if not db.get(sid):
        raise HTTPException(404, "Session not found")
    if not body.text.strip():
        raise HTTPException(400, "Empty message")
    from_session = body.from_session or "web"
    if from_session != "web" and db.get(from_session) is None:
        raise HTTPException(404, "Source session not found")
    ent = fbus.send(sid, from_session, body.text)
    return {"ok": True, "entry": ent}


@app.get("/api/sessions/{sid}/messages")
async def message_inbox(sid: str, peek: bool = False, user: User = Depends(require_user)):
    db = _db(user)
    from engine import bus as fbus
    if not db.get(sid):
        raise HTTPException(404, "Session not found")
    rows = fbus.peek(sid) if peek else fbus.inbox(sid)
    return {"messages": rows, "count": len(rows)}


# ----------------------------------------------------- B2: worktree sub-agent
@app.get("/api/worktrees")
async def worktree_list(user: User = Depends(require_user)):
    from engine import worktree as fwt
    own = {row["id"] for row in _db(user).list()}
    return {"worktrees": [row for row in await fwt.list_all() if row.get("session") in own]}


@app.post("/api/worktrees/{sub_sid}/merge")
async def worktree_merge(sub_sid: str, sid: str, user: User = Depends(require_user)):
    db = _db(user)
    from engine import worktree as fwt
    st = db.get(sid)
    if not st or db.get(sub_sid) is None:
        raise HTTPException(404, "Session not found")
    return await fwt.merge(sub_sid, sid, sid, db.workspace(sid))


@app.delete("/api/worktrees/{sub_sid}")
async def worktree_discard(sub_sid: str, sid: str, user: User = Depends(require_user)):
    db = _db(user)
    from engine import worktree as fwt
    if not db.get(sid) or db.get(sub_sid) is None:
        raise HTTPException(404, "Session not found")
    return await fwt.discard(sub_sid, sid)


# ----------------------------------------------------- F1: /loop — chạy định kỳ
class LoopBody(BaseModel):
    text: str
    every: str = "30m"  # "45s" | "30m" | "2h" | số = phút
    mode: str = "agent"
    max_runs: int = 0  # 0 = tới khi /loop stop hoặc restart server


async def _loop_turn(sid: str, text: str, mode: str, owner_id: str, allow_mcp: bool) -> str:
    """Mỗi nhịp tự mở scoped store; không giữ quyền/global store trong closure."""
    db = ScopedSessionStore(store, owner_id, allow_mcp=allow_mcp)
    st = db.get(sid)
    if not st:
        return "(phiên đã xoá)"
    demo = not config.has_provider_credentials(llm.split_model_id(st.model)[0])
    agent = Agent(db, sid, router=model_router)
    source = send_demo(agent, text) if demo else agent.send(text, chat_mode=mode)
    last = ""
    async for ev in source:
        if ev.get("type") == "assistant_message" and ev.get("content"):
            last = str(ev["content"])
    return last


def _loop_runner(owner_id: str, allow_mcp: bool):
    async def run(sid: str, text: str, mode: str) -> str:
        return await _loop_turn(sid, text, mode, owner_id, allow_mcp)
    return run


@app.post("/api/sessions/{sid}/loop")
async def loop_start(sid: str, body: LoopBody, user: User = Depends(require_user)):
    db = _db(user)
    from engine import scheduler as fsched
    if not db.get(sid):
        raise HTTPException(404, "Session not found")
    if not body.text.strip():
        raise HTTPException(400, "Loop cần nội dung tác vụ")
    every_s = fsched.parse_interval(body.every, default_minutes=30)
    mode = body.mode if body.mode in ("direct", "agent", "plan", "architect") else "agent"
    max_runs = max(0, min(int(body.max_runs), 10000))
    status = fsched.manager.start(sid, every_s, body.text.strip(), mode, _loop_runner(user.id, user.role == "admin"), max_runs)
    return {"ok": True, "status": status,
            "note": "Loop sống trong tiến trình server — restart là dừng"}


@app.get("/api/sessions/{sid}/loop")
async def loop_status(sid: str, user: User = Depends(require_user)):
    if not _db(user).get(sid):
        raise HTTPException(404, "Session not found")
    from engine import scheduler as fsched
    return fsched.manager.status(sid)


@app.delete("/api/sessions/{sid}/loop")
async def loop_stop(sid: str, user: User = Depends(require_user)):
    if not _db(user).get(sid):
        raise HTTPException(404, "Session not found")
    from engine import scheduler as fsched
    return {"ok": fsched.manager.stop(sid)}


# ----------------------------------------------------- E5: chỉnh sửa tin & chạy lại
class RerunBody(BaseModel):
    index: int
    text: str


@app.post("/api/sessions/{sid}/rerun")
async def rerun_session(sid: str, body: RerunBody, user: User = Depends(require_user)):
    """Cắt session từ tin user thứ `index` và thay nội dung mới — web sẽ gọi /chat rerun=true."""
    db = _db(user)
    st = db.get(sid)
    if not st:
        raise HTTPException(404, "Session not found")
    if not (0 <= body.index < len(st.messages)):
        raise HTTPException(400, f"index {body.index} ngoài phạm vi (0..{len(st.messages) - 1})")
    if st.messages[body.index].get("role") != "user":
        raise HTTPException(400, "index không trỏ vào tin nhắn của người dùng")
    st.messages = st.messages[:body.index] + [{"role": "user", "content": body.text}]
    db.save(st)
    return {"ok": True, "messages": len(st.messages)}


# ----------------------------------------------------- comfort: undo/compact/init
@app.post("/api/sessions/{sid}/undo")
async def undo_session(sid: str, user: User = Depends(require_user)):
    """↩ Hoàn tác thay đổi gần nhất của agent trong workspace (checkpoint git nội bộ)."""
    db = _db(user)
    s = db.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    from engine import checkpoints
    if not checkpoints.available():
        raise HTTPException(409, "git không có mặt trên máy — checkpoint không khả dụng")
    ws = db.workspace(sid)
    res = await checkpoints.undo(checkpoints.key_for(ws), ws)
    return {"ok": bool(res.get("ok")), "message": str(res.get("message", ""))}


@app.post("/api/sessions/{sid}/compact")
async def compact_session_ep(sid: str, body: dict | None = None, user: User = Depends(require_user)):
    """🧹 Nén hội thoại: LLM tóm tắt các tin nhắn cũ, giữ vài tin cuối."""
    db = _db(user)
    s = db.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    from engine.agent import compact_session
    agent = Agent(db, sid, router=model_router)
    res = await compact_session(agent, (body or {}).get("instructions") or "")
    return res


@app.post("/api/sessions/{sid}/init")
async def init_agents_ep(sid: str, user: User = Depends(require_user)):
    """🚀 /init — phân tích workspace, sinh AGENTS.md (demo-mode khi chưa có key)."""
    db = _db(user)
    s = db.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    from engine.agent import init_agents_md
    agent = Agent(db, sid, router=model_router)
    res = await init_agents_md(agent)
    return res


@app.post("/api/sessions/{sid}/fork")
async def fork_session(sid: str, user: User = Depends(require_user)):
    """🍴 Fork — nhân bản phiên: copy messages + workspace thành bản mới."""
    db = _db(user)
    ns = db.fork(sid)
    if ns is None:
        raise HTTPException(404, "Session not found")
    return {"session": {"id": ns.id, "title": ns.title, "model": ns.model,
                        "message_count": len(ns.messages),
                        "updated_at": ns.updated_at}}


@app.get("/api/sessions/{sid}/context")
async def session_context(sid: str, user: User = Depends(require_user)):
    """🧠 Mức dùng context của phiên (cho /context + footer web)."""
    db = _db(user)
    s = db.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    return Agent(db, sid).context_stats()


def _audit_rows(user: User, n: int) -> list[dict]:
    from engine import auditlog
    own = {row["id"] for row in _db(user).list()}
    scan = min(10000, max(200, n * 20))
    return [e for e in auditlog.tail(scan) if e.get("session") in own][:n]


@app.get("/api/audit")
async def audit_tail(n: int = 120, user: User = Depends(require_user)):
    """Nhật ký tool call (JSONL data/audit/) — n giới hạn 1..500."""
    return {"entries": _audit_rows(user, max(1, min(n, 500)))}


@app.get("/api/audit/export")
async def audit_export(user: User = Depends(require_user)):
    """Xuất audit log CSV (tối đa 2000 mục mới nhất) — Excel/Sheets đọc trực tiếp."""
    import csv as _csv
    import io as _io

    from fastapi.responses import Response

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["ts", "session", "tool", "source", "ok", "ms", "args", "note"])
    for e in _audit_rows(user, 2000):
        w.writerow([e.get("ts", ""), e.get("session", ""), e.get("tool", ""),
                    e.get("source", ""), "1" if e.get("ok") else "0",
                    "" if e.get("ms") is None else e.get("ms"),
                    json.dumps(e.get("args") or {}, ensure_ascii=False),
                    e.get("note", "")])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="forge-audit.csv"'})


@app.get("/api/doctor")
async def doctor_endpoint(user: User = Depends(require_admin)):
    """🩺 Chẩn đoán toàn hệ thống (python/git/key/model/MCP/LSP/dữ liệu…)."""
    db = _db(user)
    from engine.diagnostics import doctor
    return await doctor(db)


@app.get("/api/sessions/{sid}/export")
async def export_session(sid: str, user: User = Depends(require_user)):
    """⤓ /export — tải hội thoại dạng Markdown."""
    db = _db(user)
    s = db.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    from urllib.parse import quote

    from engine.export import to_markdown
    md = to_markdown(s)
    fname = f"forge-{s.id}.md"
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


# ---------------------------------------------------------------------------
# Chat streaming (SSE)
# ---------------------------------------------------------------------------
@app.post("/api/sessions/{sid}/chat")
async def chat(sid: str, body: ChatBody, request: Request, user: User = Depends(require_user)):
    db = _db(user)
    s = db.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    text = body.text.strip()
    if not text and not body.rerun:
        raise HTTPException(400, "Empty message")

    model = body.model or None
    chat_mode = body.mode if body.mode in ("direct", "agent", "plan", "architect") else "agent"
    ws = db.workspace(sid)

    # /run <tên> <task> — custom agent từ .forge/agents/<name>.md (đè model/mode nếu có)
    from engine import agents as fagents
    agent_exp = fagents.expand(text, ws)
    if agent_exp is not None:
        text, ag_model, ag_mode = agent_exp
        if ag_model:
            model = ag_model
        if ag_mode:
            chat_mode = ag_mode
    demo = not config.has_provider_credentials(llm.split_model_id(model or s.model)[0])
    # /audit [n] — xem nhật ký tool call, không cần LLM
    audit_synthetic: list[dict] | None = None
    if text == "/audit" or text.startswith("/audit "):
        from engine import auditlog
        a_arg = text[6:].strip()
        a_n = min(200, max(1, int(a_arg))) if a_arg.isdigit() else 20
        audit_synthetic = [{"type": "assistant_message",
                            "content": auditlog.format_listing(a_n, rows=_audit_rows(user, a_n))}]
    # /msg <phiên> <nội dung> + /inbox — F2 cross-session messaging
    msg_synthetic: list[dict] | None = None
    if text.startswith("/msg ") or text == "/inbox":
        from engine import bus as fbus
        if text == "/inbox":
            rows = fbus.inbox(sid)
            if rows:
                m_out = "\n\n".join(f"📥 **{r['from']}** ({str(r['ts'])[11:16]}): {r['text'][:300]}"
                                    for r in rows)
            else:
                m_out = "(hộp thư trống)"
            msg_synthetic = [{"type": "assistant_message", "content": m_out}]
        else:
            parts = text[5:].strip().split(None, 1)
            to_sid = parts[0].strip() if parts else ""
            m_text = parts[1].strip() if len(parts) > 1 else ""
            if not to_sid or not m_text:
                msg_synthetic = [{"type": "assistant_message",
                                  "content": "❌ Cú pháp: `/msg <id-phiên> <nội dung>`"}]
            elif db.get(to_sid) is None:
                msg_synthetic = [{"type": "assistant_message",
                                  "content": f"❌ Không có phiên '{to_sid}'."}]
            else:
                fbus.send(to_sid, sid, m_text)
                msg_synthetic = [{"type": "assistant_message",
                                  "content": f"📨 Đã gửi tới {to_sid} — phiên đích sẽ thấy ở lượt kế tiếp."}]
    # /worktree [list|merge <sub>|discard <sub>] — B2 quản lý worktree sub-agent
    wt_synthetic: list[dict] | None = None
    if text == "/worktree" or text.startswith("/worktree "):
        from engine import worktree as fwt
        w_arg = text[9:].strip()
        if w_arg.startswith("merge "):
            sub = w_arg[6:].strip()
            if db.get(sub) is None:
                raise HTTPException(404, "Session not found")
            res = await fwt.merge(sub, sid, sid, ws)
            if res["ok"]:
                try:
                    from engine import checkpoints as fckpt
                    await fckpt.snapshot(sid, ws, f"merge wt-{sub}")
                except Exception:  # noqa: BLE001, S110 — snapshot lỗi không xoá kết quả merge
                    pass
            wt_synthetic = [{"type": "assistant_message",
                             "content": ("✅ " if res["ok"] else "❌ ") + res["message"]}]
        elif w_arg.startswith("discard "):
            sub = w_arg[8:].strip()
            if db.get(sub) is None:
                raise HTTPException(404, "Session not found")
            res = await fwt.discard(sub, sid)
            wt_synthetic = [{"type": "assistant_message",
                             "content": ("🗑 Đã bỏ worktree: " + ", ".join(res["removed"]))
                                        if res["ok"] else "(không có worktree nào để bỏ)"}]
        else:
            own = {row["id"] for row in db.list()}
            rows = [row for row in await fwt.list_all() if row.get("session") in own]
            if not rows:
                wt_synthetic = [{"type": "assistant_message",
                                 "content": "Không có worktree nào. Dùng: spawn_subagent với isolation=worktree, rồi `/worktree merge <phiên-con>` để gộp."}]
            else:
                lines = ["### 📁 Worktree đang cô lập"]
                for r in rows:
                    lines.append(f"- `{r['session']}` — {r['stat']}\n  `{r['path']}`")
                lines.append("Gộp: `/worktree merge <phiên-con>` · Bỏ: `/worktree discard <phiên-con>`")
                wt_synthetic = [{"type": "assistant_message", "content": "\n".join(lines)}]
    # /loop [interval] [off|status] — lịch chạy định kỳ trong tiến trình (F1)
    loop_synthetic: list[dict] | None = None
    if text == "/loop" or text.startswith("/loop "):
        from engine import scheduler as fsched
        l_arg = text[5:].strip()
        if l_arg.lower() in ("off", "stop", "x"):
            was = fsched.manager.stop(sid)
            loop_synthetic = [{"type": "assistant_message",
                               "content": "⚪ Đã dừng loop." if was else "(không có loop nào đang chạy)"}]
        elif not l_arg:
            st_loop = fsched.manager.status(sid)
            loop_synthetic = [{"type": "assistant_message",
                               "content": ("🔁 Đang chạy: mỗi `" + fsched.fmt_interval(st_loop["every"])
                                           + "` — «" + st_loop["text"] + "» ("
                                           + str(st_loop["runs"]) + " lượt)"
                                           if st_loop["running"] else
                                           "Không có loop nào. Cú pháp: `/loop <30m|1h> <tác vụ>` · `/loop off`")}]
        else:
            parts = l_arg.split(None, 1)
            every_s = fsched.parse_interval(parts[0], default_minutes=30)
            task_text = parts[1].strip() if len(parts) > 1 else ""
            if not task_text:
                loop_synthetic = [{"type": "assistant_message",
                                   "content": "❌ Thiếu tác vụ: `/loop <30m|1h> <tác vụ>`"}]
            else:
                mode_l = chat_mode if chat_mode != "plan" else "agent"
                status_l = fsched.manager.start(sid, every_s, task_text, mode_l, _loop_runner(user.id, user.role == "admin"))
                loop_synthetic = [{"type": "assistant_message",
                                   "content": f"🔁 Loop BẬT — mỗi `{fsched.fmt_interval(status_l['every'])}` chạy «{task_text}» "
                                              "(tool + audit như chat thường; sống trong tiến trình server, restart là dừng; `/loop off` để tắt)"}]
    # /connectors [add|auth|allow|deny|remove] — quản lý connector MCP, không cần LLM
    connectors_synthetic: list[dict] | None = None
    if text == "/connectors" or text.startswith("/connectors "):
        if user.role != "admin":
            raise HTTPException(403, "Chỉ admin được quản lý connector toàn server")
        from engine import connectors as fconn
        c_arg = text[11:].strip()
        if c_arg.startswith("add "):
            parts = c_arg[4:].strip().split()
            c_out = fconn.add(parts[0], parts[1] if len(parts) > 1 else "", "--write" in parts)
        elif c_arg.startswith("auth "):
            parts = c_arg[5:].strip().split(None, 1)
            c_out = fconn.auth(parts[0], parts[1] if len(parts) > 1 else "")
        elif c_arg.startswith("allow "):
            parts = c_arg[6:].strip().split()
            c_out = fconn.allow(parts[0], parts[1] if len(parts) > 1 else "*")
        elif c_arg.startswith("deny "):
            parts = c_arg[5:].strip().split()
            c_out = fconn.deny(parts[0], parts[1] if len(parts) > 1 else "*")
        elif c_arg.startswith("remove "):
            c_out = fconn.remove(c_arg[7:].strip())
        else:
            c_out = fconn.status_listing()
        connectors_synthetic = [{"type": "assistant_message", "content": c_out}]
    # /skills [add|new|remove …] — quản lý skill (chuẩn Agent Skills), không cần LLM
    skills_synthetic: list[dict] | None = None
    if text == "/skills" or text.startswith("/skills "):
        from engine import skillmgr
        s_arg = text[7:].strip()
        if user.role != "admin" and s_arg.startswith(("add ", "remove ")):
            raise HTTPException(403, "Skill global chỉ admin được cài/xoá; member dùng /skills new trong workspace")
        if s_arg.startswith("add "):
            # git clone có thể tới 90s — đẩy sang thread để không khoá event loop
            s_out = await asyncio.to_thread(skillmgr.add, ws, s_arg[4:].strip())
        elif s_arg.startswith("new "):
            parts = s_arg[4:].strip().split(None, 1)
            s_out = skillmgr.new_skill(ws, parts[0] if parts else "",
                                       parts[1] if len(parts) > 1 else "")
        elif s_arg.startswith("remove "):
            s_out = skillmgr.remove(ws, s_arg[7:].strip())
        elif s_arg.startswith("trust"):
            s_out = skillmgr.trust(ws, s_arg[5:].strip())
        else:
            s_out = skillmgr.format_listing(ws)
        skills_synthetic = [{"type": "assistant_message", "content": s_out}]
    else:
        # /<tên-lệnh> từ .forge/commands & skills chuẩn SKILL.md — expand trước mọi nhánh khác
        from engine import commands as fcmd
        blocked = fcmd.blocked_reason(ws, text)
        if blocked is not None:
            skills_synthetic = [{"type": "assistant_message", "content": blocked}]
        else:
            expanded = fcmd.expand(text, ws)
            if expanded is not None:
                text = expanded
    # ---- lệnh nội bộ không cần LLM: /review /diff /memory và '# ' quick-memory ----
    synthetic: list[dict] | None = (audit_synthetic if audit_synthetic is not None else
                                    (msg_synthetic if msg_synthetic is not None else
                                    (wt_synthetic if wt_synthetic is not None else
                                     (loop_synthetic if loop_synthetic is not None else
                                      (connectors_synthetic
                                       if connectors_synthetic is not None else skills_synthetic)))))
    from engine import memory as fmem
    if text.startswith("/review"):
        from engine import review as freview
        r_arg = text[len("/review"):].strip()
        try:
            diff_text, label = await freview.collect_diff(ws, sid, r_arg)
            if demo:
                synthetic = [{"type": "assistant_message",
                              "content": "(demo mode) /review cần API key để chạy LLM review — "
                                         f"diff đã sẵn sàng ({label}, {len(diff_text):,} ký tự)."}]
            else:
                text = freview.build_prompt(diff_text, r_arg, label)
                chat_mode = "plan"  # review chỉ đọc
        except ValueError as e:
            synthetic = [{"type": "assistant_message", "content": f"🔍 {e}"}]
    elif text.startswith("/diff"):
        from engine import review as freview
        d_arg = text[len("/diff"):].strip()
        try:
            diff_text, label = await freview.collect_diff(ws, sid, d_arg)
            diff_body = diff_text if len(diff_text) <= 12000 else diff_text[:12000] + "\n… (cắt ở 12KB)"
            synthetic = [{"type": "assistant_message",
                          "content": f"📄 **Diff — {label}:**\n\n```diff\n{diff_body}\n```"}]
        except ValueError as e:
            synthetic = [{"type": "assistant_message", "content": f"📄 {e}"}]
    elif text == "/memory" or text.startswith("/memory "):
        m_arg = text[7:].strip()
        synthetic = [{"type": "assistant_message",
                      "content": fmem.clear_memory(ws) if m_arg == "clear"
                      else fmem.memory_overview(ws)}]
    elif text.startswith("# ") and len(text.strip()) > 2:
        synthetic = [{"type": "assistant_message",
                      "content": fmem.quick_memory(ws, text.strip()[2:].strip())}]

    # @file references → đính kèm nội dung file vào message
    from engine import atfiles
    text, _attached = atfiles.expand_at_refs(text, ws)

    # ảnh đính kèm (multimodal) — content parts kiểu OpenAI/OpenRouter
    content = None
    images = [u for u in (body.images or []) if isinstance(u, str) and u.startswith("data:image/")][:4]
    if images and not demo:
        content = [{"type": "text", "text": text}] + [
            {"type": "image_url", "image_url": {"url": u}} for u in images]
    capability = "vision" if images and not demo else body.capability
    if capability == "image_generation":
        raise HTTPException(501, "Image generation mới có contract; adapter thuộc phase sau")
    try:
        model = model_registry.route(capability, model or s.model).id
    except (ValueError, ModelCapabilityError) as exc:
        raise HTTPException(400, str(exc)) from exc
    demo = not config.has_provider_credentials(llm.split_model_id(model)[0])

    async def gen():
        try:
            if synthetic is not None:
                for ev in synthetic:
                    if await request.is_disconnected():
                        return
                    yield sse(ev)
                return
            agent = Agent(db, sid, model=model, router=model_router)
            if demo:
                demo_text = text
                if images:
                    demo_text += (f"\n\n(demo mode: bỏ qua {len(images)} ảnh đính kèm — "
                                  "nhập API key để dùng vision)")
                source = send_demo(agent, demo_text)
            else:
                source = agent.send(text, chat_mode=chat_mode, content=content,
                                    append_user=not body.rerun)
            last_assistant = ""
            async for ev in source:
                if await request.is_disconnected():
                    return
                if ev.get("type") == "assistant_message" and ev.get("content"):
                    last_assistant = str(ev["content"])
                yield sse(ev)
            # B1 auto-commit (opt-in) — sau lượt agent thật, chỉ mode đổi file
            if (not demo and chat_mode in ("agent", "architect")
                    and config.get_auto_commit()):
                try:
                    from engine import autocommit as fac
                    res = await fac.commit_turn(ws, sid, text, last_assistant)
                    if res:
                        yield sse({"type": "auto_commit", "subject": res["subject"],
                                   "files": res["files"]})
                except Exception as _ace:  # noqa: BLE001 — autocommit lỗi chỉ log, không chết lượt
                    print(f"[autocommit] bỏ qua: {_ace}")
        except Exception as e:  # noqa: BLE001 — lỗi lượt phải report SSE, không chết stream
            yield sse({"type": "error", "message": f"Lỗi server: {e}"})
        yield sse({"type": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Batch: parallel sub-agents
# ---------------------------------------------------------------------------
@app.post("/api/batch")
async def batch(body: BatchBody, request: Request, user: User = Depends(require_user)):
    db = _db(user)
    prompts = [p.strip() for p in body.prompts if p.strip()][:5]
    if not prompts:
        raise HTTPException(400, "Không có tác vụ nào")
    try:
        batch_model = model_registry.route("code", body.model).id if body.model else model_router.default_model()
    except (ValueError, ModelCapabilityError) as exc:
        raise HTTPException(400, str(exc)) from exc
    demo = not config.has_provider_credentials(llm.split_model_id(batch_model)[0])

    async def gen():
        try:
            async for ev in run_batch(db, [{"prompt": p, "model": batch_model} for p in prompts],
                                      demo=demo, router=model_router):
                if await request.is_disconnected():
                    return
                yield sse(ev)
        except Exception as e:  # noqa: BLE001 — lỗi batch phải report SSE
            yield sse({"type": "error", "message": f"Lỗi batch: {e}"})
        yield sse({"type": "done"})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


@app.post("/api/battle")
async def battle(body: BattleBody, request: Request, user: User = Depends(require_user)):
    """⚔ Cùng 1 prompt chạy trên nhiều model song song."""
    db = _db(user)
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "Thiếu prompt")
    try:
        battle_models = [model_registry.route("code", m).id for m in body.models]
    except (ValueError, ModelCapabilityError) as exc:
        raise HTTPException(400, str(exc)) from exc

    async def gen():
        try:
            async for ev in run_battle(db, prompt, battle_models, demo=None, router=model_router):
                if await request.is_disconnected():
                    return
                yield sse(ev)
        except Exception as e:  # noqa: BLE001 — lỗi battle phải report SSE
            yield sse({"type": "error", "message": f"Lỗi battle: {e}"})
        yield sse({"type": "done"})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


@app.post("/api/workspace/exec")
async def workspace_exec(sid: str, body: ExecBody, user: User = Depends(require_user)):
    """Terminal tích hợp: NGƯỜI DÙNG chạy lệnh trực tiếp trong workspace."""
    ws = _ws(sid, user)
    cmd = body.command.strip()
    if not cmd:
        raise HTTPException(400, "Thiếu lệnh")
    verdict = guard.assess_command(cmd)
    if verdict["level"] == "danger" and config.load_config().get("approval_mode", "guarded") != "auto":
        return {"blocked": True, "level": "danger", "reasons": verdict["reasons"],
                "output": f"BLOCKED: lệnh nguy hiểm ({'; '.join(verdict['reasons'])}). "
                          "Đổi sang Auto trong ⚙ nếu bạn thực sự muốn chạy."}
    result = await tools.execute_tool("run_command", {"command": cmd}, ws)
    return {"blocked": False, "ok": result["ok"], "output": result["output"]}


@app.post("/api/workspace/open")
async def workspace_open(sid: str, body: OpenWorkspaceBody, user: User = Depends(require_admin)):
    """Mở một thư mục dự án thật làm workspace. Yêu cầu env FORGE_ALLOW_OPEN=1."""
    db = _db(user)
    import os
    if os.environ.get("FORGE_ALLOW_OPEN", "").strip() != "1":
        raise HTTPException(403,
                            "Tính năng mở dự án thật đang TẮT vì lý do an toàn. "
                            "Chạy server với biến môi trường FORGE_ALLOW_OPEN=1 để bật.")
    _ws(sid, user)  # ensure session exists
    try:
        target = db.open_workspace(sid, body.path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "workspace": str(target)}


@app.post("/api/workspace/close")
async def workspace_close(sid: str, user: User = Depends(require_user)):
    db = _db(user)
    if not db.get(sid):
        raise HTTPException(404, "Session not found")
    db.close_workspace(sid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Workspace files
# ---------------------------------------------------------------------------
def _ws(sid: str, user: User) -> Path:
    db = _db(user)
    s = db.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    return db.workspace(sid)


def _safe_path(ws: Path, rel: str) -> Path:
    p = (ws / rel).resolve()
    if p != ws.resolve() and ws.resolve() not in p.parents:
        raise HTTPException(400, "Path escapes workspace")
    return p


@app.get("/api/workspace/tree")
async def workspace_tree(sid: str, user: User = Depends(require_user)):
    ws = _ws(sid, user)

    def node(path: Path, depth: int) -> list[dict]:
        items: list[dict] = []
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except Exception:  # noqa: BLE001 — tree lỗi trả rỗng, không chết request
            return []
        for e in entries:
            if e.name in tools.SKIP_DIRS or e.name.startswith("."):
                continue
            if e.is_dir():
                items.append({"name": e.name, "type": "dir",
                              "children": node(e, depth + 1) if depth < 6 else []})
            else:
                items.append({"name": e.name, "type": "file",
                              "size": e.stat().st_size, "path": str(e.relative_to(ws))})
        return items

    return {"tree": node(ws, 0)}


@app.get("/api/workspace/file")
async def read_workspace_file(sid: str, path: str, user: User = Depends(require_user)):
    ws = _ws(sid, user)
    p = _safe_path(ws, path)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "File not found")
    raw = p.read_bytes()
    if b"\x00" in raw[:2000]:
        return {"path": path, "binary": True, "content": ""}
    return {"path": path, "binary": False, "content": raw.decode("utf-8", "replace")}


@app.put("/api/workspace/file")
async def save_workspace_file(sid: str, body: FileSaveBody, user: User = Depends(require_user)):
    ws = _ws(sid, user)
    p = _safe_path(ws, body.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.content, encoding="utf-8")
    return {"ok": True, "path": body.path, "size": len(body.content)}


@app.delete("/api/workspace/file")
async def delete_workspace_file(sid: str, path: str, user: User = Depends(require_user)):
    ws = _ws(sid, user)
    p = _safe_path(ws, path)
    if p.exists():
        p.unlink()
        return {"ok": True}
    raise HTTPException(404, "File not found")


@app.post("/api/workspace/upload")
async def upload_files(sid: str, files: list[UploadFile] = File(...), user: User = Depends(require_user)):
    ws = _ws(sid, user)
    saved, skipped = [], []
    MAX_SIZE = 20 * 1024 * 1024
    for f in files[:20]:
        name = Path(f.filename or "").name  # strip any path components
        if not name or name.startswith("."):
            skipped.append(f.filename or "?")
            continue
        data = await f.read()
        if len(data) > MAX_SIZE:
            skipped.append(f"{name} (>20MB)")
            continue
        p = _safe_path(ws, name)
        p.write_bytes(data)
        saved.append(name)
    if saved:
        # refresh tree cache implicitly (none) — return
        pass
    return {"saved": saved, "skipped": skipped}


@app.get("/api/workspace/export")
async def export_workspace(sid: str, user: User = Depends(require_user)):
    ws = _ws(sid, user)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in tools._iter_files(ws):
            z.write(f, f.relative_to(ws))
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=forge-{sid}.zip"},
    )


# ---------------------------------------------------------------------------
# Static web UI (built from web/ → server/static)
# ---------------------------------------------------------------------------
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:  # pragma: no cover - dev fallback
    @app.get("/")
    async def root():
        return JSONResponse({"info": "Web UI chưa build. Chạy: cd web && npm install && npm run build"})
