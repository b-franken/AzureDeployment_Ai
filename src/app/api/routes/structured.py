from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from jsonschema import Draft202012Validator, SchemaError, ValidationError

from app.ai.llm.factory import get_provider_and_model
from app.api.routes.schemas import StructuredChatRequest, StructuredChatResponse

router = APIRouter()


@router.post("", response_model=StructuredChatResponse)
async def structured(req: StructuredChatRequest) -> StructuredChatResponse:
    try:
        Draft202012Validator.check_schema(req.schema)
    except SchemaError as e:
        raise HTTPException(
            status_code=400,
            detail={"errors": [{"loc": [], "msg": str(e), "type": "schema"}]},
        ) from e

    llm, model = await get_provider_and_model(req.provider, req.model)
    if not hasattr(llm, "chat_raw"):
        raise HTTPException(
            status_code=400, detail="Structured output not supported by this provider."
        )

    messages = [{"role": "user", "content": req.input}]
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "StructuredOutput", "schema": req.schema},
    }

    raw = await llm.chat_raw(  # type: ignore[attr-defined]
        model=model,
        messages=messages,
        tool_choice="none",
        response_format=response_format,
        max_tokens=2048,
        temperature=0.2,
    )

    choices = raw.get("choices", [])
    content = next(
        (
            c.get("message", {}).get("content")
            for c in choices
            if c.get("message", {}).get("content")
        ),
        None,
    )
    if content is None:
        raise HTTPException(status_code=400, detail="Model did not return content.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Model did not return valid JSON.") from e

    try:
        Draft202012Validator(req.schema).validate(parsed)
    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail={"errors": [{"loc": list(e.path), "msg": e.message, "type": "schema"}]},
        ) from e

    return StructuredChatResponse(response=parsed)
