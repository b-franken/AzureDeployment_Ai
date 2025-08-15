from __future__ import annotations


def standard_tags(
    extra: dict[str, str] | None, owner: str | None, env: str | None
) -> dict[str, str]:
    base: dict[str, str] = {"provisioned-by": "devops-bot"}
    if owner:
        base["owner"] = owner
    if env:
        base["env"] = env
    if extra:
        base.update({k: str(v) for k, v in extra.items() if v is not None})
    return base
