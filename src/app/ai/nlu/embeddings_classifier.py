from __future__ import annotations

import torch
from sentence_transformers import SentenceTransformer
from torch import nn


class EmbeddingsClassifierService:
    def __init__(
        self,
        num_labels: int = 2,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        ckpt: str | None = None,
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.encoder = SentenceTransformer(model_name, device=str(self.device))
        dim_raw: int | None = self.encoder.get_sentence_embedding_dimension()
        if dim_raw is None:
            raise RuntimeError("encoder returned unknown embedding dimension")
        dim: int = dim_raw
        self.head = nn.Linear(dim, num_labels).to(self.device)
        self.softmax = nn.Softmax(dim=-1)
        if ckpt:
            state = torch.load(ckpt, map_location=self.device)
            self.head.load_state_dict(state)

    @torch.inference_mode()
    def predict_proba(self, texts: list[str]) -> torch.Tensor:
        if not texts:
            return torch.empty(0, self.head.out_features)
        emb = self.encoder.encode(
            list(texts), convert_to_tensor=True, device=str(self.device)
        )
        logits = self.head(emb)
        return self.softmax(logits)

    def save(self, path: str) -> None:
        torch.save(self.head.state_dict(), path)

    def fit(
        self,
        texts: list[str],
        labels: list[int],
        epochs: int = 10,
        lr: float = 1e-2,
        batch_size: int = 32,
    ) -> None:
        self.head.train()
        opt = torch.optim.AdamW(self.head.parameters(), lr=lr)
        loss_fn = nn.CrossEntropyLoss()
        X = self.encoder.encode(
            list(texts), convert_to_tensor=True, device=str(self.device)
        )
        y = torch.tensor(labels, dtype=torch.long, device=self.device)
        n = X.size(0)
        for _ in range(epochs):
            idx = torch.randperm(n, device=self.device)
            for i in range(0, n, batch_size):
                j = idx[i : i + batch_size]
                logits = self.head(X[j])
                loss = loss_fn(logits, y[j])
                opt.zero_grad()
                loss.backward()
                opt.step()
        self.head.eval()
