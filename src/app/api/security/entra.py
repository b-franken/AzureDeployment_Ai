from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer
from jwt import PyJWTError
from jwt.algorithms import RSAAlgorithm

from app.api.schemas import TokenData

# Configuration via env (with sensible defaults)
TENANT_ID = os.getenv("ENTRA_TENANT_ID") or os.getenv("AZURE_TENANT_ID") or ""
AUDIENCE = os.getenv("ENTRA_AUDIENCE") or os.getenv("API_AUDIENCE") or ""
ALLOWED_ALGS = ("RS256",)

if not AUDIENCE:
    raise RuntimeError("ENTRA_AUDIENCE must be set for Entra ID validation")

ISSUER_TEMPLATE = "https://login.microsoftonline.com/{tenant}/v2.0"
JWKS_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"

security = HTTPBearer(auto_error=False)


class _JwksCache:
    """Tiny in-memory JWKS cache with TTL and per-tenant storage."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, tenant: str) -> dict[str, Any]:
        key = tenant or "common"
        now = time.time()
        async with self._lock:
            cached = self._items.get(key)
            if cached and now - cached[0] < self._ttl:
                return cached[1]
        # fetch outside lock to avoid long hold
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = JWKS_URL_TEMPLATE.format(tenant=tenant or "common")
            resp = await client.get(url)
            resp.raise_for_status()
            jwks = resp.json()
        async with self._lock:
            self._items[key] = (now, jwks)
        return jwks


_jwks_cache = _JwksCache(ttl_seconds=3600)


def _pick_email(claims: dict[str, Any]) -> str:
    for k in ("preferred_username", "upn", "email"):
        v = claims.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _roles_from_claims(claims: dict[str, Any]) -> list[str]:
    if "roles" in claims and isinstance(claims["roles"], list):
        return [str(r) for r in claims["roles"] if r]
    scp = claims.get("scp")  # space-delimited scopes
    if isinstance(scp, str) and scp:
        return [s.strip() for s in scp.split() if s.strip()]
    return []


async def _validate_jwt_with_jwks(token: str) -> dict[str, Any]:
    try:
        unverified_header = jwt.get_unverified_header(token)
        unverified_claims = jwt.decode(token, options={"verify_signature": False})
    except PyJWTError as err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token header") from err

    alg = unverified_header.get("alg")
    kid = unverified_header.get("kid")
    tid = (TENANT_ID or unverified_claims.get("tid") or "").strip()

    if alg not in ALLOWED_ALGS or not kid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unsupported token")

    if not tid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="tenant not allowed")

    jwks = await _jwks_cache.get(tid)
    keys = jwks.get("keys") or []
    jwk: Optional[Dict[str, Any]] = next((k for k in keys if k.get("kid") == kid), None)
    if not jwk:
        _jwks_cache._items.pop(tid, None)
        jwks = await _jwks_cache.get(tid)
        keys = jwks.get("keys") or []
        jwk = next((k for k in keys if k.get("kid") == kid), None)
    if not jwk:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="signing key not found")

    public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
    issuer = ISSUER_TEMPLATE.format(tenant=tid)
    try:
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=list(ALLOWED_ALGS),
            audience=AUDIENCE,
            issuer=issuer,
            options={"require": ["exp", "iss", "aud"]},
        )
    except PyJWTError as err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from err

    return claims


async def entra_auth_required(request: Request) -> TokenData:
    creds = await security(request)
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")

    claims = await _validate_jwt_with_jwks(creds.credentials)

    user_id = str(claims.get("oid") or claims.get("sub") or "")
    email = _pick_email(claims)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid subject")

    roles = _roles_from_claims(claims)
    exp_ts = int(claims["exp"])

    return TokenData(
        user_id=user_id,
        email=email or "unknown@unknown",
        subscription_id=None,
        roles=roles,
        expires_at=time.gmtime(exp_ts),  
    )
