"""Cấu hình provider + release auth trong terminal, không echo API key.

    python scripts/setup_keys.py
    python scripts/setup_keys.py --provider google --release
    python scripts/setup_keys.py --check

Không có tham số --key: cố ý tránh secret xuất hiện trong shell history/process list.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import config
from engine import secrets as secretstore


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def _secret(prompt: str, allow_empty: bool = False) -> str:
    value = getpass.getpass(prompt).strip()
    if not allow_empty and not value:
        raise ValueError("Key/mật khẩu không được để trống")
    return value


def check() -> int:
    provider = config.get_provider()
    key = config.get_active_api_key()
    print("── Forge secure setup --check ──")
    print("Provider :", provider)
    print("Model    :", config.get_model())
    print("LLM key  :", config.mask_key(key) if key else "CHƯA CÓ — demo mode")
    print("Release  :", "BẬT (Settings khóa + bắt buộc đăng nhập)" if config.is_release_mode() else "tắt")
    if config.is_release_mode():
        print("Release auth:", "đã cấu hình" if secretstore.has_release_auth() else "THIẾU")
    print("Secret file:", secretstore.PROVIDER_FILE)
    print("Auth file  :", secretstore.AUTH_FILE, "(chỉ hash, không có mật khẩu thô)")
    return 0 if config.has_llm_credentials() and (not config.is_release_mode() or secretstore.has_release_auth()) else 1


def run_setup(provider_arg: str | None = None, release_arg: bool = False) -> None:
    provider = provider_arg or _ask("Chọn provider: 1=OpenRouter · 2=Google Gemini · 3=Custom", "1")
    provider = {"1": "openrouter", "2": "google", "3": "custom"}.get(provider, provider.lower())
    if provider == "gemini":
        provider = "google"
    if provider not in {"openrouter", "google", "custom"}:
        raise ValueError("Provider phải là openrouter/google/custom")

    patch: dict = {"provider": provider, "custom_base_url": ""}
    if provider == "openrouter":
        key = _secret("OpenRouter API key (nhập ẩn, Enter khi xong): ")
        patch["api_key"] = key
        default_model = "anthropic/claude-sonnet-5.5"
    elif provider == "google":
        key = _secret("Google/Gemini API key (nhập ẩn, Enter khi xong): ")
        patch["google_api_key"] = key
        default_model = "gemini-3.8-flash"
    else:
        base = _ask("Base URL OpenAI-compatible", "http://localhost:11434/v1").rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise ValueError("Base URL phải bắt đầu http:// hoặc https://")
        patch["custom_base_url"] = base
        key = _secret("Custom API key (có thể Enter nếu Ollama không cần): ", allow_empty=True)
        if key:
            patch["custom_api_key"] = key
        default_model = "llama3.2"
    patch["model"] = _ask("Model", default_model)

    release = release_arg or config.is_release_mode()
    if not release_arg:
        answer = _ask("Bật release mode cho server dùng chung? (y/N)", "y" if release else "n").lower()
        release = answer in {"y", "yes", "1", "true"}
    patch["release_mode"] = release
    if release:
        if secretstore.AUTH_FILE.is_file():
            print("Đã có release password — Enter để giữ nguyên, hoặc nhập mật khẩu mới.")
            password = _secret("Mật khẩu release mới (nhập ẩn): ", allow_empty=True)
        else:
            password = _secret("Mật khẩu release ≥16 ký tự (nhập ẩn): ")
        if password:
            again = _secret("Nhập lại mật khẩu release: ")
            if password != again:
                raise ValueError("Hai lần nhập mật khẩu không khớp")
            secretstore.write_release_password(password)
        elif not secretstore.has_release_auth():
            raise ValueError("Release mode bắt buộc có mật khẩu")

    config.save_config(patch)  # tự tách key khỏi config.json
    print("\n✓ Đã lưu cấu hình an toàn. Key KHÔNG được in ra hay ghi vào source/git/zip.")
    print("  Provider:", provider, "· Model:", patch["model"])
    print("  Secret:", secretstore.PROVIDER_FILE)
    if release:
        print("  Release: BẬT · đăng nhập username `forge`, password vừa đặt (chỉ lưu hash).")
        print("  Khởi động lại server trước khi mở cho người dùng; bắt buộc HTTPS ở reverse proxy.")
    else:
        print("  Release: tắt (chỉ nên dùng trên máy cá nhân).")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", choices=["openrouter", "google", "custom"])
    ap.add_argument("--release", action="store_true", help="Bật auth + khóa Settings cho server dùng chung")
    ap.add_argument("--check", action="store_true", help="Chỉ xem trạng thái mask, không sửa gì")
    args = ap.parse_args(argv)
    try:
        if args.check:
            return check()
        if not sys.stdin.isatty():
            raise ValueError("Hãy chạy setup trong terminal tương tác để key không bị echo/log")
        run_setup(args.provider, args.release)
        return 0
    except (ValueError, EOFError, KeyboardInterrupt) as e:
        print(f"\n❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
