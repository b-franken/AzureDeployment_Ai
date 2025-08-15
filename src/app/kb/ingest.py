from __future__ import annotations

import glob
import os

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL = SentenceTransformer("all-MiniLM-L6-v2")


def embed_corpus(root: str, out_path: str) -> None:
    files = [
        *glob.glob(os.path.join(root, "**/*.md"), recursive=True),
        *glob.glob(os.path.join(root, "**/*.tf"), recursive=True),
        *glob.glob(os.path.join(root, "**/*.yaml"), recursive=True),
    ]
    texts: list[str] = []
    metas: list[tuple[str, int]] = []
    for f in files:
        with open(f, errors="ignore") as fh:
            for i, line in enumerate(fh):
                if line.strip():
                    texts.append(line.strip())
                    metas.append((f, i + 1))
    embs = MODEL.encode(texts, convert_to_numpy=True)
    np.savez(out_path, embs=embs, texts=texts, metas=metas)
