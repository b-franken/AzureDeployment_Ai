import logging
import sys
import types

# Avoid heavy transformers dependency when importing tools_router
sys.modules.setdefault("transformers", types.ModuleType("transformers"))

emb_module = types.ModuleType("embeddings_classifier")
emb_module.EmbeddingsClassifierService = object
sys.modules["app.ai.nlu.embeddings_classifier"] = emb_module

from app.ai.tools_router import _extract_json_object


def test_extract_json_logs_on_failure(caplog):
    text = """```json
{"foo": 1,,}
```"""
    with caplog.at_level(logging.DEBUG):
        assert _extract_json_object(text) is None
    assert "Failed to parse JSON object" in caplog.text
