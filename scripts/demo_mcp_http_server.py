#!/usr/bin/env python3
"""Demo MCP server over Streamable-HTTP transport — để test Forge MCP HTTP client.

Run:  python -m uvicorn scripts.demo_mcp_http_server:app --port 8931
Endpoint: POST /mcp  (JSON-RPC; trả JSON hoặc SSE tùy header Accept của client)
"""
import json
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Demo MCP HTTP Server")
SESSIONS: set[str] = set()

TOOLS = [
    {
        "name": "weather_report",
        "description": "Return a fake weather report for a city (demo).",
        "inputSchema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
    {
        "name": "uuid4_new",
        "description": "Return a fresh random UUID string (demo).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _call(name: str, args: dict) -> dict:
    if name == "weather_report":
        return {"content": [{"type": "text",
                             "text": f"Thời tiết {args.get('city', '?')}: 28°C, nắng, độ ẩm 70% (demo)"}]}
    if name == "uuid4_new":
        import uuid
        return {"content": [{"type": "text", "text": str(uuid.uuid4())}]}
    return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}


def _rpc_response(rid, result=None, error=None) -> dict:
    obj: dict = {"jsonrpc": "2.0", "id": rid}
    obj["error" if error else "result"] = error or result
    return obj


@app.post("/mcp")
async def mcp_endpoint(req: Request):
    try:
        msg = await req.json()
    except Exception:
        return JSONResponse(_rpc_response(None, error={"code": -32700, "message": "parse error"}), status_code=400)

    method = msg.get("method")
    rid = msg.get("id")
    session = req.headers.get("mcp-session-id")
    if session and session not in SESSIONS:
        return JSONResponse({"error": "unknown session"}, status_code=404)

    # notifications (no id) → 202 accepted
    if method == "notifications/initialized":
        return JSONResponse({"ok": True}, status_code=202)

    if method == "initialize":
        new_sid = "sess-" + str(abs(hash(str(req.client) + method)) % 10 ** 8)
        SESSIONS.add(new_sid)
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "demo-http-server", "version": "0.1.0"},
        }
        resp = JSONResponse(_rpc_response(rid, result))
        resp.headers["Mcp-Session-Id"] = new_sid
        return resp

    if method == "tools/list":
        return _rpc_response(rid, {"tools": TOOLS})
    if method == "tools/call":
        p = msg.get("params", {})
        return _rpc_response(rid, _call(p.get("name", ""), p.get("arguments", {})))
    return JSONResponse(_rpc_response(rid, error={"code": -32601, "message": f"unknown method {method}"}))
