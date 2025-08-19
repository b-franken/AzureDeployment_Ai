from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, cast

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer
from jwt import PyJWTError
from jwt.algorithms import RSAAlgorithm

from app.api.schemas import TokenData
from src.app.core.loging import get_logger
from app.observability.tracing import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)

TENANT_ID = os.getenv("ENTRA_TENANT_ID") or os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("ENTRA_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")
AUDIENCE = os.getenv("ENTRA_AUDIENCE") or os.getenv(
    "API_AUDIENCE") or CLIENT_ID
ALLOWED_ALGS = ("RS256",)

if not TENANT_ID:
    raise RuntimeError("ENTRA_TENANT_ID or AZURE_TENANT_ID must be set")
if not CLIENT_ID:
    raise RuntimeError("ENTRA_CLIENT_ID or AZURE_CLIENT_ID must be set")

ISSUER_V1 = f"https://sts.windows.net/{TENANT_ID}/"
ISSUER_V2 = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
JWKS_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

security = HTTPBearer(auto_error=False)


class JwksCache:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, tenant: str) -> dict[str, Any]:
        with tracer.start_as_current_span("jwks_cache_get") as span:
            span.set_attribute("tenant_id", tenant)
            key = tenant
            now = time.time()

            async with self._lock:
                cached = self._items.get(key)
                if cached and now - cached[0] < self._ttl:
                    span.set_attribute("cache_hit", True)
                    return cached[1]

            span.set_attribute("cache_hit", False)
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
                resp = await client.get(url)
                resp.raise_for_status()
                jwks = resp.json()

            async with self._lock:
                self._items[key] = (now, jwks)
            return jwks

    async def invalidate(self, tenant: str) -> None:
        async with self._lock:
            self._items.pop(tenant, None)


_jwks_cache = JwksCache(ttl_seconds=3600)


def extract_email(claims: dict[str, Any]) -> str:
    for k in ("preferred_username", "upn", "email", "unique_name"):
        v = claims.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def extract_roles(claims: dict[str, Any]) -> list[str]:
    roles: list[str] = []

    if "roles" in claims and isinstance(claims["roles"], list):
        roles.extend([str(r) for r in claims["roles"] if r])

    scp = claims.get("scp")
    if isinstance(scp, str) and scp:
        roles.extend([s.strip() for s in scp.split() if s.strip()])

    app_roles = claims.get("app_roles")
    if isinstance(app_roles, list):
        roles.extend([str(r) for r in app_roles if r])

    groups = claims.get("groups")
    if isinstance(groups, list):
        for group_id in groups:
            roles.append(f"group:{group_id}")

    return list(set(roles))


async def validate_entra_token(token: str) -> dict[str, Any]:
    with tracer.start_as_current_span("validate_entra_token") as span:
        try:
            unverified_header = jwt.get_unverified_header(token)
            unverified_claims = jwt.decode(
                token, options={"verify_signature": False})

            span.set_attributes(
                {
                    "token_alg": unverified_header.get("alg"),
                    "token_kid": unverified_header.get("kid"),
                    "token_iss": unverified_claims.get("iss"),
                    "token_aud": unverified_claims.get("aud"),
                }
            )
        except PyJWTError as err:
            logger.error("Failed to decode token header", exc_info=err)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format"
            ) from err

        alg = unverified_header.get("alg")
        kid = unverified_header.get("kid")

        if alg not in ALLOWED_ALGS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Unsupported algorithm: {alg}"
            )

        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing key ID in token"
            )

        tid = unverified_claims.get("tid", TENANT_ID)
        if not tid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing tenant ID"
            )

        jwks = await _jwks_cache.get(tid)
        keys = jwks.get("keys") or []
        jwk: dict[str, Any] | None = next(
            (k for k in keys if k.get("kid") == kid), None)

        if not jwk:
            await _jwks_cache.invalidate(tid)
            jwks = await _jwks_cache.get(tid)
            keys = jwks.get("keys") or []
            jwk = next((k for k in keys if k.get("kid") == kid), None)

        if not jwk:
            logger.error("Signing key not found", extra={
                         "kid": kid, "tenant": tid})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Signing key not found"
            )

        public_key: RSAPublicKey = cast(
            RSAPublicKey, RSAAlgorithm.from_jwk(json.dumps(jwk)))

        valid_issuers = [ISSUER_V1, ISSUER_V2]

        try:
            claims = jwt.decode(
                token,
                key=public_key,
                algorithms=list(ALLOWED_ALGS),
                audience=AUDIENCE,
                issuer=valid_issuers,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                    "require": ["exp", "iss", "aud"],
                },
            )
            span.set_attribute("validation_success", True)
            return claims
        except jwt.ExpiredSignatureError as err:
            logger.warning("Token expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            ) from err
        except jwt.InvalidAudienceError as err:
            logger.warning("Invalid audience", extra={"expected": AUDIENCE})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid audience"
            ) from err
        except jwt.InvalidIssuerError as err:
            logger.warning("Invalid issuer", extra={"expected": valid_issuers})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid issuer"
            ) from err
        except PyJWTError as err:
            logger.error("Token validation failed", exc_info=err)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token validation failed"
            ) from err


async def entra_auth_required(request: Request) -> TokenData:
    with tracer.start_as_current_span("entra_auth_required") as span:
        creds = await security(request)
        if not creds or not creds.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
            )

        claims = await validate_entra_token(creds.credentials)

        user_id = str(claims.get("oid") or claims.get("sub") or "")
        email = extract_email(claims)

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject claim"
            )

        roles = extract_roles(claims)
        exp_ts = int(claims["exp"])

        subscription_id = claims.get("extension_SubscriptionId") or os.getenv(
            "AZURE_SUBSCRIPTION_ID"
        )

        span.set_attributes(
            {
                "user_id": user_id,
                "user_email": email,
                "user_roles_count": len(roles),
                "token_exp": exp_ts,
            }
        )

        logger.info(
            "Entra ID authentication successful",
            extra={
                "user_id": user_id,
                "email": email,
                "roles_count": len(roles),
            },
        )

        return TokenData(
            user_id=user_id,
            email=email or "unknown@unknown",
            subscription_id=subscription_id,
            roles=roles,
            expires_at=datetime.fromtimestamp(exp_ts),
        )


async def entra_auth_with_role(required_role: str) -> Callable[[Request], Awaitable[TokenData]]:
    async def verify(request: Request) -> TokenData:
        token_data = await entra_auth_required(request)

        if required_role not in token_data.roles and "admin" not in token_data.roles:
            logger.warning(
                "Insufficient privileges",
                extra={
                    "user_id": token_data.user_id,
                    "required_role": required_role,
                    "user_roles": token_data.roles,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"Role '{required_role}' required"
            )

        return token_data

    return verify
