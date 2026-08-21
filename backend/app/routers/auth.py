"""Simple login router for MVP — hardcoded admin/admin credentials.

In production this would be replaced with a proper OAuth2 / SSO flow. The
MVP token is a signed JWT so the frontend can verify it without a database
call, but the expiry is generous and there is no refresh-token rotation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Hardcoded MVP credentials
# ---------------------------------------------------------------------------
_USER = "admin"
_PASS = "admin"

# Derive a signing key from the app name + a fixed pepper. Not production-grade
# (the pepper is in the source tree), but enough to keep a casual browser from
# forging tokens. In production, read NEXA_AUTH_SECRET from the environment.
_PEPPER = b"nexa-mvp-2026-pepper"
_SIGNING_KEY = hashlib.sha256(
    _PEPPER + settings.app_name.encode()
).digest()

_TOKEN_TTL = 86400 * 7  # 7 days


def _sign(payload: bytes) -> str:
    return hmac.new(_SIGNING_KEY, payload, "sha256").hexdigest()


def _make_token(username: str) -> str:
    now = int(time.time())
    body = json.dumps({"user": username, "iat": now, "exp": now + _TOKEN_TTL})
    b64 = body.encode()
    sig = _sign(b64)
    # Simple format: base64(body).hex(signature)
    return b64.hex() + "." + sig


def verify_token(token: str) -> dict[str, Any] | None:
    """Return the token payload if valid, None otherwise."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        b64_hex, sig = parts
        body = bytes.fromhex(b64_hex)
        expected = _sign(body)
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(body.decode())
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except (ValueError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class VerifyResponse(BaseModel):
    valid: bool
    username: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/login")
def login(request: LoginRequest) -> LoginResponse:
    if request.username != _USER or request.password != _PASS:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return LoginResponse(token=_make_token(request.username), username=request.username)


@router.post("/verify")
def verify(body: dict[str, str]) -> VerifyResponse:
    token = body.get("token", "")
    payload = verify_token(token)
    if payload is None:
        return VerifyResponse(valid=False)
    return VerifyResponse(valid=True, username=payload["user"])