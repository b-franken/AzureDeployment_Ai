from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.ai.nlu.embeddings_clients import get_embedding_client


class EmbeddingsClassifierService:
    def __init__(
        self,
        num_labels: int = 2,
        provider: str | None = None,
        dimensions: int | None = None,
        ckpt: str | None = None,
        local_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self._num_labels: int = int(num_labels)
        if dimensions is not None:
            os.environ["EMBEDDINGS_DIMENSIONS"] = str(int(dimensions))

        env_provider: str | None = os.getenv("EMBEDDINGS_PROVIDER")
        base_provider: str | None = provider if provider is not None else env_provider
        provider_value: str = base_provider or "azure"
        self._provider: str = provider_value.lower()

        self._enc: Any | None = (
            None if self._provider == "local" else get_embedding_client(self._provider)
        )

        self._W: NDArray[np.float32] | None = None
        self._b: NDArray[np.float32] | None = None
        self._ckpt: str | None = ckpt
        self._local_model_name: str = local_model_name
        self._local_encoder: Any | None = None

        if ckpt:
            data = np.load(ckpt)
            self._W = np.asarray(data["W"], dtype=np.float32)
            self._b = np.asarray(data["b"], dtype=np.float32)

    def _ensure_params(self, dim: int) -> None:
        if self._W is None or self._b is None:
            self._W = np.zeros((self._num_labels, dim), dtype=np.float32)
            self._b = np.zeros((self._num_labels,), dtype=np.float32)

    def _encode_local(self, texts: Sequence[str]) -> NDArray[np.float32]:
        if self._local_encoder is None:
            try:
                import torch  # noqa: F401
                from sentence_transformers import SentenceTransformer
            except Exception as e:
                raise RuntimeError(
                    "local embeddings require torch and sentence-transformers"
                ) from e
            self._local_encoder = SentenceTransformer(self._local_model_name)
        enc = self._local_encoder
        assert enc is not None
        vecs = enc.encode(list(texts), convert_to_numpy=True, normalize_embeddings=False)
        return np.asarray(vecs, dtype=np.float32)

    def _encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        if self._provider == "local":
            return self._encode_local(texts)
        if self._enc is None:
            self._enc = get_embedding_client(self._provider)
        enc = self._enc
        assert enc is not None
        vecs = enc.encode(list(texts))
        return np.asarray(vecs, dtype=np.float32)

    def predict_proba(self, texts: Sequence[str]) -> NDArray[np.float32]:
        X = self._encode(texts)
        if X.size == 0:
            return np.empty((0, self._num_labels), dtype=np.float32)
        self._ensure_params(int(X.shape[1]))
        W = self._W
        b = self._b
        assert W is not None and b is not None
        Z = X @ W.T + b
        Z = Z - Z.max(axis=1, keepdims=True)
        Z = Z.astype(np.float32, copy=False)
        expZ = np.exp(Z)
        P = expZ / expZ.sum(axis=1, keepdims=True)
        return P.astype(np.float32)

    def fit(
        self,
        texts: Sequence[str],
        labels: Sequence[int],
        epochs: int = 10,
        lr: float = 1e-2,
        batch_size: int = 32,
        l2: float = 0.0,
    ) -> None:
        X = self._encode(texts)
        y = np.asarray(labels, dtype=np.int64)
        if X.size == 0:
            return
        n, d = int(X.shape[0]), int(X.shape[1])
        self._ensure_params(d)
        W = self._W
        b = self._b
        assert W is not None and b is not None
        for _ in range(int(epochs)):
            idx = np.random.permutation(n)
            for s in range(0, n, int(batch_size)):
                e = min(s + int(batch_size), n)
                j = idx[s:e]
                Xb = X[j]
                yb = y[j]
                Z = Xb @ W.T + b
                Z = Z - Z.max(axis=1, keepdims=True)
                expZ = np.exp(Z)
                P = expZ / expZ.sum(axis=1, keepdims=True)
                Y = np.eye(self._num_labels, dtype=np.float32)[yb]
                dZ = (P - Y) / float(Xb.shape[0])
                gW = dZ.T @ Xb + float(l2) * W
                gb = dZ.sum(axis=0)
                W = W - float(lr) * gW
                b = b - float(lr) * gb
        self._W = W
        self._b = b

    def save(self, path: str) -> None:
        W = self._W
        b = self._b
        if W is None or b is None:
            raise RuntimeError("cannot save classifier before initialization or training")
        np.savez_compressed(path, W=W, b=b)
