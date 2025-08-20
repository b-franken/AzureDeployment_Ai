import pytest
from pydantic import SecretStr

from app.core.azure_auth import build_credential
from app.core.config import AzureConfig
from app.core.exceptions import ExternalServiceException


def test_build_credential_missing_service_principal_fields_raises():
    cfg = AzureConfig(auth_mode="service_principal")
    with pytest.raises(ValueError):
        build_credential(cfg, use_cache=False)


def test_openai_provider_list_models_error(monkeypatch):
    openai = pytest.importorskip("openai")
    from openai import OpenAIError
    import app.ai.llm.openai_provider as openai_provider

    class _DummyModels:
        async def list(self):
            raise OpenAIError("boom")

    class _DummyClient:
        models = _DummyModels()

    def _dummy_settings():
        class _LLM:
            openai_api_key = SecretStr("test")
            openai_api_base = "https://api.openai.com/v1"
            openai_model = "gpt-4o-mini"

        class _Settings:
            llm = _LLM()

        return _Settings()

    monkeypatch.setattr(openai_provider, "get_settings", _dummy_settings)
    provider = openai_provider.OpenAIProvider()
    provider._client = _DummyClient()
    import asyncio
    with pytest.raises(ExternalServiceException):
        asyncio.run(provider.list_models())
