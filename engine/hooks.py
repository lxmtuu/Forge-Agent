"""Hooks — lifecycle scripts kiểu Claude Code.

Config (config.json hoặc .forge/config.json của workspace):
  "hooks": {
    "pre_tool_use":  [{"command": "...", "matcher": "write_file|edit_file"}],
    "post_tool_use": [{"command": "...", "matcher": "*"}],
    "session_start": [{"command": "..."}],
    "on_file_change": "black ."          # dạng cũ v0.10 — vẫn hoạt động
  }

Hợp đồng (theo Claude Code):
- Hook nhận JSON trên stdin: {session_id, hook_event_name, tool_name, tool_input, workspace}
- exit 0  → tiếp tục
- exit 2  → CHẶN (chỉ pre_tool_use) — stderr là lý do đưa cho LLM
- exit khác → lỗi không chặn, stderr bỏ qua
- post_tool_use: stderr/stdout được nối vào kết quả tool cho LLM thấy
- session_start: stdout được nối vào system prompt (context bổ sung)
- matcher: regex tên tool ("write_file|edit_file", hoặc bỏ/rỗng = khớp tất cả)
"""
import asyncio
import json
import re
from pathlib import Path

from . import config

TIMEOUT = 30.0


def _hook_cfgs(workspace: Path, event: str) -> list[dict]:
    ws_cfg = Path(workspace) / ".forge" / "config.json"
    cfg: dict = {}
    try:
        if ws_cfg.is_file():
            cfg = json.loads(ws_cfg.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — config lỗi → không có hook, không chết tool
        cfg = {}
    hooks = cfg.get("hooks") or config.load_config().get("hooks") or {}
    items = hooks.get(event) or []
    if isinstance(items, str):
        items = [{"command": items}]
    out = []
    for it in items:
        if isinstance(it, str):
            it = {"command": it}
        if isinstance(it, dict) and it.get("command"):
            out.append(it)
    # tương thích v0.10: on_file_change dạng chuỗi
    if event == "post_tool_use":
        legacy = (cfg.get("on_file_change") or config.load_config().get("on_file_change"))
        if legacy:
            out.append({"command": legacy, "matcher": "write_file|edit_file", "_legacy_env": True})
    return out


async def run_event(workspace: Path, sid: str, event: str,
                    extra: dict | None = None) -> list[dict]:
    """C1 (v0.32): chạy mọi hook của event TỔNG QUÁT (user_prompt_submit/stop/
    pre_compact/notification). Trả [{command, rc, out, err}] — CALLER quyết nghĩa
    exit 2 (user_prompt_submit/pre_compact = chặn; stop/notification = bỏ qua rc)."""
    results = []
    payload = {"session_id": sid, "hook_event_name": event,
               "workspace": str(workspace), **(extra or {})}
    for entry in _hook_cfgs(workspace, event):
        res = await _run_cmd(str(entry.get("command")), payload, workspace)
        results.append({"command": str(entry.get("command")),
                        "rc": res.get("code", 1),
                        "out": res.get("out", ""), "err": res.get("err", "")})
    return results


def _matched(entry: dict, tool_name: str) -> bool:
    matcher = str(entry.get("matcher", "") or "").strip()
    if not matcher or matcher == "*":
        return True
    try:
        return re.search(matcher, tool_name or "") is not None
    except re.error:
        return tool_name == matcher


async def _run_cmd(command: str, payload: dict, workspace: Path, env_extra: dict | None = None):
    import os
    env = {**os.environ, **(env_extra or {}),
           "FORGE_WORKSPACE": str(workspace)}
    try:
        proc = await asyncio.create_subprocess_shell(
            command, cwd=str(workspace), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(json.dumps(payload, ensure_ascii=False).encode()), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return {"code": 1, "out": "", "err": f"hook timeout {TIMEOUT}s"}
        return {"code": proc.returncode or 0,
                "out": out.decode("utf-8", "replace").strip()[:1200],
                "err": err.decode("utf-8", "replace").strip()[:600]}
    except Exception as e:  # noqa: BLE001 — hook lỗi không được làm hỏng tool
        return {"code": 1, "out": "", "err": f"hook error: {e}"}


async def pre_tool_use(workspace: Path, sid: str, tool_name: str, tool_input: dict) -> dict | None:
    """Trả {"blocked": True, "reason": ...} nếu bị chặn, ngược lại None."""
    for entry in _hook_cfgs(workspace, "pre_tool_use"):
        if not _matched(entry, tool_name):
            continue
        payload = {"session_id": sid, "hook_event_name": "PreToolUse",
                   "tool_name": tool_name, "tool_input": tool_input,
                   "workspace": str(workspace)}
        r = await _run_cmd(entry["command"], payload, workspace)
        if r["code"] == 2:
            return {"blocked": True,
                    "reason": r["err"] or r["out"] or "bị chặn bởi hook pre_tool_use (exit 2)"}
    return None


async def post_tool_use(workspace: Path, sid: str, tool_name: str, tool_input: dict,
                        tool_output: str, env_extra: dict | None = None) -> str:
    """Trả chuỗi bổ sung nối vào tool output (có thể rỗng)."""
    extras: list[str] = []
    for entry in _hook_cfgs(workspace, "post_tool_use"):
        if not _matched(entry, tool_name):
            continue
        if entry.get("_legacy_env"):
            continue  # on_file_change đã chạy trong tools.execute_tool
        payload = {"session_id": sid, "hook_event_name": "PostToolUse",
                   "tool_name": tool_name, "tool_input": tool_input,
                   "tool_output": tool_output[:4000], "workspace": str(workspace)}
        r = await _run_cmd(entry["command"], payload, workspace, env_extra)
        msg = r["err"] or r["out"]
        if msg:
            extras.append(f"🔗 Hook PostToolUse (exit {r['code']}): {msg}")
    return "\n".join(extras)


_SS_CACHE: dict[str, str] = {}


async def session_start_cache(workspace: Path, sid: str) -> str:
    """session_start chạy 1 lần mỗi (sid) mỗi tiến trình; kết quả nối vào system prompt."""
    if sid in _SS_CACHE:
        return _SS_CACHE[sid]
    out = await session_start(workspace, sid)
    _SS_CACHE[sid] = out
    return out


async def session_start(workspace: Path, sid: str) -> str:
    """stdout của hook → context bổ sung nối vào system prompt (chạy 1 lần/sid)."""
    parts: list[str] = []
    for entry in _hook_cfgs(workspace, "session_start"):
        r = await _run_cmd(entry["command"], {
            "session_id": sid, "hook_event_name": "SessionStart", "workspace": str(workspace),
        }, workspace)
        if r["out"]:
            parts.append(r["out"])
    return "\n".join(parts)[:2000]
