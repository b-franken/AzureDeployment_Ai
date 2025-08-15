from __future__ import annotations


def pick_backend(product: str, env: str, requested: str) -> str:
    if requested and requested != "auto":
        if requested in ["sdk", "terraform", "bicep"]:
            return requested
        return "sdk"

    if env == "prod":
        return "terraform"

    if product == "web_app":
        return "sdk"

    if product == "storage_account":
        return "sdk"

    return "sdk"
