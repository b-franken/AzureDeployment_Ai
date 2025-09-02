from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWK, PyJWKClient, PyJWTError

from app.core.config import API_APP_ID_URI, ISSUER, JWKS_URL

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not JWKS_URL:
            raise ValueError("JWKS_URL is required but not configured")
        _jwks_client = PyJWKClient(JWKS_URL)
    return _jwks_client


def _decode_ms_token(token: str) -> dict[str, Any]:
    jwks_client = _get_jwks_client()
    signing_jwk: PyJWK = jwks_client.get_signing_key_from_jwt(token)
    decoded: dict[str, Any] = jwt.decode(
        token,
        signing_jwk,
        algorithms=["RS256"],
        audience=API_APP_ID_URI,
        issuer=ISSUER,
    )
    return decoded


async def azure_auth(request: Request) -> dict[str, Any]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="auth required")

    token = auth.split(None, 1)[1]

    try:
        claims = _decode_ms_token(token)
    except PyJWTError as err:
        # Keep the original cause attached for debugging clarity
        raise HTTPException(status_code=401, detail="invalid token") from err

    scopes = set((claims.get("scp") or "").split())
    roles_list = cast("Sequence[str]", claims.get("roles") or [])
    roles = set(roles_list)

    return {
        "sub": claims.get("sub"),
        "oid": claims.get("oid"),
        "email": claims.get("preferred_username") or claims.get("upn"),
        "scopes": scopes,
        "roles": roles,
        "exp": datetime.fromtimestamp(int(cast("str | int", claims["exp"]))),
    }
