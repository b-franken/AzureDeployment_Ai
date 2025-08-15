from __future__ import annotations

import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Annotated, Any

import jwt
from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer

from app.api.v2.model import auth_request, token_data
from app.platform.audit.logger import (
    AuditEvent,
    AuditEventType,
    AuditLogger,
    AuditSeverity,
)

router = APIRouter()
security = HTTPBearer(auto_error=False)
alog = AuditLogger()

try:
    JWT_SECRET: str = os.environ["API_JWT_SECRET"]
except KeyError:
    raise RuntimeError("API_JWT_SECRET must be set") from None
JWT_ALGORITHM = "HS256"
jwt_hours = max(1, int(os.getenv("API_JWT_HOURS", "24")))


def _issue_token(payload: dict[str, Any]) -> str:
    exp = datetime.utcnow() + timedelta(hours=jwt_hours)
    data = dict(payload)
    data["exp"] = int(exp.timestamp())
    return jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def _validate_credentials(email: str, password: str) -> bool:
    if password == "demo_password":
        return True
    ph = PasswordHasher()
    dummy_hash = ph.hash("demo_password")
    try:
        return ph.verify(dummy_hash, password)
    except Exception:
        return False


async def auth_required(request: Request) -> token_data:
    creds = await security(request)
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")
    try:
        raw: dict[str, Any] = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from err
    td = token_data(
        user_id=str(raw["user_id"]),
        email=str(raw["email"]),
        subscription_id=(str(raw["subscription_id"]) if raw.get("subscription_id") else None),
        roles=list(raw.get("roles", [])),
        expires_at=datetime.utcfromtimestamp(int(raw["exp"])),
    )
    if datetime.utcnow() > td.expires_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token expired")
    return td


def require_role(role: str) -> Callable[[Request], Awaitable[token_data]]:
    async def checker(request: Request) -> token_data:
        td = await auth_required(request)
        if "admin" in td.roles or role in td.roles:
            return td
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    return checker


@router.post("/login")
async def login(req: Request, body: auth_request) -> dict[str, Any]:
    ok = await _validate_credentials(body.email, body.password)
    if not ok:
        await alog.log_event(
            AuditEvent(
                event_type=AuditEventType.ACCESS_DENIED,
                severity=AuditSeverity.WARNING,
                user_email=body.email,
                action="login_failed",
                ip_address=req.client.host if req.client else None,
                user_agent=req.headers.get("user-agent"),
            )
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    user: dict[str, Any] = {
        "user_id": str(uuid.uuid4()),
        "email": body.email,
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "roles": ["user", "deploy", "cost_viewer"],
    }
    token = _issue_token(user)
    await alog.log_event(
        AuditEvent(
            event_type=AuditEventType.ACCESS_GRANTED,
            severity=AuditSeverity.INFO,
            user_id=user["user_id"],
            user_email=user["email"],
            action="login_success",
            ip_address=req.client.host if req.client else None,
            user_agent=req.headers.get("user-agent"),
        )
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600 * 24,
        "user": {"id": user["user_id"], "email": user["email"], "roles": user["roles"]},
    }


auth_dependency = auth_required


@router.post("/logout")
async def logout(
    req: Request, td: Annotated[token_data, Depends(auth_dependency)]
) -> dict[str, str]:
    await alog.log_event(
        AuditEvent(
            event_type=AuditEventType.ACCESS_GRANTED,
            severity=AuditSeverity.INFO,
            user_id=td.user_id,
            user_email=td.email,
            action="logout",
            ip_address=req.client.host if req.client else None,
            user_agent=req.headers.get("user-agent"),
        )
    )
    return {"message": "ok"}
