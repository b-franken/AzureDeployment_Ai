from __future__ import annotations

import re

from app.core.config import settings

ALLOWED_LOCATIONS = tuple(settings.azure.allowed_locations)

LOCATION_ALIASES = {
    "west europe": "westeurope",
    "north europe": "northeurope",
    "uk south": "uksouth",
    "east us": "eastus",
    "west us": "westus",
}

_NAME_PATTERNS: dict[str, re.Pattern[str]] = {
    "storage": re.compile(r"^[a-z0-9]{3,24}$"),
    "webapp": re.compile(r"^[a-z][a-z0-9-]{1,59}$"),
    "vnet": re.compile(r"^[a-zA-Z0-9-]{2,64}$"),
    "acr": re.compile(r"^[a-zA-Z0-9]{5,50}$"),
    "sql_server": re.compile(r"^[a-z0-9-]{1,63}$"),
    "generic": re.compile(r"^[a-zA-Z0-9-_.]{1,80}$"),
}


def validate_name(kind: str, value: str | None) -> bool:
    if not value:
        return False
    pat = _NAME_PATTERNS.get(kind) or _NAME_PATTERNS["generic"]
    return bool(pat.match(value))


def validate_location(loc: str | None) -> bool:
    if not loc:
        return False
    loc_lower = loc.lower().strip()
    if loc_lower in ALLOWED_LOCATIONS:
        return True
    if loc_lower in LOCATION_ALIASES:
        aliased = LOCATION_ALIASES[loc_lower]
        return aliased in ALLOWED_LOCATIONS
    return False


def normalize_location(loc: str) -> str:
    loc_lower = loc.lower().strip()
    return LOCATION_ALIASES.get(loc_lower, loc_lower)


def validate_scope(scope: str | None) -> bool:
    if not scope:
        return False
    if not scope.startswith("/subscriptions/"):
        return False
    return "/resourceGroups/" in scope or "/providers/" in scope
