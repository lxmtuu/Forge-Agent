"""Google OpenID Connect login only — không xin hoặc sử dụng Gmail scope."""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebToken

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
SCOPES = "openid email profile"


class GoogleAuthError(ValueError):
    pass


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(client_id: str, redirect_uri: str, state: str,
                      verifier: str, nonce: str) -> str:
    params = {"client_id": client_id, "redirect_uri": redirect_uri,
              "response_type": "code", "scope": SCOPES, "state": state,
              "code_challenge": _pkce_challenge(verifier), "code_challenge_method": "S256",
              "nonce": nonce, "prompt": "select_account", "access_type": "online"}
    return AUTHORIZATION_URL + "?" + urlencode(params)


async def exchange_code(client_id: str, client_secret: str, redirect_uri: str,
                        code: str, verifier: str) -> dict[str, Any]:
    try:
        async with AsyncOAuth2Client(client_id=client_id, client_secret=client_secret,
                                     redirect_uri=redirect_uri) as client:
            token = await client.fetch_token(TOKEN_URL, code=code,
                                             grant_type="authorization_code",
                                             code_verifier=verifier)
        if not isinstance(token, dict) or not token.get("id_token"):
            raise GoogleAuthError("Google không trả ID token")
        return token
    except GoogleAuthError:
        raise
    except Exception as exc:  # Authlib/httpx errors không lộ chi tiết ra browser.
        raise GoogleAuthError("Không thể đổi Google authorization code") from exc


async def fetch_google_jwks() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(JWKS_URL)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
            raise TypeError("invalid JWKS")
        return data
    except Exception as exc:
        raise GoogleAuthError("Không thể lấy Google JWKS") from exc


async def verify_id_token(id_token: str, client_id: str, expected_nonce: str,
                          jwks: dict[str, Any] | None = None) -> dict[str, str]:
    """Verify chữ ký RS256 bằng Google JWKS, issuer/audience/time và nonce."""
    keys = jwks if jwks is not None else await fetch_google_jwks()
    try:
        claims = JsonWebToken(["RS256"]).decode(
            id_token, keys,
            claims_options={
                "iss": {"essential": True, "values": ["https://accounts.google.com", "accounts.google.com"]},
                "aud": {"essential": True, "value": client_id},
                "exp": {"essential": True},
                "iat": {"essential": True},
                "sub": {"essential": True},
            })
        claims.validate(leeway=60)
        nonce = str(claims.get("nonce", ""))
        if not nonce or not hmac.compare_digest(nonce, expected_nonce):
            raise GoogleAuthError("Google nonce không khớp")
        if claims.get("azp") and claims.get("azp") != client_id:
            raise GoogleAuthError("Google authorized party không khớp")
        if claims.get("email_verified") is not True:
            raise GoogleAuthError("Google email chưa được xác minh")
        subject = str(claims.get("sub", ""))
        email = str(claims.get("email", "")).strip()
        if not subject or not email or len(subject) > 255 or len(email) > 254:
            raise GoogleAuthError("Google identity thiếu claims")
        picture = str(claims.get("picture", ""))
        return {"sub": subject, "email": email,
                "name": str(claims.get("name", ""))[:120],
                "picture": picture[:500] if picture.startswith("https://") else ""}
    except GoogleAuthError:
        raise
    except Exception as exc:
        raise GoogleAuthError("Google ID token không hợp lệ") from exc
