AVM_VERSIONS = {
    "network/virtual-network": "0.1.8",
    "key-vault/vault": "0.6.2",
    "storage/storage-account": "0.11.0",
    "web/site": "0.3.9",
}


def resolve(name: str, overrides: dict[str, str] | None = None) -> str:
    versions = dict(AVM_VERSIONS)
    if overrides:
        versions.update(overrides)
    return f"br/public:avm/res/{name}:{versions[name]}"
