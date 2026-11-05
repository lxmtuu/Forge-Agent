"""Lưu secret ngoài source/release + environment sạch cho subprocess.

- Provider key nằm ở data/provider-secrets.json (chmod 600 khi hệ điều hành hỗ trợ).
- Mật khẩu release KHÔNG lưu thô: PBKDF2-HMAC-SHA256 + salt ngẫu nhiên.
- sanitized_env() loại key LLM/admin khỏi tiến trình con. Secret trong `extra`
  được coi là chủ đích truyền (ví dụ cấu hình env riêng của một MCP server).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FORGE_DATA_DIR", ROOT / "data"))
PROVIDER_FILE = DATA_DIR / "provider-secrets.json"
AUTH_FILE = DATA_DIR / "release-auth.json"
PBKDF2_ITERATIONS = 240_000

# Không bao giờ cho shell/hook/LSP/git do agent gọi thừa kế các biến này.
SENSITIVE_ENV = frozenset({
    "OPENROUTER_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "FORGE_CUSTOM_API_KEY",
    "FORGE_ADMIN_TOKEN", "FORGE_SETUP_TOKEN",
})


def sanitized_env(extra: dict | None = None) -> dict[str, str]:
    """Môi trường cho child process: giữ PATH/system config nhưng bỏ LLM/admin keys."""
    env = {k: v for k, v in os.environ.items() if k not in SENSITIVE_ENV}
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_json_private(path: Path, data: dict) -> None:
    """Ghi nguyên tử + quyền tối thiểu; không in nội dung secret ra stdout/log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass  # Windows: ACL user-profile là lớp bảo vệ chính; chmod không đủ ý nghĩa.
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def read_provider_key(provider: str) -> str | None:
    value = _read_json(PROVIDER_FILE).get(str(provider).strip().lower())
    value = str(value or "").strip()
    return value or None


def write_provider_key(provider: str, key: str) -> None:
    provider = str(provider).strip().lower()
    key = str(key or "").strip()
    if provider not in {"openrouter", "google", "custom"}:
        raise ValueError("Provider secret không hợp lệ")
    if not 8 <= len(key) <= 512 or any(c.isspace() for c in key):
        raise ValueError("Key trống/quá ngắn hoặc chứa khoảng trắng")
    data = _read_json(PROVIDER_FILE)
    data[provider] = key
    _write_json_private(PROVIDER_FILE, data)


def has_release_auth() -> bool:
    return bool(os.environ.get("FORGE_ADMIN_TOKEN", "").strip()) or AUTH_FILE.is_file()


def write_release_password(password: str, username: str = "forge") -> None:
    username = str(username or "forge").strip()[:80]
    if username != "forge":
        raise ValueError("Release hiện dùng username cố định: forge")
    if len(password) < 16 or len(password) > 512:
        raise ValueError("Mật khẩu release cần ít nhất 16 ký tự")
    salt = os.urandom(24)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    _write_json_private(AUTH_FILE, {
        "version": 1,
        "username": username,
        "scheme": "pbkdf2_sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": salt.hex(),
        "hash": digest.hex(),
    })


def verify_release_password(username: str, password: str) -> bool:
    """Kiểm tra Basic/Bearer secret, constant-time ở bước so sánh."""
    env_token = os.environ.get("FORGE_ADMIN_TOKEN", "").strip()
    if env_token:
        return (username == "forge"
                and hmac.compare_digest(password.encode("utf-8"), env_token.encode("utf-8")))
    data = _read_json(AUTH_FILE)
    try:
        salt = bytes.fromhex(str(data["salt"]))
        expected = bytes.fromhex(str(data["hash"]))
        iterations = int(data["iterations"])
        if not 100_000 <= iterations <= 2_000_000 or data.get("scheme") != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        user_ok = hmac.compare_digest(str(username), str(data.get("username", "forge")))
        return user_ok and hmac.compare_digest(actual, expected)
    except (KeyError, ValueError, TypeError):
        return False
