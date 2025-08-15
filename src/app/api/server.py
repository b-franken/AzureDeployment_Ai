from __future__ import annotations

import os
from typing import cast

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from app.runtime import backend


class chat_message(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def _role_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("user", "assistant", "system"):
            raise ValueError("invalid role")
        return v


class chat_request(BaseModel):
    message: str
    history: list[chat_message] | list[dict] | None = None
    provider: str | None = None
    model: str | None = None
    enable_tools: bool = False
    preferred_tool: str | None = None


class chat_response(BaseModel):
    content: str


class review_request(BaseModel):
    user: str
    assistant: str
    provider: str | None = None
    model: str | None = None


class review_response(BaseModel):
    content: str


app = FastAPI(title="devops_ai_api")

origins = [os.getenv("FRONTEND_ORIGIN", "*")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=chat_response)
async def chat(req: chat_request) -> chat_response:
    hist: list[dict[str, str]] = []
    for m in list(req.history or []):
        if isinstance(m, dict):
            role = str(m.get("role", "")).strip().lower()
            content = str(m.get("content", ""))
        else:
            mm = cast(chat_message, m)
            role = mm.role
            content = mm.content
        if role and content:
            hist.append({"role": role, "content": content})
    preferred = req.preferred_tool or None
    try:
        content = await backend.chat(
            req.message,
            hist,
            provider=req.provider,
            model=req.model,
            enable_tools=bool(req.enable_tools),
            preferred_tool=preferred,
        )
        return chat_response(content=content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/review", response_model=review_response)
async def review(req: review_request) -> review_response:
    try:
        content = await backend.review(
            req.user,
            req.assistant,
            provider=req.provider,
            model=req.model,
        )
        return review_response(content=content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
