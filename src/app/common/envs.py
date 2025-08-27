# src/app/common/envs.py
from __future__ import annotations

from typing import Literal, cast

Env = Literal["dev", "tst", "acc", "prod"]

ALLOWED_ENVS: tuple[str, ...] = ("dev", "tst", "acc", "prod")

_ALIASES: dict[str, Env] = {
    "development": "dev",
    "production": "prod",
    "prod": "prod",
    "test": "tst",
    "testing": "tst",
    "uat": "tst",
    "stage": "acc",
    "staging": "acc",
    "acceptance": "acc",
    "acc": "acc",
    "tst": "tst",
    "dev": "dev",
}


def normalize_env(value: str) -> Env:
    v = (value or "").strip().lower()
    if v in ALLOWED_ENVS:
        return cast("Env", v)
    mapped = _ALIASES.get(v)
    if mapped:
        return mapped
    raise ValueError(f"invalid environment: {value}")
