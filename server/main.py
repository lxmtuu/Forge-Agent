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
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import config, llm, tools, guard    # noqa: E402
from engine.agent import Agent, send_demo, run_batch, run_battle   # noqa: E402
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
    mode: str = "agent"  # direct | agent | plan
    images: list[str] = []  # data URI image/png|jpeg|webp|gif (tối đa 4)


class BattleBody(BaseModel):
    prompt: str
    models: list[str] = []


class ExecBody(BaseModel):
    command: str


class OpenWorkspaceBody(BaseModel):
    path: str


class SettingsBody(BaseModel):
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
        "web_search": bool(cfg.get("web_search")),
        "allow_commands": cfg.get("allow_commands") or [],
        "deny_commands": cfg.get("deny_commands") or [],
        "active_profile": cfg.get("active_profile"),
        "profiles": sorted(config.list_profiles().keys()),
        "custom_base_url": config.get_base_url(),
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
    config.save_config(patch)
    return await health()


# ---------------------------------------------------------------------------
# Connectors OAuth 2.1 (C6) — flow chạy nền, web poll /status
# ---------------------------------------------------------------------------
class OAuthStartBody(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None


@app.get("/api/connectors/presets")
async def connector_presets():
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


@app.post("/api/connectors/{name}/oauth/start")
async def oauth_start(name: str, body: OAuthStartBody):
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
async def oauth_status(name: str):
    from engine import connectors as fc
    from engine import oauth as fo
    if (name or "").strip().lower() not in fc.PRESETS:
        raise HTTPException(404, "Unknown preset")
    return fo.flow_status(name.strip().lower())


@app.delete("/api/connectors/{name}/oauth")
async def oauth_disconnect(name: str):
    from engine import oauth as fo
    return {"ok": fo.forget(name)}


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
async def list_sessions(q: str = ""):
    return {"sessions": store.list(q=q)}


class RenameBody(BaseModel):
    title: str


@app.post("/api/sessions/{sid}/rename")
async def rename_session(sid: str, body: RenameBody):
    if not store.rename(sid, body.title):
        raise HTTPException(404, "Session not found")
    return {"ok": True, "title": body.title.strip()[:80]}


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


class ElicitBody(BaseModel):
    action: str = "cancel"          # accept | decline | cancel
    content: dict | None = None


@app.get("/api/elicitations")
async def pending_elicitations():
    """Danh sách elicitation MCP đang chờ người dùng (poll fallback cho UI)."""
    from engine import elicitations
    return {"pending": elicitations.snapshot()}


@app.post("/api/elicitation/{eid}")
async def resolve_elicitation(eid: str, body: ElicitBody):
    """Trả lời elicitation MCP (spec: action = accept|decline|cancel + content)."""
    from engine import elicitations
    ok = elicitations.resolve(eid, body.action, body.content)
    if not ok:
        raise HTTPException(404, "Elicitation không tồn tại hoặc đã xử lý")
    return {"ok": True, "action": body.action}


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
                raise HTTPException(502, f"Không tải được danh sách model: {e}") from e
    return {"models": _MODELS_CACHE["data"], "count": len(_MODELS_CACHE["data"])}


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str):
    ok = store.delete(sid)
    return {"ok": ok}


# ----------------------------------------------------- comfort: undo/compact/init
@app.post("/api/sessions/{sid}/undo")
async def undo_session(sid: str):
    """↩ Hoàn tác thay đổi gần nhất của agent trong workspace (checkpoint git nội bộ)."""
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    from engine import checkpoints
    if not checkpoints.available():
        raise HTTPException(409, "git không có mặt trên máy — checkpoint không khả dụng")
    ws = store.workspace(sid)
    res = await checkpoints.undo(checkpoints.key_for(ws), ws)
    return {"ok": bool(res.get("ok")), "message": str(res.get("message", ""))}


@app.post("/api/sessions/{sid}/compact")
async def compact_session_ep(sid: str, body: dict | None = None):
    """🧹 Nén hội thoại: LLM tóm tắt các tin nhắn cũ, giữ vài tin cuối."""
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    from engine.agent import compact_session
    agent = Agent(store, sid)
    res = await compact_session(agent, (body or {}).get("instructions") or "")
    return res


@app.post("/api/sessions/{sid}/init")
async def init_agents_ep(sid: str):
    """🚀 /init — phân tích workspace, sinh AGENTS.md (demo-mode khi chưa có key)."""
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    from engine.agent import init_agents_md
    agent = Agent(store, sid)
    res = await init_agents_md(agent)
    return res


@app.post("/api/sessions/{sid}/fork")
async def fork_session(sid: str):
    """🍴 Fork — nhân bản phiên: copy messages + workspace thành bản mới."""
    ns = store.fork(sid)
    if ns is None:
        raise HTTPException(404, "Session not found")
    return {"session": {"id": ns.id, "title": ns.title, "model": ns.model,
                        "message_count": len(ns.messages),
                        "updated_at": ns.updated_at}}


@app.get("/api/sessions/{sid}/context")
async def session_context(sid: str):
    """🧠 Mức dùng context của phiên (cho /context + footer web)."""
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    return Agent(store, sid).context_stats()


@app.get("/api/audit")
async def audit_tail(n: int = 120):
    """Nhật ký tool call (JSONL data/audit/) — n giới hạn 1..500."""
    from engine import auditlog
    return {"entries": auditlog.tail(max(1, min(n, 500)))}


@app.get("/api/doctor")
async def doctor_endpoint():
    """🩺 Chẩn đoán toàn hệ thống (python/git/key/model/MCP/LSP/dữ liệu…)."""
    from engine.diagnostics import doctor
    return await doctor(store)


@app.get("/api/sessions/{sid}/export")
async def export_session(sid: str):
    """⤓ /export — tải hội thoại dạng Markdown."""
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    from engine.export import to_markdown
    from urllib.parse import quote
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
async def chat(sid: str, body: ChatBody, request: Request):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Empty message")

    demo = config.get_api_key() is None
    model = body.model or None
    chat_mode = body.mode if body.mode in ("direct", "agent", "plan") else "agent"
    ws = store.workspace(sid)

    # /run <tên> <task> — custom agent từ .forge/agents/<name>.md (đè model/mode nếu có)
    from engine import agents as fagents
    agent_exp = fagents.expand(text, ws)
    if agent_exp is not None:
        text, ag_model, ag_mode = agent_exp
        if ag_model:
            model = ag_model
        if ag_mode:
            chat_mode = ag_mode
    # /audit [n] — xem nhật ký tool call, không cần LLM
    audit_synthetic: list[dict] | None = None
    if text == "/audit" or text.startswith("/audit "):
        from engine import auditlog
        a_arg = text[6:].strip()
        a_n = int(a_arg) if a_arg.isdigit() else 20
        audit_synthetic = [{"type": "assistant_message",
                            "content": auditlog.format_listing(a_n)}]
    # /connectors [add|auth|allow|deny|remove] — quản lý connector MCP, không cần LLM
    connectors_synthetic: list[dict] | None = None
    if text == "/connectors" or text.startswith("/connectors "):
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
                                    (connectors_synthetic
                                     if connectors_synthetic is not None else skills_synthetic))
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
            body = diff_text if len(diff_text) <= 12000 else diff_text[:12000] + "\n… (cắt ở 12KB)"
            synthetic = [{"type": "assistant_message",
                          "content": f"📄 **Diff — {label}:**\n\n```diff\n{body}\n```"}]
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
    text, attached = atfiles.expand_at_refs(text, ws)

    # ảnh đính kèm (multimodal) — content parts kiểu OpenAI/OpenRouter
    content = None
    images = [u for u in (body.images or []) if isinstance(u, str) and u.startswith("data:image/")][:4]
    if images and not demo:
        content = [{"type": "text", "text": text}] + [
            {"type": "image_url", "image_url": {"url": u}} for u in images]

    async def gen():
        try:
            if synthetic is not None:
                for ev in synthetic:
                    if await request.is_disconnected():
                        return
                    yield sse(ev)
                return
            agent = Agent(store, sid, model=model)
            if demo:
                demo_text = text
                if images:
                    demo_text += (f"\n\n(demo mode: bỏ qua {len(images)} ảnh đính kèm — "
                                  "nhập API key để dùng vision)")
                source = send_demo(agent, demo_text)
            else:
                source = agent.send(text, chat_mode=chat_mode, content=content)
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
            async for ev in run_batch(store, [{"prompt": p, "model": body.model or ""} for p in prompts],
                                      demo=demo):
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


@app.post("/api/battle")
async def battle(body: BattleBody, request: Request):
    """⚔ Cùng 1 prompt chạy trên nhiều model song song."""
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "Thiếu prompt")
    demo = config.get_api_key() is None

    async def gen():
        try:
            async for ev in run_battle(store, prompt, body.models, demo=demo):
                if await request.is_disconnected():
                    return
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "message": f"Lỗi battle: {e}"})
        yield sse({"type": "done"})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


@app.post("/api/workspace/exec")
async def workspace_exec(sid: str, body: ExecBody):
    """Terminal tích hợp: NGƯỜI DÙNG chạy lệnh trực tiếp trong workspace."""
    ws = _ws(sid)
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
async def workspace_open(sid: str, body: OpenWorkspaceBody):
    """Mở một thư mục dự án thật làm workspace. Yêu cầu env FORGE_ALLOW_OPEN=1."""
    import os
    if os.environ.get("FORGE_ALLOW_OPEN", "").strip() != "1":
        raise HTTPException(403,
                            "Tính năng mở dự án thật đang TẮT vì lý do an toàn. "
                            "Chạy server với biến môi trường FORGE_ALLOW_OPEN=1 để bật.")
    _ws(sid)  # ensure session exists
    try:
        target = store.open_workspace(sid, body.path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "workspace": str(target)}


@app.post("/api/workspace/close")
async def workspace_close(sid: str):
    store.close_workspace(sid)
    return {"ok": True}


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
