"""OAuth 2.1 cho connectors — authorization code + PKCE (RFC 7636) trên loopback (RFC 8252).

Chuẩn ngành áp dụng (MCP authorization spec, 2025-06-18):
- Public client: PKCE S256 BẮT BUỘC; không có secret thì token_endpoint_auth_method=none.
- Loopback redirect `http://127.0.0.1:<port>/callback` — port 0 = chọn cổng trống ngẫu nhiên
  (RFC 8252 §7.3); preset ghim cổng khi nhà cung cấp yêu cầu đăng ký URI tĩnh.
- `state` ngẫu nhiên mỗi lần — chặn CSRF; sai state = từ chối code.
- DCR (RFC 7591): nếu preset khai báo registration_endpoint → tự đăng ký client.
- Token lưu `data/secrets.json` (chmod 600), KHÔNG bao giờ vào context LLM; hiển thị chỉ mask.
- KHÔNG tự mở browser giữa lượt agent — flow chỉ chạy khi người dùng chủ động gọi lệnh.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import secrets as _pysecrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

_CALLBACK_OK = b"<html><body style='font-family:sans-serif;background:#1b1c21;color:#eee;display:grid;place-items:center;height:90vh'><div style='text-align:center'><h1>&#9989; Forge agent &#8212; da nhan ma truy cap</h1><p>Ban co the dong tab nay va quay lai.</p></div></body></html>"
_CALLBACK_ERR = b"<html><body style='font-family:sans-serif;background:#1b1c21;color:#eee;display:grid;place-items:center;height:90vh'><div style='text-align:center'><h1>&#10060; Loi OAuth</h1><p id='d'></p><script>document.getElementById('d').textContent=location.search</script></div></body></html>"


# ─────────────────────────────────────────── PKCE + state ─────────────────────
def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge S256) — RFC 7636 §4.1-4.2, charset unreserved."""
    verifier = _pysecrets.token_urlsafe(48)  # -/_ đều thuộc unreserved của RFC 7636
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def new_state() -> str:
    """State chống CSRF — tối thiểu 16 byte ngẫu nhiên (OAuth 2.1 draft §4.5.1)."""
    return _pysecrets.token_urlsafe(24)


# ─────────────────────────────────────────── loopback listener ────────────────
class Loopback:
    """HTTP one-shot trên 127.0.0.1 — nhận ?code=&state= từ lần redirect đầu tiên."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.result: dict[str, str] = {}
        outer = self
        self._httpd = HTTPServer((host, port), self._handler(outer))
        self.port = self._httpd.server_address[1]
        self.uri = f"http://{host}:{self.port}/callback"
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    @staticmethod
    def _handler(outer: Loopback):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                if u.path != "/callback":
                    self.send_error(404, "chỉ nhận /callback")
                    return
                outer.result = dict(urllib.parse.parse_qsl(u.query))
                body = _CALLBACK_ERR if "error" in outer.result else _CALLBACK_OK
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                threading.Thread(target=outer._httpd.shutdown, daemon=True).start()

            def log_message(self, *_a):
                pass

        return H

    def wait(self, timeout: float = 300.0) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.result:
                return self.result
            time.sleep(0.15)
        raise TimeoutError(f"Hết {int(timeout)}s không thấy redirect về {self.uri}")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._httpd.shutdown()
            self._httpd.server_close()


# ─────────────────────────────────────────── HTTP helpers ─────────────────────
def build_authorize_url(authorize_url: str, client_id: str, redirect_uri: str,
                        state: str, challenge: str, scope: str = "") -> str:
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    if scope:
        q["scope"] = scope
    sep = "&" if "?" in authorize_url else "?"
    return f"{authorize_url}{sep}{urllib.parse.urlencode(q)}"


def _client_auth(data: dict, client_id: str, client_secret: str | None, style: str) -> httpx.BasicAuth | None:
    if client_secret:
        if style == "basic":
            return httpx.BasicAuth(client_id, client_secret)
        data["client_secret"] = client_secret
    data["client_id"] = client_id
    return None


def exchange_code(token_url: str, code: str, verifier: str, redirect_uri: str,
                  client_id: str, client_secret: str | None = None, auth_style: str = "post",
                  timeout: float = 30.0) -> dict:
    """Đổi authorization code lấy token (grant=authorization_code + code_verifier)."""
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "code_verifier": verifier}
    auth = _client_auth(data, client_id, client_secret, auth_style)
    r = httpx.post(token_url, data=data, auth=auth, timeout=timeout,
                   headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"token endpoint {r.status_code}: {r.text[:200]}")
    return r.json()


def refresh_tokens(token_url: str, refresh_token: str, client_id: str,
                   client_secret: str | None = None, auth_style: str = "post",
                   timeout: float = 30.0) -> dict:
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    auth = _client_auth(data, client_id, client_secret, auth_style)
    r = httpx.post(token_url, data=data, auth=auth, timeout=timeout,
                   headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"refresh {r.status_code}: {r.text[:200]}")
    return r.json()


def register_client(registration_endpoint: str, redirect_uri: str, client_name: str,
                    timeout: float = 30.0) -> str:
    """DCR RFC 7591 — public client (PKCE S256, token_endpoint_auth_method=none)."""
    body = {"client_name": client_name,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "code_challenge_method": "S256"}
    r = httpx.post(registration_endpoint, json=body, timeout=timeout,
                   headers={"Accept": "application/json"})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"DCR {r.status_code}: {r.text[:200]}")
    cid = r.json().get("client_id")
    if not cid:
        raise RuntimeError("DCR phản hồi thiếu client_id")
    return cid


# ─────────────────────────────────────────── lưu trữ (secrets.json, chmod 600) ──
def _conn():
    from . import connectors as fc
    return fc


def save_creds(name: str, client_id: str, client_secret: str | None = None) -> None:
    fc = _conn()
    key = fc._sanitize_name(name)
    sec = fc._load_secrets()
    ent = sec.setdefault(key, {})
    ent["client_id"], ent["client_secret"] = client_id.strip(), (client_secret or "").strip()
    ent["connector"] = ent.get("connector", name)
    fc._save_secrets(sec)


def save_tokens(name: str, tokens: dict) -> None:
    fc = _conn()
    key = fc._sanitize_name(name)
    sec = fc._load_secrets()
    ent = sec.setdefault(key, {})
    expires_in = int(tokens.get("expires_in") or 3600)
    ent["oauth"] = {
        "access_token": tokens.get("access_token", ""),
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": time.time() + max(0, expires_in - 60),  # nới 60s cho độ trễ
        "scope": tokens.get("scope", ""),
        "ts": time.time(),
    }
    ent["masked"] = fc.mask_token(ent["oauth"]["access_token"])
    fc._save_secrets(sec)


def forget(name: str) -> bool:
    """Xoá token OAuth (giữ client_id/secret để đăng nhập lại nhanh)."""
    fc = _conn()
    key = fc._sanitize_name(name)
    sec = fc._load_secrets()
    if key not in sec or "oauth" not in sec[key]:
        return False
    sec[key].pop("oauth", None)
    fc._save_secrets(sec)
    return True


def has_oauth(name: str) -> bool:
    fc = _conn()
    return bool(fc._load_secrets().get(fc._sanitize_name(name), {}).get("oauth", {}).get("access_token"))


def masked(name: str) -> str | None:
    fc = _conn()
    ent = fc._load_secrets().get(fc._sanitize_name(name), {})
    return ent.get("masked") if ent.get("oauth") else None


def get_access_token(name: str) -> str | None:
    """Token còn hạn → trả luôn; hết hạn → refresh ngầm 1 lần; fail → None (không ném)."""
    fc = _conn()
    ent = fc._load_secrets().get(fc._sanitize_name(name), {})
    oa = ent.get("oauth")
    if not oa or not oa.get("access_token"):
        return None
    if time.time() < oa.get("expires_at", 0):
        return oa["access_token"]
    if not oa.get("refresh_token"):
        return None
    p = fc.PRESETS.get(name, {})
    oc = p.get("oauth") or {}
    try:
        fresh = refresh_tokens(oc.get("token", ""), oa["refresh_token"],
                               ent.get("client_id", ""), ent.get("client_secret", ""),
                               oc.get("style", "post"))
    except Exception:  # noqa: BLE001 — refresh hỏng không được làm sập chat
        return None
    if not fresh.get("access_token"):
        return None
    save_tokens(name, {**oa, **fresh, "expires_in": fresh.get("expires_in") or 3600})
    return fresh["access_token"]


# ─────────────────────────────────────────── flow chính ───────────────────────
_FLOWS: dict[str, dict] = {}  # name → {"status": pending|connected|error, "detail", "authorize_url"}


def flow_status(name: str) -> dict:
    return dict(_FLOWS.get(_conn()._sanitize_name(name), {"status": "idle", "detail": ""}))


def connect(name: str, open_browser: bool = True, _open=None, _timeout: float = 300.0) -> str:
    """Chạy flow đầy đủ: loopback → (DCR) → mở browser → chờ code → đổi token → lưu.

    Trả về chuỗi thân thiện người dùng (không bao giờ chứa token thật).
    """
    fc = _conn()
    pid = (name or "").strip().lower()
    p = fc.PRESETS.get(pid)
    if p is None or not p.get("oauth"):
        return (f"❌ Preset '{name}' không hỗ trợ OAuth. Hỗ trợ: "
                + ", ".join(sorted(k for k, v in fc.PRESETS.items() if v.get("oauth"))))
    oc = p["oauth"]
    key = fc._sanitize_name(pid)
    sec = fc._load_secrets().get(key, {})
    cid = sec.get("client_id") or os.environ.get(f"FORGE_{key.upper()}_CLIENT_ID", "").strip()
    csec = sec.get("client_secret") or os.environ.get(f"FORGE_{key.upper()}_CLIENT_SECRET", "").strip()
    style = oc.get("style", "post")

    lb = Loopback(port=int(oc.get("loopback_port", 0) or 0))
    _FLOWS[key] = {"status": "pending", "detail": "Đang chờ duyệt trong trình duyệt…", "authorize_url": ""}
    try:
        if not cid and oc.get("registration_endpoint"):
            cid = register_client(oc["registration_endpoint"], lb.uri, f"forge-agent-{key}")
            save_creds(pid, cid, "")
        if not cid:
            _FLOWS[key] = {"status": "error", "detail": "thiếu client_id", "authorize_url": ""}
            return (f"❌ '{pid}' cần client_id. Tạo ứng dụng OAuth của nhà cung cấp (redirect: "
                    f"http://127.0.0.1:{oc.get('loopback_port', 0) or '<cổng trống>'}/callback) rồi chạy:\n"
                    f"   /connectors oauth {pid} <client_id> [client_secret]")
        state, (verifier, challenge) = new_state(), pkce_pair()
        url = build_authorize_url(oc["authorize"], cid, lb.uri, state, challenge, oc.get("scope", ""))
        _FLOWS[key] = {"status": "pending", "detail": "Chờ duyệt trong trình duyệt…", "authorize_url": url}
        opener = _open or (webbrowser.open if open_browser else (lambda _u: False))
        opener(url)
        cb = lb.wait(_timeout)
        if cb.get("error"):
            _FLOWS[key] = {"status": "error", "detail": cb["error"], "authorize_url": ""}
            return f"❌ Nhà cung cấp từ chối: {cb.get('error_description') or cb['error']}"
        if not _pysecrets.compare_digest(cb.get("state", ""), state):
            _FLOWS[key] = {"status": "error", "detail": "state không khớp (CSRF?)", "authorize_url": ""}
            return "❌ state không khớp — từ chối code (có thể là CSRF hoặc phiên cũ)."
        tokens = exchange_code(oc["token"], cb["code"], verifier, lb.uri, cid, csec, style)
        if not tokens.get("access_token"):
            _FLOWS[key] = {"status": "error", "detail": "không có access_token", "authorize_url": ""}
            return "❌ Token endpoint không trả access_token."
        save_tokens(pid, tokens)
        msg = f"✅ OAuth '{p['label'].split(' — ')[0]}' xong — token {fc.mask_token(tokens['access_token'])} đã lưu (secrets.json, chmod 600). Gõ /mcp refresh để nạp tool."
        _FLOWS[key] = {"status": "connected", "detail": msg, "authorize_url": ""}
        return msg
    except Exception as e:  # noqa: BLE001 — lỗi flow trả về chuỗi, không ném
        _FLOWS[key] = {"status": "error", "detail": str(e)[:200], "authorize_url": ""}
        return f"❌ OAuth thất bại: {e}"
    finally:
        lb.close()
