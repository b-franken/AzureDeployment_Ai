from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray


class CacheTierOptimizer(Protocol):
    async def predict_index(self, key: str, n_levels: int) -> int: ...
    async def recommend_index(self, key: str, value: Any, n_levels: int) -> int: ...

    async def observe_hit(self, key: str) -> None: ...
    async def observe_miss(self, key: str) -> None: ...


class EwmaOptimizer:
    def __init__(self, decay: float = 0.9, max_size: int = 2048) -> None:
        self._scores: OrderedDict[str, float] = OrderedDict()
        self._decay = float(decay)
        self._max = int(max_size)

    def _bump(self, key: str, v: float) -> None:
        s = self._scores.get(key, 0.0)
        s = s * self._decay + v
        self._scores[key] = s
        self._scores.move_to_end(key)
        if len(self._scores) > self._max:
            self._scores.popitem(last=False)

    async def observe_hit(self, key: str) -> None:
        self._bump(key, 1.0)

    async def observe_miss(self, key: str) -> None:
        self._bump(key, 0.0)

    async def predict_index(self, key: str, n_levels: int) -> int:
        s = self._scores.get(key, 0.0)
        if s >= 2.0:
            return 0
        if s >= 0.5:
            return min(1, n_levels - 1)
        return min(2, n_levels - 1)

    async def recommend_index(self, key: str, value: Any, n_levels: int) -> int:
        return await self.predict_index(key, n_levels)


class ProbaModel(Protocol):
    def predict_proba(self, texts: Sequence[str]) -> NDArray[np.floating[Any]]: ...


class EmbeddingsTierOptimizer:
    def __init__(self, model: ProbaModel, label_to_index: Sequence[int]) -> None:
        self._model = model
        self._map = list(label_to_index)

    async def observe_hit(self, key: str) -> None:
        return None

    async def observe_miss(self, key: str) -> None:
        return None

    async def _predict_label(self, key: str) -> int:
        probs = self._model.predict_proba([key])
        if not probs or not probs[0]:
            return 0
        row = probs[0]
        j = max(range(len(row)), key=row.__getitem__)
        if j >= len(self._map):
            return self._map[-1]
        return self._map[j]

    async def predict_index(self, key: str, n_levels: int) -> int:
        idx = await self._predict_label(key)
        return min(int(idx), n_levels - 1)

    async def recommend_index(self, key: str, value: Any, n_levels: int) -> int:
        return await self.predict_index(key, n_levels)
