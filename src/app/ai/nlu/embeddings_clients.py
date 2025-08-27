from __future__ import annotations

import os
import time
from collections.abc import Iterable, Sequence
from typing import cast

import httpx
import numpy as np


class EmbeddingClient:
    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        raise NotImplementedError


def _chunks(xs: Sequence[str], n: int) -> Iterable[Sequence[str]]:
    m = max(1, int(n))
    for i in range(0, len(xs), m):
        yield xs[i : i + m]


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
    def __init__(
        self,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_key: str | None = None,
        api_version: str | None = None,
        dimensions: int | None = None,
        auth: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        ep_env = os.getenv("AZURE_OPENAI_ENDPOINT") or ""
        ep_base = endpoint if endpoint is not None else ep_env
        self.endpoint: str = (ep_base or "").rstrip("/")

        dep_env = os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT") or ""
        self.deployment: str = deployment if deployment is not None else dep_env

        key_env = os.getenv("AZURE_OPENAI_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env

        ver_env = os.getenv("AZURE_OPENAI_API_VERSION") or "2024-10-21"
        self.api_version: str = api_version if api_version is not None else ver_env

        self.dimensions: int | None = int(dimensions) if dimensions is not None else None
        self.timeout: float = float(timeout)

        auth_env = os.getenv("AZURE_OPENAI_AUTH") or "key"
        self.auth: str = (auth if auth is not None else auth_env).lower()
        self._aad: _AADTokenProvider | None = (
            _AADTokenProvider() if self.auth == "aad" or not self.key else None
        )

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/embeddings"
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"input": list(chunk)}
                    if self.dimensions is not None:
                        payload["dimensions"] = int(self.dimensions)
                    params = {"api-version": self.api_version}
                    headers: dict[str, str] = {"Content-Type": "application/json"}
                    if self._aad:
                        headers["Authorization"] = f"Bearer {self._aad.get()}"
                    else:
                        headers["api-key"] = self.key
                    r = s.post(url, headers=headers, params=params, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    out.extend([cast("list[float]", d["embedding"]) for d in data["data"]])
        except Exception as e:
            raise RuntimeError(f"azure embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class OpenAIClient(EmbeddingClient):
    def __init__(
        self,
        model: str = "text-embedding-3-large",
        api_key: str | None = None,
        base_url: str | None = None,
        dimensions: int | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model: str = model
        key_env = os.getenv("OPENAI_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env
        base_env = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        base = base_url if base_url is not None else base_env
        self.base_url: str = (base or "https://api.openai.com/v1").rstrip("/")
        self.dimensions: int | None = int(dimensions) if dimensions is not None else None
        self.timeout: float = float(timeout)

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"model": self.model, "input": list(chunk)}
                    if self.dimensions is not None:
                        payload["dimensions"] = int(self.dimensions)
                    r = s.post(url, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    out.extend([cast("list[float]", d["embedding"]) for d in data["data"]])
        except Exception as e:
            raise RuntimeError(f"openai embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class CohereClient(EmbeddingClient):
    def __init__(
        self,
        model: str = "embed-v4.0",
        api_key: str | None = None,
        output_dimension: int | None = None,
        input_type: str | None = "search_document",
        timeout: float = 60.0,
    ) -> None:
        self.model: str = model
        key_env = os.getenv("COHERE_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env
        self.output_dimension: int | None = (
            int(output_dimension) if output_dimension is not None else None
        )
        self.input_type: str | None = input_type
        self.timeout: float = float(timeout)

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = "https://api.cohere.com/v2/embed"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"model": self.model, "texts": list(chunk)}
                    if self.input_type:
                        payload["input_type"] = self.input_type
                    if self.output_dimension is not None:
                        payload["output_dimension"] = int(self.output_dimension)
                    r = s.post(url, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    emb_container = data.get("embeddings", {})
                    vecs: object
                    if isinstance(emb_container, dict):
                        vecs = emb_container.get("float") or emb_container.get("embeddings")
                    else:
                        vecs = emb_container
                    if vecs is None:
                        raise RuntimeError("invalid embeddings response from Cohere")
                    out.extend(cast("list[list[float]]", vecs))
        except Exception as e:
            raise RuntimeError(f"cohere embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class VoyageClient(EmbeddingClient):
    def __init__(
        self,
        model: str = "voyage-3-large",
        api_key: str | None = None,
        output_dimension: int | None = None,
        input_type: str | None = "document",
        timeout: float = 60.0,
    ) -> None:
        self.model: str = model
        key_env = os.getenv("VOYAGE_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env
        self.output_dimension: int | None = (
            int(output_dimension) if output_dimension is not None else None
        )
        self.input_type: str | None = input_type
        self.timeout: float = float(timeout)

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = "https://api.voyageai.com/v1/embeddings"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"model": self.model, "input": list(chunk)}
                    if self.input_type:
                        payload["input_type"] = self.input_type
                    if self.output_dimension is not None:
                        payload["output_dimension"] = int(self.output_dimension)
                    r = s.post(url, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    if "data" in data and "embeddings" in data["data"][0]:
                        out.extend(cast("list[list[float]]", data["data"][0]["embeddings"]))
                    else:
                        out.extend(cast("list[list[float]]", data["embeddings"]))
        except Exception as e:
            raise RuntimeError(f"voyage embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class MistralClient(EmbeddingClient):
    def __init__(
        self, model: str = "mistral-embed", api_key: str | None = None, timeout: float = 60.0
    ) -> None:
        self.model: str = model
        key_env = os.getenv("MISTRAL_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env
        self.timeout: float = float(timeout)

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = "https://api.mistral.ai/v1/embeddings"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"model": self.model, "input": list(chunk)}
                    r = s.post(url, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    out.extend([cast("list[float]", d["embedding"]) for d in data["data"]])
        except Exception as e:
            raise RuntimeError(f"mistral embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class LocalEmbeddingClient(EmbeddingClient):
    """Lightweight local embedding client using simple TF-IDF for classification."""

    def __init__(self, model_name: str = "tfidf") -> None:
        self.model_name = model_name
        self._vectorizer = None
        self._fallback_dim = 384  # Standard embedding dimension

    def _ensure_vectorizer(self) -> None:
        if self._vectorizer is None:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer

                # Simple TF-IDF vectorizer for lightweight classification
                self._vectorizer = TfidfVectorizer(
                    max_features=self._fallback_dim,
                    stop_words="english",
                    lowercase=True,
                    ngram_range=(1, 2),
                    min_df=1,
                    max_df=0.95,
                )
            except ImportError:
                # Ultra-lightweight fallback: hash-based features
                self._vectorizer = None

    def _simple_hash_embedding(self, text: str, dim: int = 384) -> list[float]:
        """Ultra-lightweight hash-based embedding as fallback."""
        import hashlib

        # Create multiple hash features
        features = [0.0] * dim
        words = text.lower().split()

        for i, word in enumerate(words):
            # Use different hash seeds for variety
            for seed in range(3):
                hash_val = int(hashlib.md5(f"{word}_{seed}".encode()).hexdigest(), 16)
                idx = hash_val % dim
                features[idx] += 1.0 / (i + 1)  # Weight by position

        # Normalize
        norm = sum(f * f for f in features) ** 0.5
        if norm > 0:
            features = [f / norm for f in features]

        return features

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)

        # Try TF-IDF if sklearn is available
        if self._vectorizer is not None:
            try:
                self._ensure_vectorizer()
                # Fit on the texts (simple approach for classification)
                tfidf_matrix = self._vectorizer.fit_transform(texts)
                return tfidf_matrix.toarray().astype(np.float32)
            except Exception:
                pass

        # Ultra-lightweight fallback: hash-based embeddings
        embeddings = []
        for text in texts:
            embedding = self._simple_hash_embedding(text, self._fallback_dim)
            embeddings.append(embedding)

        return np.asarray(embeddings, dtype=np.float32)


def get_embedding_client(provider: str | None = None) -> EmbeddingClient:
    base = provider if provider is not None else (os.getenv("EMBEDDINGS_PROVIDER") or "azure")
    p = base.lower()
    dims_str = os.getenv("EMBEDDINGS_DIMENSIONS")
    dims = int(dims_str) if dims_str else None
    if p == "azure":
        return AzureOpenAIClient(dimensions=dims)
    if p == "openai":
        return OpenAIClient(dimensions=dims)
    if p == "cohere":
        return CohereClient(output_dimension=dims)
    if p == "voyage":
        return VoyageClient(output_dimension=dims)
    if p == "mistral":
        return MistralClient()
    if p == "local":
        model_name = os.getenv("LOCAL_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        return LocalEmbeddingClient(model_name)
    raise ValueError(f"Unknown embeddings provider: {provider}")
