from __future__ import annotations

from typing import Literal, TypedDict

Role = Literal["system", "user", "assistant", "tool", "reviewer"]


class Message(TypedDict):
    role: Role
    content: str


ChatHistory = list[Message]
