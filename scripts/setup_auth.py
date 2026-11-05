"""Tạo user private-team hoặc cấu hình Google OIDC; secret chỉ nhập ẩn.

  python scripts/setup_auth.py --email admin@example.com --role admin
  python scripts/setup_auth.py --email member@example.com --google-only
  python scripts/setup_auth.py --google --client-id ... --public-url https://forge.example
  python scripts/setup_auth.py --check

Không có --password/--client-secret để tránh secret trong shell history/process list.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.auth import AuthStore


def _password(optional: bool = False) -> str | None:
    if optional:
        return None
    first = getpass.getpass("Password ≥16 ký tự (nhập ẩn): ")
    second = getpass.getpass("Nhập lại password: ")
    if first != second:
        raise ValueError("Hai lần nhập password không khớp")
    return first


def create_user(args) -> int:
    store = AuthStore()
    email = (args.email or input("Email user: ")).strip()
    if not email:
        raise ValueError("Email không được để trống")
    if store.get_by_email(email):
        raise ValueError("Email đã tồn tại; không tự reset password")
    role = args.role or ("admin" if not store.has_users() else "member")
    if not store.has_users() and role != "admin":
        raise ValueError("User đầu tiên phải là admin")
    if args.google_only and not store.google_config() and not store.has_users():
        raise ValueError("Google-only user đầu tiên cần cấu hình --google trước")
    password = _password(args.google_only)
    user = store.create_user(email, password, args.name, role, True)
    print(f"✓ Đã tạo {user.role}: {user.email} · auth={'Google' if args.google_only else 'password'}")
    print("  Password/client secret không được in hay ghi vào source.")
    return 0


def configure_google(args) -> int:
    store = AuthStore()
    old = store.google_config() or {}
    client_id = (args.client_id or old.get("client_id") or input("Google OAuth client ID: ")).strip()
    public_url = (args.public_url or old.get("public_url")
                  or input("Public URL (https://forge.example): ")).strip().rstrip("/")
    secret = getpass.getpass("Google client secret (nhập ẩn; Enter = giữ secret cũ): ").strip()
    secret = secret or old.get("client_secret", "")
    if not secret:
        raise ValueError("Thiếu Google client secret")
    store.save_google_config(client_id, secret, public_url)
    print("✓ Đã lưu Google login (chỉ openid email profile; KHÔNG có Gmail scope).")
    print(f"  Redirect URI: {public_url}/api/auth/google/callback")
    return 0


def check() -> int:
    store = AuthStore()
    users = store.list_users()
    cfg = store.google_config()
    print("── Forge private auth --check ──")
    print("Users       :", len(users), f"({sum(u.enabled for u in users)} active)")
    print("Admins      :", sum(u.role == "admin" and u.enabled for u in users))
    print("Google login:", "configured" if cfg else "chưa cấu hình")
    print("Public signup:", "enabled" if store.registration_enabled() else "disabled")
    print("Auth DB     :", store.db_path)
    return 0 if users and any(u.role == "admin" and u.enabled for u in users) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email")
    ap.add_argument("--name", default="")
    ap.add_argument("--role", choices=["admin", "member"])
    ap.add_argument("--google-only", action="store_true", help="Không đặt password; dùng Google đã được mời")
    ap.add_argument("--google", action="store_true", help="Cấu hình Google OIDC login")
    ap.add_argument("--client-id")
    ap.add_argument("--public-url")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.check:
            return check()
        if not sys.stdin.isatty():
            raise ValueError("Chạy trong terminal tương tác để secret không bị log/echo")
        if args.google:
            return configure_google(args)
        return create_user(args)
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
