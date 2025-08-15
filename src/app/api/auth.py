import os

from fastapi import HTTPException, Request, status


def get_api_token() -> str:
    token = os.getenv("API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("API_TOKEN must be set in non-dev environments")
    return token


def require_bearer_token(request: Request) -> None:
    expected = get_api_token()
    auth = request.headers.get("authorization", "")
    provided = auth.split(None, 1)[1] if auth.lower().startswith("bearer ") else None
    if provided is None or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        )
