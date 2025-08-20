import asyncio
import logging
import sys
import types

from pydantic import SecretStr

# Avoid heavy transformers dependency when importing openai
sys.modules.setdefault("transformers", types.ModuleType("transformers"))

from app.ai.llm import openai_provider as op


class DummyModels:
    async def list(self):
        raise RuntimeError("boom")


class DummyClient:
    def __init__(self):
        self.models = DummyModels()


class DummySettings:
    class llm:
        openai_api_key = SecretStr("key")
        openai_api_base = "https://example.com"
        openai_model = "gpt-4o-mini"


def test_list_models_logs_on_failure(monkeypatch, caplog):
    monkeypatch.setattr(op, "AsyncOpenAI", lambda **kwargs: DummyClient())
    monkeypatch.setattr(op, "get_settings", lambda: DummySettings())
    provider = op.OpenAIProvider()
    with caplog.at_level(logging.DEBUG):
        models = asyncio.run(provider.list_models())
    assert models == ["gpt-4o-mini", "gpt-4o", "gpt-5"]
    assert "Failed to list OpenAI models" in caplog.text
