# src/app/api/error_handlers.py
from __future__ import annotations

from typing import Any, NoReturn

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(_: Any, exc: RequestValidationError) -> NoReturn:
        errors: list[dict[str, Any]] = [
            {
                "loc": e.get("loc", []),
                "msg": e.get("msg", "Invalid value"),
                "type": e.get("type", "value_error"),
            }
            for e in exc.errors()
        ]
        raise HTTPException(status_code=400, detail={"errors": errors})

    @app.exception_handler(ValidationError)
    async def _handle_pydantic_validation(_: Any, exc: ValidationError) -> NoReturn:
        errors: list[dict[str, Any]] = [
            {
                "loc": e.get("loc", []),
                "msg": e.get("msg", "Invalid value"),
                "type": e.get("type", "value_error"),
            }
            for e in exc.errors()
        ]
        raise HTTPException(status_code=400, detail={"errors": errors})
