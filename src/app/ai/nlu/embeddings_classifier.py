from __future__ import annotations

import os
from collections.abc import Sequence

import numpy as np

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
        self._num_labels = int(num_labels)
        if dimensions is not None:
            os.environ["EMBEDDINGS_DIMENSIONS"] = str(int(dimensions))
        self._provider = (provider or os.getenv("EMBEDDINGS_PROVIDER", "azure")).lower()
        self._enc = None if self._provider == "local" else get_embedding_client(self._provider)
        self._W: np.ndarray | None = None
        self._b: np.ndarray | None = None
        self._ckpt = ckpt
        self._local_model_name = local_model_name
        self._local_encoder = None
        if ckpt:
            data = np.load(ckpt)
            self._W = data["W"]
            self._b = data["b"]

    def _ensure_params(self, dim: int) -> None:
        if self._W is None or self._b is None:
            self._W = np.zeros((self._num_labels, dim), dtype=np.float32)
            self._b = np.zeros((self._num_labels,), dtype=np.float32)

    def _encode_local(self, texts: Sequence[str]) -> np.ndarray:
        if self._local_encoder is None:
            try:
                import torch  # noqa: F401
                from sentence_transformers import SentenceTransformer
            except Exception as e:
                raise RuntimeError(
                    "local embeddings require torch and sentence-transformers"
                ) from e
            self._local_encoder = SentenceTransformer(self._local_model_name)
        vecs = self._local_encoder.encode(
            list(texts), convert_to_numpy=True, normalize_embeddings=False
        )
        return np.asarray(vecs, dtype=np.float32)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        if self._provider == "local":
            return self._encode_local(texts)
        if self._enc is None:
            self._enc = get_embedding_client(self._provider)
        return self._enc.encode(list(texts))

    def predict_proba(self, texts: Sequence[str]) -> np.ndarray:
        X = self._encode(texts)
        if X.size == 0:
            return np.empty((0, self._num_labels), dtype=np.float32)
        self._ensure_params(X.shape[1])
        Z = X @ self._W.T + self._b
        Z = Z - Z.max(axis=1, keepdims=True)
        P = np.exp(Z, dtype=np.float32)
        P = P / P.sum(axis=1, keepdims=True)
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
        n, d = X.shape
        self._ensure_params(d)
        for _ in range(int(epochs)):
            idx = np.random.permutation(n)
            for s in range(0, n, int(batch_size)):
                e = min(s + int(batch_size), n)
                j = idx[s:e]
                Xb = X[j]
                yb = y[j]
                Z = Xb @ self._W.T + self._b
                Z = Z - Z.max(axis=1, keepdims=True)
                expZ = np.exp(Z)
                P = expZ / expZ.sum(axis=1, keepdims=True)
                Y = np.eye(self._num_labels, dtype=np.float32)[yb]
                dZ = (P - Y) / Xb.shape[0]
                gW = dZ.T @ Xb + l2 * self._W
                gb = dZ.sum(axis=0)
                self._W = self._W - lr * gW
                self._b = self._b - lr * gb

    def save(self, path: str) -> None:
        np.savez_compressed(path, W=self._W, b=self._b)
