"""Forge Agent — FastAPI server: SSE agent streaming, sessions, workspace files, static web UI.

Run:  uvicorn server.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import io
import json
import time
import zipfile
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import config, llm, tools, guard    # noqa: E402
from engine.agent import Agent, send_demo, run_batch   # noqa: E402
from engine.mcp import manager as mcp_manager, load_servers, save_servers  # noqa: E402
from engine.session import SessionStore        # noqa: E402

app = FastAPI(title="Forge Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
store = SessionStore()

STATIC_DIR = ROOT / "server" / "static"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ChatBody(BaseModel):
    text: str
    model: str | None = None


class SettingsBody(BaseModel):
    api_key: str | None = None
    model: str | None = None
    approval_mode: str | None = None
    docker_sandbox: bool | None = None
    max_tokens: int | None = None


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


_MODELS_CACHE = {"ts": 0.0, "data": []}


# ---------------------------------------------------------------------------
# Health / settings
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    key = config.get_api_key()
    cfg = config.load_config()
    return {
        "ok": True,
        "demo": key is None,
        "model": config.get_model(),
        "key_masked": config.mask_key(key),
        "default_models": config.DEFAULT_MODELS,
        "approval_mode": cfg.get("approval_mode", "guarded"),
        "docker_sandbox": bool(cfg.get("docker_sandbox")),
        "docker_available": guard.DOCKER_AVAILABLE,
        "max_tokens": config.get_max_tokens(),
    }


@app.get("/api/settings")
async def get_settings():
    return await health()


class KeyCheckBody(BaseModel):
    api_key: str | None = None


@app.post("/api/keycheck")
async def keycheck(body: KeyCheckBody | None = None):
    """Verify the saved (or provided) OpenRouter key against /api/v1/auth/key."""
    provided = body.api_key.strip() if (body and body.api_key) else None
    return await llm.check_key(provided)


@app.post("/api/settings")
async def set_settings(body: SettingsBody):
    patch: dict = {}
    if body.api_key is not None and body.api_key.strip():
        patch["api_key"] = body.api_key.strip()
    if body.model is not None and body.model.strip():
        patch["model"] = body.model.strip()
    if body.approval_mode is not None and body.approval_mode in ("guarded", "ask", "auto"):
        patch["approval_mode"] = body.approval_mode
    if body.docker_sandbox is not None:
        patch["docker_sandbox"] = body.docker_sandbox
    if body.max_tokens is not None and 256 <= int(body.max_tokens) <= 65536:
        patch["max_tokens"] = int(body.max_tokens)
    config.save_config(patch)
    return await health()


# ---------------------------------------------------------------------------
# MCP servers management
# ---------------------------------------------------------------------------
@app.get("/api/mcp")
async def mcp_status():
    return {"servers": mcp_manager.status()}


@app.post("/api/mcp")
async def mcp_add(body: McpServerBody):
    servers = load_servers()
    if any(s["name"] == body.name for s in servers):
        raise HTTPException(400, f"Server '{body.name}' đã tồn tại")
    servers.append({"name": body.name, "command": body.command, "args": body.args, "enabled": True})
    save_servers(servers)
    return {"servers": mcp_manager.status()}


@app.post("/api/mcp/{name}/refresh")
async def mcp_refresh(name: str):
    await mcp_manager.refresh(name if name != "all" else None)
    return {"servers": mcp_manager.status()}


@app.delete("/api/mcp/{name}")
async def mcp_remove(name: str):
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
async def list_sessions():
    return {"sessions": store.list()}


@app.post("/api/sessions")
async def create_session(body: dict | None = None):
    model = (body or {}).get("model")
    s = store.create(model=model or "")
    return {"session": {"id": s.id, "title": s.title, "model": s.model,
                        "message_count": 0, "updated_at": s.updated_at}}


@app.get("/api/sessions/{sid}")
async def get_session(sid: str):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    return {"session": s.to_dict()}


@app.get("/api/usage")
async def usage_totals():
    tot = {"sessions": 0, "prompt_tokens": 0, "completion_tokens": 0,
           "total_tokens": 0, "cost": 0.0}
    for meta in store.list():
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
async def resolve_approval(aid: str, body: ApprovalBody):
    from engine import approvals
    ok = approvals.resolve(aid, body.decision)
    if not ok:
        raise HTTPException(404, "Yêu cầu phê duyệt không tồn tại hoặc đã xử lý")
    return {"ok": True, "decision": body.decision}


@app.get("/api/models")
async def list_models():
    """Auto-sync model catalog from OpenRouter (cached 1 hour)."""
    if time.time() - _MODELS_CACHE["ts"] > 3600 or not _MODELS_CACHE["data"]:
        try:
            async with httpx.AsyncClient(timeout=25) as c:
                r = await c.get("https://openrouter.ai/api/v1/models")
                r.raise_for_status()
                items = r.json().get("data", [])
            data = []
            for m in items:
                pr = m.get("pricing") or {}
                try:
                    prompt_p = float(pr.get("prompt") or 0)
                    comp_p = float(pr.get("completion") or 0)
                except ValueError:
                    prompt_p = comp_p = 0.0
                data.append({
                    "id": m.get("id", ""),
                    "name": m.get("name", ""),
                    "context": m.get("context_length"),
                    "prompt_price": prompt_p,   # USD per token
                    "completion_price": comp_p,
                    "free": prompt_p == 0 and comp_p == 0,
                })
            data.sort(key=lambda x: x["id"])
            _MODELS_CACHE["data"] = data
            _MODELS_CACHE["ts"] = time.time()
        except Exception as e:
            if not _MODELS_CACHE["data"]:
                raise HTTPException(502, f"Không tải được danh sách model: {e}")
    return {"models": _MODELS_CACHE["data"], "count": len(_MODELS_CACHE["data"])}


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str):
    ok = store.delete(sid)
    return {"ok": ok}


# ---------------------------------------------------------------------------
# Chat streaming (SSE)
# ---------------------------------------------------------------------------
@app.post("/api/sessions/{sid}/chat")
async def chat(sid: str, body: ChatBody, request: Request):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Empty message")

    demo = config.get_api_key() is None
    model = body.model or None

    async def gen():
        try:
            agent = Agent(store, sid, model=model)
            source = send_demo(agent, text) if demo else agent.send(text)
            async for ev in source:
                if await request.is_disconnected():
                    return
                yield sse(ev)
        except Exception as e:
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
async def batch(body: BatchBody, request: Request):
    prompts = [p.strip() for p in body.prompts if p.strip()][:5]
    if not prompts:
        raise HTTPException(400, "Không có tác vụ nào")
    demo = config.get_api_key() is None

    async def gen():
        try:
            async for ev in run_batch(store, prompts, model=body.model, demo=demo):
                if await request.is_disconnected():
                    return
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "message": f"Lỗi batch: {e}"})
        yield sse({"type": "done"})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Workspace files
# ---------------------------------------------------------------------------
def _ws(sid: str) -> Path:
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    return store.workspace(sid)


def _safe_path(ws: Path, rel: str) -> Path:
    p = (ws / rel).resolve()
    if p != ws.resolve() and ws.resolve() not in p.parents:
        raise HTTPException(400, "Path escapes workspace")
    return p


@app.get("/api/workspace/tree")
async def workspace_tree(sid: str):
    ws = _ws(sid)

    def node(path: Path, depth: int) -> list[dict]:
        items = []
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except Exception:
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
async def read_workspace_file(sid: str, path: str):
    ws = _ws(sid)
    p = _safe_path(ws, path)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "File not found")
    raw = p.read_bytes()
    if b"\x00" in raw[:2000]:
        return {"path": path, "binary": True, "content": ""}
    return {"path": path, "binary": False, "content": raw.decode("utf-8", "replace")}


@app.put("/api/workspace/file")
async def save_workspace_file(sid: str, body: FileSaveBody):
    ws = _ws(sid)
    p = _safe_path(ws, body.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.content, encoding="utf-8")
    return {"ok": True, "path": body.path, "size": len(body.content)}


@app.delete("/api/workspace/file")
async def delete_workspace_file(sid: str, path: str):
    ws = _ws(sid)
    p = _safe_path(ws, path)
    if p.exists():
        p.unlink()
        return {"ok": True}
    raise HTTPException(404, "File not found")


@app.post("/api/workspace/upload")
async def upload_files(sid: str, files: list[UploadFile] = File(...)):
    ws = _ws(sid)
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
async def export_workspace(sid: str):
    ws = _ws(sid)
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
