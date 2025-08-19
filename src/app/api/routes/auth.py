from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

try:
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception:
    import hashlib
    import secrets

    class SimplePwdContext:
        def hash(self, password: str) -> str:
            salt = secrets.token_hex(16)
            return f"{salt}${hashlib.sha256((salt + password).encode()).hexdigest()}"

        def verify(self, plain_password: str, hashed_password: str) -> bool:
            try:
                salt, hash_part = hashed_password.split("$")
                return hashlib.sha256((salt + plain_password).encode()).hexdigest() == hash_part
            except ValueError as exc:
                logger.exception("Invalid hashed password: %s", exc)
                return False

    pwd_context = SimplePwdContext()

router = APIRouter()
logger = logging.getLogger(__name__)


SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


USERS_DB = {}


def init_users():
    """Initialize users with hashed passwords"""
    global USERS_DB
    USERS_DB = {
        "admin@example.com": {
            "email": "admin@example.com",
            "hashed_password": pwd_context.hash("admin123"),
            "roles": ["admin", "user"],
            "subscription_id": "12345678-1234-1234-1234-123456789012",
            "is_active": True,
        },
        "user@example.com": {
            "email": "user@example.com",
            "hashed_password": pwd_context.hash("user123"),
            "roles": ["user"],
            "subscription_id": "87654321-4321-4321-4321-210987654321",
            "is_active": True,
        },
    }


init_users()


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    email: str
    user_id: str
    roles: list[str]
    subscription_id: str | None = None
    expires_at: datetime


class User(BaseModel):
    email: str
    roles: list[str]
    subscription_id: str | None
    is_active: bool


class UserInDB(User):
    hashed_password: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.exception("Password verification error: %s", e)
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def get_user(email: str) -> UserInDB | None:
    user_data = USERS_DB.get(email)
    if user_data:
        return UserInDB(**user_data)
    return None


def authenticate_user(email: str, password: str) -> UserInDB | None:
    user = get_user(email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise credentials_exception

        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception

        token_data = TokenData(
            email=email,
            user_id=payload.get("user_id", email),
            roles=payload.get("roles", []),
            subscription_id=payload.get("subscription_id"),
            expires_at=datetime.fromtimestamp(payload.get("exp", 0)),
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise credentials_exception

    user = get_user(email=token_data.email)
    if user is None:
        raise credentials_exception

    return User(
        email=user.email,
        roles=user.roles,
        subscription_id=user.subscription_id,
        is_active=user.is_active,
    )


async def get_current_active_user(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def require_role(role: str):
    async def role_checker(current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
        if role not in current_user.roles and "admin" not in current_user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
            )
        return current_user

    return role_checker


@router.post("/token", response_model=Token)
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """OAuth2 compatible token login, get an access token for future requests"""
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token_data = {
        "sub": user.email,
        "user_id": user.email.replace("@", "_").replace(".", "_"),
        "roles": user.roles,
        "subscription_id": user.subscription_id,
    }

    access_token = create_access_token(
        token_data, expires_delta=access_token_expires)
    refresh_token = create_refresh_token(token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/refresh")
async def refresh_token(refresh_token: str):
    """Use refresh token to get new access token"""
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
            )

        email = payload.get("sub")
        user = get_user(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        token_data = {
            "sub": user.email,
            "user_id": user.email.replace("@", "_").replace(".", "_"),
            "roles": user.roles,
            "subscription_id": user.subscription_id,
        }

        new_access_token = create_access_token(
            token_data, expires_delta=access_token_expires)

        return {
            "access_token": new_access_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has expired"
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )


@router.get("/me")
async def read_users_me(current_user: Annotated[User, Depends(get_current_active_user)]):
    """Get current user information"""
    return current_user


@router.post("/logout")
async def logout(current_user: Annotated[User, Depends(get_current_active_user)]):
    """Logout (client should discard tokens)"""
    return {"message": "Successfully logged out"}


auth_dependency = get_current_active_user


async def auth_required(request: Request) -> TokenData:
    """Backward compatibility function"""
    token = await oauth2_scheme(request)
    user = await get_current_user(token)
    return TokenData(
        email=user.email,
        user_id=user.email.replace("@", "_").replace(".", "_"),
        roles=user.roles,
        subscription_id=user.subscription_id,
        expires_at=datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
