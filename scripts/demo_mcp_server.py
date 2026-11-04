#!/usr/bin/env python3
"""Demo MCP server (stdio, newline-delimited JSON-RPC 2.0) — để test Forge MCP client.

Tools:
  echo_text  — trả lại chuỗi được gửi
  now_time   — thời gian hiện tại
  add        — cộng 2 số
Run:  python scripts/demo_mcp_server.py
"""
import json
import sys
from datetime import datetime

TOOLS = [
    {
        "name": "echo_text",
        "description": "Echo back the given text (demo MCP tool).",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "text to echo"}},
            "required": ["text"],
        },
    },
    {
        "name": "now_time",
        "description": "Return the current date and time.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "add",
        "description": "Add two numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
]


def handle_call(name: str, args: dict) -> dict:
    if name == "echo_text":
        return {"content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}]}
    if name == "now_time":
        return {"content": [{"type": "text", "text": datetime.now().isoformat()}]}
    if name == "add":
        return {"content": [{"type": "text", "text": str(float(args.get("a", 0)) + float(args.get("b", 0)))}]}
    return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}


def main() -> None:
    for raw in sys.stdin:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        if method == "initialize":
            send(msg["id"], {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "demo-server", "version": "0.1.0"},
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send(msg["id"], {"tools": TOOLS})
        elif method == "tools/call":
            p = msg.get("params", {})
            send(msg["id"], handle_call(p.get("name", ""), p.get("arguments", {})))
        elif method and "id" in msg:
            send(msg["id"], {}, error={"code": -32601, "message": f"unknown method {method}"})


def send(rid, result, error=None):
    obj = {"jsonrpc": "2.0", "id": rid}
    obj["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
