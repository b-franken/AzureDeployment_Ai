import sys
import types
import importlib.machinery

import pytest

# Stub the openai module to avoid optional dependency during import
openai_stub = types.ModuleType("openai")
openai_stub.AsyncOpenAI = object
openai_stub.__spec__ = importlib.machinery.ModuleSpec("openai", loader=None)
types_stub = types.ModuleType("openai.types")
chat_stub = types.ModuleType("openai.types.chat")
chat_stub.ChatCompletionMessageParam = object
types_stub.chat = chat_stub
openai_stub.types = types_stub
sys.modules.setdefault("openai", openai_stub)
sys.modules.setdefault("openai.types", types_stub)
sys.modules.setdefault("openai.types.chat", chat_stub)

# Stub sentence_transformers to avoid heavy dependency
st_stub = types.ModuleType("sentence_transformers")
st_stub.SentenceTransformer = object
st_stub.__spec__ = importlib.machinery.ModuleSpec("sentence_transformers", loader=None)
sys.modules.setdefault("sentence_transformers", st_stub)

from app.ai.tools_router import _extract_json_object


def test_extract_json_object_valid_json():
    text = '{"tool": "demo", "args": {"a": 1}}'
    assert _extract_json_object(text) == {"tool": "demo", "args": {"a": 1}}


def test_extract_json_object_malformed_json():
    text = '{"tool": "demo", "args": {"a": 1}'  # missing closing brace
    with pytest.raises(ValueError):
        _extract_json_object(text)

