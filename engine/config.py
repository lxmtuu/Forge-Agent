"""Central configuration: data dirs, API key, model selection."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FORGE_DATA_DIR", ROOT / "data"))
SESSIONS_DIR = DATA_DIR / "sessions"
WORKSPACES_DIR = DATA_DIR / "workspaces"
CONFIG_FILE = DATA_DIR / "config.json"

# Verified live on OpenRouter (Nov 2026)
DEFAULT_MODELS = [
    "anthropic/claude-sonnet-5.5",
    "openai/gpt-5.3-codex",
    "openai/gpt-5.6-luna",
    "google/gemini-3.8-flash",
    "deepseek/deepseek-v4.1-flash",
    "moonshotai/kimi-k2.7-code",
    "qwen/qwen3-coder-next",
]
FALLBACK_MODEL = "anthropic/claude-sonnet-5.5"


def ensure_dirs() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_config(patch: dict) -> dict:
    ensure_dirs()
    cfg = load_config()
    cfg.update(patch)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    try:
        CONFIG_FILE.chmod(0o600)
    except Exception:
        pass
    return cfg


def get_api_key() -> str | None:
    """Env var wins over saved config (12-factor style)."""
    env = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if env:
        return env
    return load_config().get("api_key") or None


def get_model() -> str:
    cfg_model = load_config().get("model", "").strip()
    return cfg_model or os.environ.get("FORGE_MODEL", "") or FALLBACK_MODEL


def mask_key(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 12:
        return key[:4] + "…" + key[-2:]
    return key[:8] + "…" + key[-4:]
