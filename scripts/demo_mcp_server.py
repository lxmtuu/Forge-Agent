#!/usr/bin/env python3
"""Demo MCP server (stdio, newline-delimited JSON-RPC 2.0) — để test Forge MCP client.

Tools:
  echo_text  — trả lại chuỗi được gửi
  now_time   — thời gian hiện tại
  add        — cộng 2 số
  ask_preference — demo elicitation: hỏi người dùng giữa chừng call
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
    {
        "name": "ask_preference",
        "description": "Demo MCP elicitation: hỏi người dùng lựa chọn giữa chừng tool call.",
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "chủ đề cần hỏi"}},
            "required": ["topic"],
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
    if name == "ask_preference":
        topic = args.get("topic", "?")
        # elicitation/create (form mode) — gửi request giữa chừng, chờ client trả lời
        rid = 9001
        sys.stdout.write(json.dumps({
            "jsonrpc": "2.0", "id": rid, "method": "elicitation/create",
            "params": {
                "mode": "form",
                "message": f"Server demo cần biết lựa chọn của bạn về: {topic}?",
                "requestedSchema": {
                    "type": "object",
                    "properties": {
                        "choice": {"type": "string", "description": "phương án bạn chọn"},
                        "urgent": {"type": "boolean", "description": "có gấp không"},
                    },
                    "required": ["choice"],
                },
            },
        }) + "\n")
        sys.stdout.flush()
        # đọc cho tới khi nhận response đúng id (bỏ qua notification)
        for raw in sys.stdin:
            try:
                resp = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if resp.get("id") != rid or "method" in resp:
                continue
            result = resp.get("result") or {}
            action = result.get("action", "cancel")
            content = result.get("content") or {}
            if action == "accept":
                return {"content": [{"type": "text",
                                     "text": f"Người dùng chọn «{content.get('choice', '?')}»"
                                             f" (urgent={content.get('urgent', False)}) về {topic}."}]}
            if action == "decline":
                return {"content": [{"type": "text", "text": f"Người dùng TỪ CHỐI trả lời về {topic}."}],
                        "isError": False}
            return {"content": [{"type": "text", "text": f"Người dùng đã đóng hộp thoại ({action})."}],
                    "isError": False}
        return {"content": [{"type": "text", "text": "client ngắt kết nối"}], "isError": True}
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
