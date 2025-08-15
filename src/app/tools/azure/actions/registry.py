from __future__ import annotations

import difflib
import importlib
import re
from collections.abc import Callable, Iterable
from typing import Any

ActionFn = Callable[..., Any]

_ACTIONS: dict[str, ActionFn] = {}
_LOADED = False


def _bind(mod: str, attr: str) -> str:
    return f"app.tools.azure.actions.{mod}:{attr}"


_LAZY_BINDINGS: dict[str, str] = {
    "create_rg": _bind(
        "resource_groups",
        "create_resource_group",
    ),
    "create_storage": _bind(
        "storage",
        "create_storage_account",
    ),
    "create_blob_container": _bind(
        "storage",
        "create_blob_container",
    ),
    "create_file_share": _bind(
        "storage",
        "create_file_share",
    ),
    "create_vnet": _bind(
        "network",
        "create_vnet",
    ),
    "create_subnet": _bind(
        "network",
        "create_subnet",
    ),
    "create_public_ip": _bind(
        "network",
        "create_public_ip",
    ),
    "create_nsg": _bind(
        "network",
        "create_nsg",
    ),
    "create_lb": _bind(
        "network",
        "create_lb",
    ),
    "create_app_gateway": _bind(
        "network",
        "create_app_gateway",
    ),
    "create_plan": _bind(
        "webapp",
        "create_plan",
    ),
    "create_webapp": _bind(
        "webapp",
        "create_webapp",
    ),
    "create_acr": _bind(
        "acr",
        "create_registry",
    ),
    "create_aks": _bind(
        "aks",
        "create_aks",
    ),
    "create_vm": _bind(
        "compute",
        "create_vm",
    ),
    "create_sql": _bind(
        "sql",
        "create_sql",
    ),
    "create_keyvault": _bind(
        "keyvault",
        "create_keyvault",
    ),
    "set_keyvault_secret": _bind(
        "keyvault",
        "set_keyvault_secret",
    ),
    "create_cosmos": _bind(
        "cosmos",
        "create_cosmos_account",
    ),
    "create_sp": _bind(
        "iam",
        "create_service_principal",
    ),
    "assign_role": _bind(
        "iam",
        "assign_role",
    ),
    "create_log_analytics_workspace": _bind(
        "monitor",
        "create_log_analytics_workspace",
    ),
    "create_app_insights": _bind(
        "monitor",
        "create_app_insights",
    ),
    "create_user_assigned_identity": _bind(
        "identity",
        "create_user_assigned_identity",
    ),
    "create_redis": _bind(
        "redis",
        "create_redis",
    ),
    "create_private_dns_zone": _bind(
        "private_dns",
        "create_private_dns_zone",
    ),
    "link_private_dns_zone": _bind(
        "private_dns",
        "link_private_dns_zone",
    ),
    "create_private_endpoint": _bind(
        "private_link",
        "create_private_endpoint",
    ),
}

_ALIASES_BASE: dict[str, str] = {
    "create_resource_group": "create_rg",
    "resource_group_create": "create_rg",
    "new_resource_group": "create_rg",
    "make_resource_group": "create_rg",
    "rg_create": "create_rg",
    "create_storage_account": "create_storage",
    "storage_account_create": "create_storage",
    "create_web_app": "create_webapp",
    "webapp_create": "create_webapp",
    "create_container_registry": "create_acr",
    "create_kubernetes_cluster": "create_aks",
    "create_virtual_network": "create_vnet",
    "create_virtual_machine": "create_vm",
    "create_sql_server": "create_sql",
    "create_key_vault": "create_keyvault",
    "create_log_analytics": "create_log_analytics_workspace",
    "create_application_insights": "create_app_insights",
    "create_managed_identity": "create_user_assigned_identity",
    "create_user_assigned_managed_identity": "create_user_assigned_identity",
    "create_cache": "create_redis",
    "create_private_dns": "create_private_dns_zone",
    "link_private_dns": "link_private_dns_zone",
    "create_pe": "create_private_endpoint",
}

_ALIAS_LOOKUP: dict[str, str] = {}

_NORMALIZE_RE = re.compile(r"[^a-z0-9_]+")

_VERBS_CREATE: list[str] = ["create", "make", "new", "provision", "ensure", "setup", "add"]
_VERBS_SET: list[str] = ["set", "create", "add", "put", "update"]
_VERBS_ASSIGN: list[str] = ["assign", "grant", "add", "attach"]

_OBJ_SYNONYMS: dict[str, list[str]] = {
    "rg": ["resource_group", "resource group", "rg"],
    "storage": ["storage_account", "storage account", "sa"],
    "blob_container": ["blob_container", "blob container", "container"],
    "file_share": ["file_share", "file share", "fileshare"],
    "vnet": ["virtual_network", "virtual network", "vnet"],
    "subnet": ["subnet"],
    "public_ip": ["public_ip", "public ip", "pip"],
    "nsg": ["network_security_group", "network security group", "nsg"],
    "lb": ["load_balancer", "load balancer", "lb"],
    "app_gateway": ["application_gateway", "application gateway", "app gateway", "appgw"],
    "plan": ["app_service_plan", "app service plan", "plan"],
    "webapp": ["webapp", "web app", "app service", "website"],
    "acr": ["container_registry", "container registry", "acr"],
    "aks": ["kubernetes_cluster", "kubernetes cluster", "aks"],
    "vm": ["virtual_machine", "virtual machine", "vm"],
    "sql": ["sql_server", "sql server", "sql"],
    "keyvault": ["key_vault", "key vault", "keyvault", "kv"],
    "cosmos": ["cosmos_db", "cosmos db", "cosmos"],
    "sp": ["service_principal", "service principal", "sp"],
    "role": ["role", "rbac role", "role assignment"],
    "keyvault_secret": ["keyvault secret", "key vault secret", "kv secret", "secret"],
    "log_analytics_workspace": ["log analytics workspace", "law", "workspace"],
    "app_insights": ["application insights", "app insights", "insights"],
    "user_assigned_identity": ["user assigned identity", "uami", "managed identity"],
    "redis": ["redis", "cache", "azure cache for redis"],
    "private_dns_zone": ["private dns zone", "pdns zone"],
    "private_endpoint": ["private endpoint", "pe"],
}


def _normalize(name: str) -> str:
    s = name.strip().lower()
    s = s.replace("-", "_").replace(" ", "_")
    s = _NORMALIZE_RE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def register_action(name: str, fn: ActionFn) -> None:
    if not name or not callable(fn):
        raise ValueError("invalid action registration")
    if name in _ACTIONS:
        raise ValueError(f"action already registered: {name}")
    _ACTIONS[name] = fn


def action(name: str) -> Callable[[ActionFn], ActionFn]:
    def _decorator(fn: ActionFn) -> ActionFn:
        register_action(name, fn)
        return fn

    return _decorator


def _resolve(binding: str) -> ActionFn:
    mod_name, sep, attr = binding.partition(":")
    if not sep:
        raise ImportError(f"invalid binding: {binding}")
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, attr, None)
    if not callable(fn):
        raise ImportError(f"callable not found: {binding}")
    return fn


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    for name, binding in _LAZY_BINDINGS.items():
        if name not in _ACTIONS:
            _ACTIONS[name] = _resolve(binding)
    _build_aliases()
    _LOADED = True


def _object_terms(canon: str) -> list[str]:
    if canon.startswith("create_"):
        obj = canon[len("create_") :]
    elif canon.startswith("set_"):
        obj = canon[len("set_") :]
    elif canon.startswith("assign_"):
        obj = canon[len("assign_") :]
    else:
        obj = canon
    parts = obj.split("_")
    key = obj
    if key in _OBJ_SYNONYMS:
        return _OBJ_SYNONYMS[key]
    if parts and parts[0] in _OBJ_SYNONYMS:
        return _OBJ_SYNONYMS[parts[0]]
    return [obj.replace("_", " "), obj]


def _add_alias(alias_map: dict[str, str], alias: str, canon: str) -> None:
    alias_map.setdefault(_normalize(alias), canon)


def _build_aliases() -> None:
    global _ALIAS_LOOKUP
    alias_map: dict[str, str] = {}
    for k, v in _ALIASES_BASE.items():
        _add_alias(alias_map, k, v)
    for canon in list(_ACTIONS.keys()):
        n = _normalize(canon)
        _add_alias(alias_map, n, canon)
        _add_alias(alias_map, n.replace("create_", ""), canon)
        _add_alias(alias_map, n.replace("_", ""), canon)
        _add_alias(alias_map, n.replace("_", " "), canon)
        _add_alias(alias_map, n.replace("_", "-"), canon)
        terms = _object_terms(canon)
        if canon.startswith("create_"):
            for t in terms:
                for v in _VERBS_CREATE:
                    _add_alias(alias_map, f"{v} {t}", canon)
        elif canon.startswith("set_"):
            for t in terms + _OBJ_SYNONYMS.get("keyvault_secret", []):
                for v in _VERBS_SET:
                    _add_alias(alias_map, f"{v} {t}", canon)
        elif canon.startswith("assign_"):
            for t in terms + _OBJ_SYNONYMS.get("role", []):
                for v in _VERBS_ASSIGN:
                    _add_alias(alias_map, f"{v} {t}", canon)
        if canon == "create_public_ip":
            for v in _VERBS_CREATE:
                _add_alias(alias_map, f"{v} public ip address", canon)
        if canon == "create_nsg":
            for v in _VERBS_CREATE:
                _add_alias(alias_map, f"{v} nsg", canon)
                _add_alias(alias_map, f"{v} network security group", canon)
        if canon == "create_lb":
            for v in _VERBS_CREATE:
                _add_alias(alias_map, f"{v} load balancer", canon)
                _add_alias(alias_map, f"{v} lb", canon)
        if canon == "create_app_gateway":
            for v in _VERBS_CREATE:
                _add_alias(alias_map, f"{v} application gateway", canon)
                _add_alias(alias_map, f"{v} app gateway", canon)
        if canon == "set_keyvault_secret":
            for v in _VERBS_SET:
                _add_alias(alias_map, f"{v} secret", canon)
                _add_alias(alias_map, f"{v} kv secret", canon)
    _ALIAS_LOOKUP = alias_map


def _closest(name: str) -> str | None:
    pool = list(_ALIAS_LOOKUP.keys())
    if not pool:
        return None
    matches = difflib.get_close_matches(_normalize(name), pool, n=1, cutoff=0.7)
    return matches[0] if matches else None


def available_actions() -> Iterable[str]:
    _ensure_loaded()
    return _ACTIONS.keys()


def action_names_with_aliases() -> Iterable[str]:
    _ensure_loaded()
    return sorted(set(list(_ACTIONS.keys()) + list(_ALIAS_LOOKUP.keys())))


def resolve_action(name: str) -> tuple[str | None, ActionFn | None]:
    _ensure_loaded()
    if not name:
        return None, None
    key = _normalize(name)
    canon = _ALIAS_LOOKUP.get(key)
    if not canon:
        near = _closest(key)
        if near:
            canon = _ALIAS_LOOKUP.get(near)
    if not canon and key in _ACTIONS:
        canon = key
    fn = _ACTIONS.get(canon) if canon else None
    return canon, fn


def get_action(name: str) -> ActionFn | None:
    _, fn = resolve_action(name)
    return fn


ACTION_MAP = _ACTIONS

__all__ = [
    "ACTION_MAP",
    "available_actions",
    "action_names_with_aliases",
    "resolve_action",
    "get_action",
    "register_action",
    "action",
]
