"""Minimal MCP (Model Context Protocol) stdio client.

Connects to MCP servers (subprocess, newline-delimited JSON-RPC 2.0), lists their
tools, exposes them to the LLM as namespaced OpenAI-style functions:
    mcp_<server>_<tool>
Config lives in data/mcp.json:
    {"servers": [{"name": "fs", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."], "enabled": true}]}
"""
import asyncio
import json
import re
import time
from pathlib import Path

from . import config

PROTOCOL_VERSION = "2024-11-05"
INIT_TIMEOUT = 20.0
CALL_TIMEOUT = 120.0


class McpError(Exception):
    pass


def _config_path() -> Path:
    return config.DATA_DIR / "mcp.json"


def load_servers() -> list[dict]:
    try:
        return json.loads(_config_path().read_text()).get("servers", [])
    except Exception:
        return []


def save_servers(servers: list[dict]) -> None:
    config.ensure_dirs()
    _config_path().write_text(json.dumps({"servers": servers}, indent=2, ensure_ascii=False))


def _sanitize_name(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)[:32] or "srv"


class McpServer:
    """One MCP server subprocess with lazy start + cached tool list."""

    def __init__(self, name: str, command: str, args: list[str], env: dict | None = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.proc: asyncio.subprocess.Process | None = None
        self.tools: list[dict] = []          # raw MCP tools
        self.status = "stopped"              # stopped|starting|ready|error
        self.error: str | None = None
        self._next_id = 10
        self._lock = asyncio.Lock()
        self.started_at = 0.0

    # -- low-level JSON-RPC over stdio ------------------------------------
    async def _send(self, obj: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        await self.proc.stdin.drain()

    async def _recv(self, want_id: int, timeout: float) -> dict:
        assert self.proc and self.proc.stdout
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise McpError(f"MCP '{self.name}': timeout chờ response id={want_id}")
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=remaining)
            if not line:
                raise McpError(f"MCP '{self.name}': tiến trình đã thoát")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == want_id:
                if "error" in msg:
                    raise McpError(f"MCP '{self.name}': {msg['error']}")
                return msg.get("result", {})

    async def _request(self, method: str, params: dict, timeout: float) -> dict:
        self._next_id += 1
        rid = self._next_id
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return await self._recv(rid, timeout)

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        async with self._lock:
            if self.status == "ready":
                return
            self.status = "starting"
            try:
                env = {**__import__("os").environ, **self.env}
                self.proc = await asyncio.create_subprocess_exec(
                    self.command, *self.args,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, env=env,
                )
                init = await self._request("initialize", {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "forge-agent", "version": "0.1.0"},
                }, INIT_TIMEOUT)
                srv = (init.get("serverInfo") or {}).get("name", "?")
                await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
                result = await self._request("tools/list", {}, INIT_TIMEOUT)
                self.tools = result.get("tools", [])
                self.status = "ready"
                self.error = None
                self.started_at = time.time()
                print(f"[mcp] '{self.name}' ready ({srv}): {len(self.tools)} tools")
            except Exception as e:
                self.status = "error"
                self.error = str(e)
                await self.stop_quiet()
                print(f"[mcp] '{self.name}' error: {e}")

    async def stop_quiet(self) -> None:
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass
            self.proc = None
        if self.status != "error":
            self.status = "stopped"
        self.tools = []

    async def refresh(self) -> None:
        await self.stop_quiet()
        self.status = "stopped"
        await self.start()

    async def call(self, tool: str, args: dict) -> dict:
        if self.status != "ready":
            await self.start()
        if self.status != "ready":
            raise McpError(f"MCP server '{self.name}' không khởi động được: {self.error}")
        result = await self._request("tools/call", {"name": tool, "arguments": args}, CALL_TIMEOUT)
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        return {"ok": not result.get("isError", False), "output": "\n".join(texts) or "(no content)"}


class McpManager:
    """Global registry: lazy-start servers, expose namespaced tool specs."""

    def __init__(self) -> None:
        self._servers: dict[str, McpServer] = {}
        self._lock = asyncio.Lock()

    def _build(self, cfg: dict) -> McpServer:
        key = _sanitize_name(cfg["name"])
        if key not in self._servers:
            self._servers[key] = McpServer(cfg["name"], cfg["command"], cfg.get("args", []), cfg.get("env"))
        return self._servers[key]

    async def get_tool_specs(self) -> tuple[list[dict], dict[str, tuple[McpServer, str]]]:
        """Returns (OpenAI tool specs, routing map nsname -> (server, tool))."""
        specs: list[dict] = []
        routing: dict[str, tuple[McpServer, str]] = {}
        for cfg in load_servers():
            if not cfg.get("enabled", True):
                continue
            srv = self._build(cfg)
            await srv.start()
            for t in srv.tools:
                ns = f"mcp_{_sanitize_name(srv.name)}_{_sanitize_name(t['name'])}"[:64]
                params = t.get("inputSchema") or {"type": "object", "properties": {}}
                # keep schema small: strip heavy keys some servers add
                params = {k: params.get(k) for k in ("type", "properties", "required") if params.get(k)}
                specs.append({
                    "type": "function",
                    "function": {
                        "name": ns,
                        "description": f"[MCP:{srv.name}] {t.get('description') or t['name']}"[:500],
                        "parameters": params,
                    },
                })
                routing[ns] = (srv, t["name"])
        return specs, routing

    async def call_namespaced(self, routing: dict, ns_name: str, args: dict) -> dict:
        if ns_name not in routing:
            return {"ok": False, "output": f"Error: unknown MCP tool '{ns_name}'"}
        srv, tool = routing[ns_name]
        try:
            return await srv.call(tool, args)
        except McpError as e:
            return {"ok": False, "output": f"Error: {e}"}

    async def refresh(self, name: str | None = None) -> None:
        for cfg in load_servers():
            if name and cfg["name"] != name:
                continue
            srv = self._build(cfg)
            await srv.refresh()

    def status(self) -> list[dict]:
        out = []
        for cfg in load_servers():
            key = _sanitize_name(cfg["name"])
            srv = self._servers.get(key)
            out.append({
                "name": cfg["name"], "command": cfg["command"], "args": cfg.get("args", []),
                "enabled": cfg.get("enabled", True),
                "status": srv.status if srv else "stopped",
                "error": srv.error if srv else None,
                "tools": [t["name"] for t in srv.tools] if srv else [],
            })
        return out


manager = McpManager()
