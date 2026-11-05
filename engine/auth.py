"""Private-team identity, browser sessions and OAuth transaction storage.

SQLite phù hợp một VPS. Mật khẩu dùng PBKDF2 có salt; browser chỉ giữ session token
trong HttpOnly cookie, DB chỉ giữ SHA-256(token). Không có public registration.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config
from .secrets import make_password_record, verify_password_record

SESSION_COOKIE = "forge_session"
OAUTH_COOKIE = "forge_oauth"
CSRF_COOKIE = "forge_csrf"
SESSION_TTL = 8 * 3600
OAUTH_TTL = 10 * 60
EMAIL_RE = re.compile(r"^[^\s@<>]{1,128}@[^\s@<>]{1,190}$")
_DUMMY_PASSWORD_RECORD = make_password_record(secrets.token_urlsafe(32))


def normalize_email(email: str) -> str:
    value = email.strip().casefold()
    if len(value) > 254 or not EMAIL_RE.fullmatch(value):
        raise ValueError("Email không hợp lệ")
    return value


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    role: str
    enabled: bool
    picture: str = ""
    password_set: bool = False
    google_linked: bool = False

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "email": self.email, "name": self.name,
                "role": self.role, "enabled": self.enabled, "picture": self.picture,
                "password_set": self.password_set, "google_linked": self.google_linked}


class AuthStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (config.DATA_DIR / "auth.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.db_path.parent.chmod(0o700)  # bảo vệ auth.db-wal/shm chứa OAuth secret
        except OSError:
            pass
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    email_norm TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT 'member',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    password_record TEXT,
                    picture TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS oauth_accounts (
                    provider TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    email TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    PRIMARY KEY(provider, subject),
                    UNIQUE(provider, user_id)
                );
                CREATE TABLE IF NOT EXISTS oauth_flows (
                    state_hash TEXT PRIMARY KEY,
                    verifier TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _user(row: sqlite3.Row | None, google_linked: bool = False) -> User | None:
        if row is None:
            return None
        return User(id=row["id"], email=row["email"], name=row["name"], role=row["role"],
                    enabled=bool(row["enabled"]), picture=row["picture"],
                    password_set=bool(row["password_record"]), google_linked=google_linked)

    def has_users(self) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def get(self, user_id: str) -> User | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            linked = bool(row and db.execute(
                "SELECT 1 FROM oauth_accounts WHERE provider='google' AND user_id=?",
                (user_id,)).fetchone())
            return self._user(row, linked)

    def get_by_email(self, email: str) -> User | None:
        try:
            email_norm = normalize_email(email)
        except ValueError:
            return None
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE email_norm=?", (email_norm,)).fetchone()
            return self._user(row, bool(row and self._google_linked(db, row["id"])))

    @staticmethod
    def _google_linked(db: sqlite3.Connection, user_id: str) -> bool:
        return db.execute("SELECT 1 FROM oauth_accounts WHERE provider='google' AND user_id=?",
                          (user_id,)).fetchone() is not None

    def create_user(self, email: str, password: str | None = None, name: str = "",
                    role: str = "member", enabled: bool = True) -> User:
        email_norm = normalize_email(email)
        if role not in ("admin", "member"):
            raise ValueError("Role phải là admin hoặc member")
        if len(name) > 120 or any(ord(c) < 32 for c in name):
            raise ValueError("Tên không hợp lệ")
        record = json.dumps(make_password_record(password)) if password is not None else None
        user_id = "usr_" + secrets.token_hex(12)
        with self._lock, self._connect() as db:
            try:
                db.execute("INSERT INTO users(id,email,email_norm,name,role,enabled,password_record,created_at) "
                           "VALUES(?,?,?,?,?,?,?,?)",
                           (user_id, email.strip(), email_norm, name.strip(), role,
                            int(enabled), record, time.time()))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Email đã tồn tại") from exc
        user = self.get(user_id)
        assert user is not None
        return user

    def list_users(self) -> list[User]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM users ORDER BY created_at").fetchall()
            users: list[User] = []
            for row in rows:
                user = self._user(row, self._google_linked(db, row["id"]))
                if user is not None:
                    users.append(user)
            return users

    def authenticate(self, email: str, password: str) -> User | None:
        try:
            email_norm = normalize_email(email)
        except ValueError:
            return None
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE email_norm=?", (email_norm,)).fetchone()
        try:
            record = json.loads(row["password_record"]) if row and row["password_record"] \
                else _DUMMY_PASSWORD_RECORD
        except (TypeError, ValueError):
            record = _DUMMY_PASSWORD_RECORD
        valid = verify_password_record(password, record)
        if row is None or not row["enabled"] or not row["password_record"] or not valid:
            return None
        return self._user(row, False)

    def set_password(self, user_id: str, password: str) -> None:
        record = json.dumps(make_password_record(password))
        with self._lock, self._connect() as db:
            if db.execute("UPDATE users SET password_record=? WHERE id=?",
                          (record, user_id)).rowcount != 1:
                raise KeyError("User không tồn tại")

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        with self._lock, self._connect() as db:
            if db.execute("UPDATE users SET enabled=? WHERE id=?",
                          (int(enabled), user_id)).rowcount != 1:
                raise KeyError("User không tồn tại")
            if not enabled:
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                       (token_hash(token), user_id, now, now + SESSION_TTL))
        return token

    def user_for_session(self, token: str) -> User | None:
        if not token or len(token) > 256:
            return None
        try:
            digest = token_hash(token)
        except UnicodeEncodeError:
            return None
        with self._connect() as db:
            row = db.execute("SELECT u.*, s.expires_at AS session_expires FROM sessions s "
                             "JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (digest,)).fetchone()
            if row is None:
                return None
            if row["session_expires"] <= time.time() or not row["enabled"]:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
                return None
            return self._user(row, self._google_linked(db, row["id"]))

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        try:
            digest = token_hash(token)
        except UnicodeEncodeError:
            return
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))

    def revoke_user_sessions(self, user_id: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def update_profile(self, user_id: str, name: str, picture: str = "") -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE users SET name=?, picture=? WHERE id=?",
                       (name[:120], picture[:500], user_id))

    def create_oauth_flow(self) -> dict[str, str]:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        nonce = secrets.token_urlsafe(32)
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM oauth_flows WHERE expires_at<=?", (time.time(),))
            db.execute("INSERT INTO oauth_flows(state_hash,verifier,nonce,expires_at) VALUES(?,?,?,?)",
                       (token_hash(state), verifier, nonce, time.time() + OAUTH_TTL))
        return {"state": state, "verifier": verifier, "nonce": nonce}

    def consume_oauth_flow(self, state: str) -> dict[str, str] | None:
        if not state or len(state) > 256:
            return None
        try:
            digest = token_hash(state)
        except UnicodeEncodeError:
            return None
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM oauth_flows WHERE state_hash=?", (digest,)).fetchone()
            if row is None:
                return None
            db.execute("DELETE FROM oauth_flows WHERE state_hash=?", (digest,))
            if row["expires_at"] <= time.time():
                return None
            return {"state": state, "verifier": row["verifier"], "nonce": row["nonce"]}

    def user_by_google(self, subject: str) -> User | None:
        with self._connect() as db:
            row = db.execute("SELECT u.* FROM oauth_accounts o JOIN users u ON u.id=o.user_id "
                             "WHERE o.provider='google' AND o.subject=?", (subject,)).fetchone()
            return self._user(row, bool(row))

    def link_google(self, user_id: str, subject: str, email: str) -> None:
        if not subject or len(subject) > 255:
            raise ValueError("Google subject không hợp lệ")
        with self._lock, self._connect() as db:
            existing = db.execute("SELECT user_id FROM oauth_accounts WHERE provider='google' AND subject=?",
                                  (subject,)).fetchone()
            if existing and existing["user_id"] != user_id:
                raise ValueError("Google identity đã thuộc user khác")
            bound = db.execute("SELECT subject FROM oauth_accounts WHERE provider='google' AND user_id=?",
                               (user_id,)).fetchone()
            if bound and bound["subject"] != subject:
                raise ValueError("User đã liên kết một Google subject khác")
            db.execute("INSERT OR IGNORE INTO oauth_accounts(provider,subject,user_id,email,created_at) "
                       "VALUES('google',?,?,?,?)", (subject, user_id, email, time.time()))

    def save_google_config(self, client_id: str, client_secret: str, public_url: str) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("Thiếu Google client ID/secret")
        if not public_url.startswith("https://") and not public_url.startswith("http://localhost") \
                and not public_url.startswith("http://127.0.0.1"):
            raise ValueError("FORGE_PUBLIC_URL phải là HTTPS (HTTP chỉ cho localhost)")
        value = json.dumps({"client_id": client_id.strip(), "client_secret": client_secret.strip(),
                            "public_url": public_url.rstrip("/")})
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO auth_settings(key,value) VALUES('google',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass

    def google_config(self) -> dict[str, str] | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM auth_settings WHERE key='google'").fetchone()
        data: dict[str, Any] = {}
        if row:
            try:
                data = json.loads(row["value"])
            except ValueError:
                data = {}
        # ENV là fallback cho deployment quản lý secret ngoài DB.
        data = {"client_id": data.get("client_id") or os.environ.get("FORGE_GOOGLE_CLIENT_ID", ""),
                "client_secret": data.get("client_secret") or os.environ.get("FORGE_GOOGLE_CLIENT_SECRET", ""),
                "public_url": data.get("public_url") or os.environ.get("FORGE_PUBLIC_URL", "")}
        if not all(data.values()):
            return None
        return {k: str(v).rstrip("/") if k == "public_url" else str(v) for k, v in data.items()}


def secure_cookies() -> bool:
    raw = os.environ.get("FORGE_COOKIE_SECURE", "").strip().lower()
    if raw:
        return raw in ("1", "true", "yes", "on")
    return os.environ.get("FORGE_PUBLIC_URL", "").startswith("https://")


def csrf_valid(header_token: str | None, cookie_token: str | None,
               fetch_site: str | None = None) -> bool:
    if fetch_site and fetch_site.lower() == "cross-site":
        return False
    return bool(header_token and cookie_token and len(header_token) <= 256
                and hmac.compare_digest(header_token, cookie_token))
