from __future__ import annotations
from typing import Sequence, Iterable
import os
import time
import httpx
import numpy as np


class EmbeddingClient:
    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        raise NotImplementedError


def _chunks(xs: Sequence[str], n: int) -> Iterable[Sequence[str]]:
    m = max(1, int(n))
    for i in range(0, len(xs), m):
        yield xs[i:i + m]


class _AADTokenProvider:
    def __init__(self, scope: str = "https://cognitiveservices.azure.com/.default") -> None:
        from azure.identity import DefaultAzureCredential
        self._cred = DefaultAzureCredential()
        self._scope = scope
        self._token: str | None = None
        self._exp: float = 0.0

    def get(self) -> str:
        now = time.time()
        if not self._token or now > self._exp - 60:
            t = self._cred.get_token(self._scope)
            self._token = t.token
            self._exp = float(t.expires_on)
        return self._token or ""


class AzureOpenAIClient(EmbeddingClient):
    def __init__(self, endpoint: str | None = None, deployment: str | None = None, api_key: str | None = None, api_version: str | None = None, dimensions: int | None = None, auth: str | None = None, timeout: float = 60.0) -> None:
        self.endpoint = (endpoint or os.getenv(
            "AZURE_OPENAI_ENDPOINT", "")).rstrip("/")
        self.deployment = deployment or os.getenv(
            "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "")
        self.key = api_key or os.getenv("AZURE_OPENAI_API_KEY", "")
        self.api_version = api_version or os.getenv(
            "AZURE_OPENAI_API_VERSION", "2024-10-21")
        self.dimensions = dimensions
        self.timeout = timeout
        self.auth = (auth or os.getenv("AZURE_OPENAI_AUTH", "key")).lower()
        self._aad = _AADTokenProvider() if self.auth == "aad" or not self.key else None

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/embeddings"
        out: list[list[float]] = []
        with httpx.Client(timeout=self.timeout) as s:
            for chunk in _chunks(texts, batch_size):
                payload = {"input": list(chunk)}
                if self.dimensions:
                    payload["dimensions"] = int(self.dimensions)
                params = {"api-version": self.api_version}
                headers = {"Content-Type": "application/json"}
                if self._aad:
                    headers["Authorization"] = f"Bearer {self._aad.get()}"
                else:
                    headers["api-key"] = self.key
                r = s.post(url, headers=headers, params=params, json=payload)
                r.raise_for_status()
                data = r.json()
                out.extend([d["embedding"] for d in data["data"]])
        return np.asarray(out, dtype=np.float32)


class OpenAIClient(EmbeddingClient):
    def __init__(self, model: str = "text-embedding-3-large", api_key: str | None = None, base_url: str | None = None, dimensions: int | None = None, timeout: float = 60.0) -> None:
        self.model = model
        self.key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url or os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.dimensions = dimensions
        self.timeout = timeout

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        out: list[list[float]] = []
        with httpx.Client(timeout=self.timeout) as s:
            for chunk in _chunks(texts, batch_size):
                payload = {"model": self.model, "input": list(chunk)}
                if self.dimensions:
                    payload["dimensions"] = int(self.dimensions)
                r = s.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
                out.extend([d["embedding"] for d in data["data"]])
        return np.asarray(out, dtype=np.float32)


class CohereClient(EmbeddingClient):
    def __init__(self, model: str = "embed-v4.0", api_key: str | None = None, output_dimension: int | None = None, input_type: str | None = "search_document", timeout: float = 60.0) -> None:
        self.model = model
        self.key = api_key or os.getenv("COHERE_API_KEY", "")
        self.output_dimension = output_dimension
        self.input_type = input_type
        self.timeout = timeout

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = "https://api.cohere.com/v2/embed"
        headers = {"Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        out: list[list[float]] = []
        with httpx.Client(timeout=self.timeout) as s:
            for chunk in _chunks(texts, batch_size):
                payload = {"model": self.model, "texts": list(chunk)}
                if self.input_type:
                    payload["input_type"] = self.input_type
                if self.output_dimension:
                    payload["output_dimension"] = int(self.output_dimension)
                r = s.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
                vecs = data.get("embeddings", {}).get("float") or data.get(
                    "embeddings", {}).get("embeddings")
                if vecs is None:
                    vecs = data["embeddings"]
                out.extend(vecs)
        return np.asarray(out, dtype=np.float32)


class VoyageClient(EmbeddingClient):
    def __init__(self, model: str = "voyage-3-large", api_key: str | None = None, output_dimension: int | None = None, input_type: str | None = "document", timeout: float = 60.0) -> None:
        self.model = model
        self.key = api_key or os.getenv("VOYAGE_API_KEY", "")
        self.output_dimension = output_dimension
        self.input_type = input_type
        self.timeout = timeout

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = "https://api.voyageai.com/v1/embeddings"
        headers = {"Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        out: list[list[float]] = []
        with httpx.Client(timeout=self.timeout) as s:
            for chunk in _chunks(texts, batch_size):
                payload = {"model": self.model, "input": list(chunk)}
                if self.input_type:
                    payload["input_type"] = self.input_type
                if self.output_dimension:
                    payload["output_dimension"] = int(self.output_dimension)
                r = s.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
                out.extend(data["data"][0]["embeddings"]
                           if "data" in data and "embeddings" in data["data"][0] else data["embeddings"])
        return np.asarray(out, dtype=np.float32)


class MistralClient(EmbeddingClient):
    def __init__(self, model: str = "mistral-embed", api_key: str | None = None, timeout: float = 60.0) -> None:
        self.model = model
        self.key = api_key or os.getenv("MISTRAL_API_KEY", "")
        self.timeout = timeout

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = "https://api.mistral.ai/v1/embeddings"
        headers = {"Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        out: list[list[float]] = []
        with httpx.Client(timeout=self.timeout) as s:
            for chunk in _chunks(texts, batch_size):
                payload = {"model": self.model, "input": list(chunk)}
                r = s.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
                out.extend([d["embedding"] for d in data["data"]])
        return np.asarray(out, dtype=np.float32)


def get_embedding_client(provider: str | None = None) -> EmbeddingClient:
    p = (provider or os.getenv("EMBEDDINGS_PROVIDER", "azure")).lower()
    if p == "azure":
        dims = os.getenv("EMBEDDINGS_DIMENSIONS")
        return AzureOpenAIClient(dimensions=int(dims) if dims else None)
    if p == "openai":
        dims = os.getenv("EMBEDDINGS_DIMENSIONS")
        return OpenAIClient(dimensions=int(dims) if dims else None)
    if p == "cohere":
        dims = os.getenv("EMBEDDINGS_DIMENSIONS")
        return CohereClient(output_dimension=int(dims) if dims else None)
    if p == "voyage":
        dims = os.getenv("EMBEDDINGS_DIMENSIONS")
        return VoyageClient(output_dimension=int(dims) if dims else None)
    if p == "mistral":
        return MistralClient()
    raise ValueError(f"Unknown embeddings provider: {provider}")
