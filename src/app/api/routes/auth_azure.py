from datetime import datetime

import httpx
import jwt
from core.config import API_APP_ID_URI, ISSUER, JWKS_URL
from fastapi import HTTPException, Request

_jwks = None
def _get_jwks():
    global _jwks
    if not _jwks:
        _jwks = httpx.get(JWKS_URL, timeout=5).json()
    return _jwks

def _decode_ms_token(token: str) -> dict:
    header = jwt.get_unverified_header(token)
    jwks = _get_jwks()
    key = next((k for k in jwks["keys"] if k["kid"] == header["kid"]), None)
    if not key:
        raise HTTPException(status_code=401, detail="jwks key not found")

    signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
    return jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        audience=API_APP_ID_URI,
        issuer=ISSUER,
    )

async def azure_auth(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="auth required")
    token = auth.split(None, 1)[1]
    try:
        claims = _decode_ms_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")

    scopes = set((claims.get("scp") or "").split())

    roles = set(claims.get("roles") or [])

    return {
        "sub": claims.get("sub"),
        "oid": claims.get("oid"),
        "email": claims.get("preferred_username") or claims.get("upn"),
        "scopes": scopes,
        "roles": roles,
        "exp": datetime.fromtimestamp(int(claims["exp"])),
    }