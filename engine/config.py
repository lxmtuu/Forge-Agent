"""Central configuration: data dirs, API key, model selection."""
import json
import os
from pathlib import Path

from . import secrets as secretstore

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
    # free options (không cần credit)
    "openrouter/free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]
FALLBACK_MODEL = "anthropic/claude-sonnet-5.5"


def get_auto_commit() -> bool:
    """B1: tự git-commit workspace sau mỗi lượt agent (mặc định TẮT — opt-in)."""
    return bool(load_config().get("auto_commit", False))


def get_reasoning_effort() -> str:
    """D3: effort suy luận ('low'|'medium'|'high') — '' = không gửi field reasoning."""
    v = (load_config().get("reasoning_effort") or "").strip().lower()
    return v if v in ("low", "medium", "high") else ""


def get_max_tokens() -> int:
    """Max output tokens per LLM call. Lower = cheaper pre-auth on pay-as-you-go."""
    try:
        v = load_config().get("max_tokens")
        v = int(v) if v is not None else 0
    except Exception:
        v = 0
    if not v:
        try:
            v = int(os.environ.get("FORGE_MAX_TOKENS", "0"))
        except ValueError:
            v = 0
    return v if 256 <= v <= 65536 else 16384


def get_auto_compact_chars() -> int:
    """Tổng ký tự hội thoại tối đa trước khi auto-compact (~4 chars ≈ 1 token).
    0 = tắt. Mặc định 150.000 (~37k tokens)."""
    try:
        v = int(load_config().get("auto_compact_chars", 0) or 0)
    except Exception:
        v = 0
    if not v:
        try:
            v = int(os.environ.get("FORGE_AUTO_COMPACT", "150000"))
        except ValueError:
            v = 150000
    return max(0, v)


def ensure_dirs() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return apply_profile(cfg)


def list_profiles() -> dict:
    """Các profile định nghĩa trong config.json: {"profiles": {"safe": {...}}}."""
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    p = raw.get("profiles")
    return p if isinstance(p, dict) else {}


def apply_profile(cfg: dict) -> dict:
    """Codex-style profiles: env FORGE_PROFILE chọn 1 preset trong
    config.json["profiles"] → merge đè lên config gốc (không ghi đè file)."""
    name = os.environ.get("FORGE_PROFILE", "").strip()
    if not name:
        return cfg
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict) or name not in profiles:
        return cfg
    overlay = profiles[name]
    merged = {k: v for k, v in cfg.items() if k != "profiles"}
    if isinstance(overlay, dict):
        merged.update(overlay)
    merged["active_profile"] = name
    return merged


def save_config(patch: dict) -> dict:
    """Lưu cấu hình KHÔNG-secret; key được tách sang provider-secrets.json.

    Giữ tương thích: các caller cũ vẫn truyền api_key/custom_api_key. Nếu config
    cũ còn key thô, lần save kế tiếp di chuyển key đó ra khỏi config.json.
    """
    ensure_dirs()
    patch = dict(patch)
    secret_fields = {"api_key": "openrouter", "google_api_key": "google",
                     "custom_api_key": "custom"}
    provided: dict[str, str] = {}
    for field, provider in secret_fields.items():
        value = str(patch.pop(field, "") or "").strip()
        if value:
            provided[provider] = value
    cfg = load_config()
    # Migrate legacy TRƯỚC: key operator vừa nhập phải thắng key cũ trong config.
    for field, provider in secret_fields.items():
        legacy = str(cfg.pop(field, "") or "").strip()
        if legacy:
            secretstore.write_provider_key(provider, legacy)
    for provider, value in provided.items():
        secretstore.write_provider_key(provider, value)
    cfg.update(patch)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        CONFIG_FILE.chmod(0o600)
    except Exception:
        pass
    return cfg


def get_base_url() -> str:
    """Base URL OpenAI-compatible tuỳ chỉnh (Ollama/LM Studio/vLLM…). '' = dùng OpenRouter."""
    return (load_config().get("custom_base_url") or "").strip().rstrip("/")


def get_custom_api_key() -> str:
    """API key cho base URL tuỳ chỉnh (Ollama không cần)."""
    env = os.environ.get("FORGE_CUSTOM_API_KEY", "").strip()
    return (env or secretstore.read_provider_key("custom")
            or (load_config().get("custom_api_key") or "").strip())


def get_api_key() -> str | None:
    """OpenRouter: env → secret file → config legacy (để tương thích bản cũ)."""
    env = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if env:
        return env
    return secretstore.read_provider_key("openrouter") or load_config().get("api_key") or None


def get_google_api_key() -> str | None:
    """Gemini: GOOGLE_API_KEY/GEMINI_API_KEY → secret file → config legacy."""
    env = (os.environ.get("GOOGLE_API_KEY", "").strip()
           or os.environ.get("GEMINI_API_KEY", "").strip())
    if env:
        return env
    return secretstore.read_provider_key("google") or load_config().get("google_api_key") or None


def get_provider() -> str:
    """openrouter | google | custom. `gemini` là alias của google."""
    raw = (os.environ.get("FORGE_PROVIDER", "").strip().lower()
           or str(load_config().get("provider") or "").strip().lower())
    if raw == "gemini":
        raw = "google"
    if raw in {"openrouter", "google", "custom"}:
        return raw
    return "custom" if get_base_url() else "openrouter"


def get_active_api_key() -> str | None:
    """Key của provider đang active; custom local có thể hợp lệ với None."""
    provider = get_provider()
    if provider == "google":
        return get_google_api_key()
    if provider == "custom":
        return get_custom_api_key()
    return get_api_key()


def provider_secret_field(provider: str | None = None) -> str:
    """Tên field tương thích để save_config() route key vào đúng secret store."""
    return {"google": "google_api_key", "custom": "custom_api_key"}.get(
        provider or get_provider(), "api_key")


def has_llm_credentials() -> bool:
    """Có thể gọi LLM thật? Custom local không bắt buộc key; Google dùng key riêng."""
    provider = get_provider()
    if provider == "custom":
        return bool(get_base_url())
    if provider == "google":
        return bool(get_google_api_key())
    return bool(get_api_key())


def has_provider_credentials(provider: str) -> bool:
    """Credential cho đúng provider của một model request, không theo active global."""
    if provider == "custom":
        return bool(get_base_url())
    if provider == "google":
        return bool(get_google_api_key())
    return bool(get_api_key())


def has_any_llm_credentials() -> bool:
    return bool(get_api_key() or get_google_api_key() or get_base_url())


def is_release_mode() -> bool:
    """Khóa Settings + bắt buộc auth cho server dùng chung; chỉ terminal/env đổi được."""
    env = os.environ.get("FORGE_RELEASE_MODE", "").strip().lower()
    if env:
        return env in {"1", "true", "yes", "on"}
    return bool(load_config().get("release_mode", False))


def get_rate_limit_per_min() -> int:
    """Số request LLM tối đa/phút cho một user+IP ở release mode."""
    raw = (os.environ.get("FORGE_RATE_LIMIT_PER_MIN", "").strip()
           or str(load_config().get("rate_limit_per_min", 20)))
    try:
        return min(max(int(raw), 1), 1000)
    except (TypeError, ValueError):
        return 20


def get_model() -> str:
    cfg = load_config()
    cfg_model = cfg.get("model", "").strip()
    env_model = os.environ.get("FORGE_MODEL", "").strip()
    if cfg_model or env_model:
        return cfg_model or env_model
    provider = (os.environ.get("FORGE_PROVIDER", "").strip().lower()
                or str(cfg.get("provider") or "").strip().lower())
    return "gemini-3.8-flash" if provider in {"google", "gemini"} else FALLBACK_MODEL


def set_profile(name: str) -> bool:
    """Chọn profile cho tiến trình hiện tại (CLI/TUI --profile, lệnh /profile)."""
    name = (name or "").strip()
    if not name:
        os.environ.pop("FORGE_PROFILE", None)
        return True
    if name not in list_profiles():
        return False
    os.environ["FORGE_PROFILE"] = name
    return True


def mask_key(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 12:
        return key[:4] + "…" + key[-2:]
    return key[:8] + "…" + key[-4:]
