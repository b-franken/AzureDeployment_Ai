import asyncio
import sys
import types

import pytest

openai_module = types.ModuleType("openai")
openai_module.AsyncOpenAI = object
types_module = types.ModuleType("openai.types")
chat_module = types.ModuleType("openai.types.chat")
chat_module.ChatCompletionMessageParam = object
types_module.chat = chat_module
openai_module.types = types_module
sys.modules.setdefault("openai", openai_module)
sys.modules.setdefault("openai.types", types_module)
sys.modules.setdefault("openai.types.chat", chat_module)

from app.ai.arg_mapper import map_args_with_function_call


class FakeLLM:
    async def chat_raw(self, **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "test",
                                    "arguments": "{invalid}",
                                }
                            }
                        ]
                    }
                }
            ]
        }


async def fake_get_provider_and_model(provider, model):
    return FakeLLM(), "model"


def test_map_args_with_function_call_invalid_json(monkeypatch):
    monkeypatch.setattr("app.ai.arg_mapper.get_provider_and_model", fake_get_provider_and_model)

    async def run() -> None:
        await map_args_with_function_call("test", None, "input", None, None)

    with pytest.raises(ValueError) as exc:
        asyncio.run(run())
    assert "Expecting property name enclosed in double quotes" in str(exc.value)
