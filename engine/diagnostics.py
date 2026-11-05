"""Chẩn đoán toàn hệ thống — /doctor (dùng chung Web/TUI/CLI)."""
import os
import sys
from pathlib import Path

from . import checkpoints, config, lsp


async def doctor(store) -> dict:
    """Trả {checks: [{name, ok, detail}], summary, ok}."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    # nền tảng
    add("Python", sys.version_info >= (3, 10),
        f"{sys.version.split()[0]} ({sys.platform})")
    add("Nền tảng", True, f"{os.name} · cwd {Path.cwd()}")

    # key + model
    key = config.get_api_key()
    add("API key OpenRouter", key is not None,
        f"{config.mask_key(key)}" if key else "DEMO MODE — chưa có key (agent vẫn chạy kịch bản mẫu)")
    add("Model", True, config.get_model() + (f" · profile {config.load_config().get('active_profile')}"
                                             if config.load_config().get("active_profile") else ""))

    # checkpoints
    ck_on = config.load_config().get("checkpoints_enabled", True)
    add("git + checkpoints", checkpoints.available() and ck_on,
        f"git {'✓ ' + checkpoints.GIT if checkpoints.GIT else '✗ không có'}"
        f" · {'bật' if ck_on else 'TẮT (checkpoints_enabled=false)'}")

    # context budget
    acc = config.get_auto_compact_chars()
    add("Auto-compact", acc > 0,
        f"ngưỡng {acc:,} ký tự" if acc else "TẮT (FORGE_AUTO_COMPACT=0) — phiên dài sẽ tràn context")

    # LSP
    lsp_avail = {k: bool(v) for k, v in _lsp_map().items()}
    any_lsp = any(lsp_avail.values())
    add("LSP diagnostics", any_lsp,
        ", ".join(k for k, v in lsp_avail.items() if v) if any_lsp
        else "chưa cài pylsp/pyright/ts-server (tuỳ chọn — pip install \"python-lsp-server[pyflakes,pycodestyle]\")")

    # MCP
    try:
        from .mcp import manager as mm
        statuses = mm.status()
        ready = sum(1 for s in statuses if s["status"] == "ready")
        add("MCP servers", True, f"{ready}/{len(statuses)} sẵn sàng"
            + ("" if statuses else " (chưa cấu hình — data/mcp.json)"))
    except Exception as e:  # noqa: BLE001
        add("MCP servers", False, f"lỗi: {e}")

    # connectors (v0.17)
    try:
        from .connectors import has_auth, PRESETS
        from .mcp import load_servers
        cfgs = load_servers()
        n_token = sum(1 for c in cfgs if has_auth(c["name"]))
        add("Connectors", True, f"{len(cfgs)} cài · {n_token} có token"
            + ("" if cfgs else f" — preset sẵn: {', '.join(sorted(PRESETS))}"))
    except Exception as e:  # noqa: BLE001
        add("Connectors", False, f"lỗi: {e}")

    # sandbox / guard
    cfg = config.load_config()
    guards = []
    if cfg.get("block_network"):
        guards.append("block_network")
    if cfg.get("deny_commands"):
        guards.append(f"deny {len(cfg['deny_commands'])} mẫu")
    if cfg.get("allow_commands"):
        guards.append(f"allow {len(cfg['allow_commands'])} mẫu")
    add("Guard", True, f"mode {cfg.get('approval_mode', 'guarded')}"
        + (f" · {', '.join(guards)}" if guards else " · mặc định"))

    # dữ liệu
    try:
        data_mb = sum(f.stat().st_size for f in config.DATA_DIR.rglob("*") if f.is_file()) / 1e6
        n_sessions = len(store.list())
        add("Dữ liệu", data_mb < 500, f"{data_mb:.1f} MB · {n_sessions} phiên")
    except Exception as e:  # noqa: BLE001
        add("Dữ liệu", False, f"lỗi: {e}")

    # hook
    hook = cfg.get("on_file_change")
    add("Hook on_file_change", True, hook if hook else "chưa đặt (tuỳ chọn — formatter sau khi sửa file)")

    ok = all(c["ok"] for c in checks if c["name"] not in ("API key OpenRouter", "LSP diagnostics"))
    return {"checks": checks, "ok": ok,
            "summary": f"{sum(1 for c in checks if c['ok'])}/{len(checks)} mục OK"}


def _lsp_map() -> dict:
    import shutil
    return {
        "python": shutil.which("pylsp") is not None or shutil.which("pyright-langserver") is not None,
        "typescript": shutil.which("typescript-language-server") is not None,
    }
