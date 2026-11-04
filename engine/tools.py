"""Built-in agent tools: file operations + shell, confined to a session workspace."""
import asyncio
import os
import re
from pathlib import Path

MAX_READ = 60_000          # chars returned to the model
MAX_CMD_OUTPUT = 12_000    # chars returned to the model
MAX_SEARCH_MATCHES = 100
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache",
             "dist", "build", ".next", ".mypy_cache", ".pytest_cache", "target"}

# ---------------------------------------------------------------------------
# OpenAI-style tool schema (sent to the LLM)
# ---------------------------------------------------------------------------
TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and folders in the workspace. Use it to explore "
                           "the project before reading files. Paths are relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative dir path, default '.'"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full text content of a file in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or fully overwrite an existing one. "
                           "Parent folders are created automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact snippet inside an existing file. "
                           "old_text must match exactly (including whitespace).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence (default false)"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Grep-like text search across all text files in the workspace "
                           "(case-insensitive). Returns path:line matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "description": "Optional sub-path to limit search"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command (bash) inside the workspace and return "
                           "combined stdout/stderr plus exit code. Use for builds, tests, "
                           "git, running scripts, installing deps, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_sec": {"type": "integer", "description": "Max seconds (default 30, max 120)"},
                },
                "required": ["command"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve(workspace: Path, rel: str) -> Path:
    """Resolve a user/LLM path and ensure it stays inside the workspace."""
    rel = (rel or ".").strip()
    p = (workspace / rel).resolve()
    root = workspace.resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"Path '{rel}' is outside the workspace")
    return p


def _iter_files(base: Path):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRS and not d.startswith(".")]
        for f in sorted(filenames):
            if f.startswith("."):
                continue
            yield Path(dirpath) / f


# ---------------------------------------------------------------------------
# Tool implementations (all sync + one async for shell)
# ---------------------------------------------------------------------------
def _list_dir(workspace: Path, args: dict) -> str:
    base = _resolve(workspace, args.get("path", "."))
    if not base.exists():
        return f"Error: path not found: {args.get('path')}"
    if base.is_file():
        return f"{args.get('path')} (file)"
    lines: list[str] = []
    count = 0
    for f in _iter_files(base):
        rel = f.relative_to(base)
        depth = len(rel.parts) - 1
        if depth > 3:
            continue
        lines.append("  " * depth + ("📄 " if True else "") + str(rel))
        count += 1
        if count >= 400:
            lines.append("… (truncated at 400 entries)")
            break
    if not lines:
        return "(empty workspace)"
    return "\n".join(lines)


def _read_file(workspace: Path, args: dict) -> str:
    p = _resolve(workspace, args["path"])
    if not p.exists() or not p.is_file():
        return f"Error: file not found: {args['path']}"
    raw = p.read_bytes()
    if b"\x00" in raw[:2000]:
        return f"Error: '{args['path']}' looks binary; cannot display."
    text = raw.decode("utf-8", "replace")
    if len(text) > MAX_READ:
        return text[:MAX_READ] + f"\n… (truncated, {len(text) - MAX_READ} more chars)"
    return text if text else "(empty file)"


def _write_file(workspace: Path, args: dict) -> str:
    p = _resolve(workspace, args["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args.get("content", ""), encoding="utf-8")
    return f"Wrote {len(args.get('content', ''))} chars to {args['path']}"


def _edit_file(workspace: Path, args: dict) -> str:
    p = _resolve(workspace, args["path"])
    if not p.exists() or not p.is_file():
        return f"Error: file not found: {args['path']}"
    text = p.read_text(encoding="utf-8", errors="replace")
    old, new = args["old_text"], args["new_text"]
    n = text.count(old)
    if n == 0:
        return ("Error: old_text not found in file. Make sure it matches exactly "
                "(whitespace/newlines). Read the file again first.")
    if args.get("replace_all"):
        text = text.replace(old, new)
        p.write_text(text, encoding="utf-8")
        return f"Replaced {n} occurrence(s) in {args['path']}"
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    return f"Edited {args['path']} (1 occurrence replaced)"


def _search_files(workspace: Path, args: dict) -> str:
    query = args["query"].lower()
    base = _resolve(workspace, args.get("path", "."))
    matches: list[str] = []
    for f in _iter_files(base if base.is_dir() else base.parent):
        try:
            if f.stat().st_size > 1_000_000:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if query in line.lower():
                    rel = f.relative_to(workspace)
                    matches.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        matches.append(f"… (stopped at {MAX_SEARCH_MATCHES} matches)")
                        return "\n".join(matches)
        except Exception:
            continue
    return "\n".join(matches) if matches else f"No matches for '{args['query']}'"


async def _run_command(workspace: Path, args: dict, override: bool = False) -> str:
    from . import config, guard

    cmd = args["command"]
    approval = config.load_config().get("approval_mode", "guarded")
    verdict = guard.assess_command(cmd)
    if verdict["level"] == "danger" and approval != "auto" and not override:
        return guard.guard_message(cmd, verdict)
    if config.load_config().get("docker_sandbox") and guard.DOCKER_AVAILABLE:
        cmd = guard.docker_wrap(cmd)
    timeout = min(int(args.get("timeout_sec") or 30), 120)
    env = {**os.environ, "TERM": "dumb", "NO_COLOR": "1"}
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(workspace), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=env,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Error: command timed out after {timeout}s: {cmd}"
        text = out.decode("utf-8", "replace")
        if len(text) > MAX_CMD_OUTPUT:
            text = text[:MAX_CMD_OUTPUT] + f"\n… (truncated, exit={proc.returncode})"
        return f"exit={proc.returncode}\n{text}" if text else f"exit={proc.returncode} (no output)"
    except Exception as e:
        return f"Error running command: {e}"


_IMPL = {
    "list_dir": _list_dir,
    "read_file": _read_file,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "search_files": _search_files,
}


async def execute_tool(name: str, args: dict, workspace: Path, override: bool = False) -> dict:
    """Run one tool. Returns {"ok": bool, "output": str}.

    override=True: user explicitly approved this exact command interactively.
    """
    try:
        if name == "run_command":
            output = await _run_command(workspace, args, override=override)
            ok = not output.startswith(("Error", "BLOCKED"))
        elif name in _IMPL:
            output = _IMPL[name](workspace, args)
            ok = not output.startswith(("Error", "BLOCKED"))
        else:
            output, ok = f"Error: unknown tool '{name}'", False
    except Exception as e:
        output, ok = f"Error: {e}", False
    return {"ok": ok, "output": output}
