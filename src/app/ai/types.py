from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

Role = Literal["system", "user", "assistant", "tool", "reviewer"]


class Message(TypedDict):
    role: Role
    content: str
    tool_calls: NotRequired[list[dict[str, Any]]]
    tool_call_id: NotRequired[str]
    name: NotRequired[str]


ChatHistory = list[Message]
