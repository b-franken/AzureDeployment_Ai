from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NLUPatterns:
    location_patterns: list[tuple[str, str]] = field(default_factory=lambda: [
        (r"\b(?:in|at|to|for)\s+(west\s*europe|westeurope)\b", "westeurope"),
        (r"\b(?:in|at|to|for)\s+(north\s*europe|northeurope)\b", "northeurope"),
        (r"\b(?:in|at|to|for)\s+(uk\s*south|uksouth)\b", "uksouth"),
        (r"\b(?:in|at|to|for)\s+(east\s*us|eastus)\b", "eastus"),
        (r"\bwest\s*europe\b", "westeurope"),
        (r"\bnorth\s*europe\b", "northeurope"),
        (r"\buk\s*south\b", "uksouth"),
        (r"\beast\s*us\b", "eastus"),
        (r"\beurope\b", "westeurope"),
    ])

    resource_patterns: dict[str, list[str]] = field(default_factory=lambda: {
        "resource_group": [
            r"resource\s+group\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,89})",
            r"rg\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,89})",
            r"(?:create|make|new|provision|deploy|setup|add)\s+(?:a\s+)?(?:resource\s+group|rg)\s+([a-z0-9][\w-]{0,89})",
            r"(?:new\s+)?resource\s+group\s+([a-z0-9][\w-]{0,89})",
        ],
        "storage": [
            r"storage\s+account\s+(?:named\s+|called\s+)?([a-z0-9]{3,24})",
            r"storage\s+(?:named\s+|called\s+)?([a-z0-9]{3,24})",
            r"(?:create|make|new|provision|deploy|setup|add)\s+(?:a\s+)?storage\s+(?:account\s+)?([a-z0-9]{3,24})",
            r"blob\s+storage\s+(?:named\s+|called\s+)?([a-z0-9]{3,24})",
        ],
        "webapp": [
            r"web\s*app\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"app\s+service\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"website\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"(?:create|make|new|provision|deploy|setup|add)\s+(?:a\s+)?(?:web\s*app|website|app\s+service)\s+([a-z0-9][\w-]{0,59})",
        ],
        "vm": [
            r"virtual\s+machine\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,79})",
            r"vm\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,79})",
            r"(?:create|make|new|provision|deploy|setup|add)\s+(?:a\s+)?(?:virtual\s+machine|vm)\s+([a-z0-9][\w-]{0,79})",
        ],
        "keyvault": [
            r"key\s*vault\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,23})",
            r"keyvault\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,23})",
            r"(?:create|make|new|provision|deploy|setup|add)\s+(?:a\s+)?(?:key\s*vault|keyvault)\s+([a-z0-9][\w-]{0,23})",
        ],
        "aks": [
            r"kubernetes\s+(?:cluster\s+)?(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"aks\s+(?:cluster\s+)?(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"k8s\s+(?:cluster\s+)?(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"(?:create|make|new|provision|deploy|setup|add)\s+(?:a\s+)?(?:kubernetes|aks|k8s)(?:\s+cluster)?\s+([a-z0-9][\w-]{0,59})",
        ],
        "acr": [
            r"container\s+registry\s+(?:named\s+|called\s+)?([a-z0-9]{5,50})",
            r"acr\s+(?:named\s+|called\s+)?([a-z0-9]{5,50})",
            r"docker\s+registry\s+(?:named\s+|called\s+)?([a-z0-9]{5,50})",
            r"(?:create|make|new|provision|deploy|setup|add)\s+(?:a\s+)?(?:container\s+registry|acr|docker\s+registry)\s+([a-z0-9]{5,50})",
        ],
        "sql": [
            r"sql\s+server\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"database\s+(?:server\s+)?(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"(?:create|make|new|provision|deploy|setup|add)\s+(?:a\s+)?(?:sql\s+server|database)\s+([a-z0-9][\w-]{0,59})",
        ],
        "vnet": [
            r"virtual\s+network\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"vnet\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{0,59})",
            r"(?:create|make|new|provision|deploy|setup|add)\s+(?:a\s+)?(?:virtual\s+network|vnet)\s+([a-z0-9][\w-]{0,59})",
        ],
    })

    intent_patterns: dict[str, list[str]] = field(default_factory=lambda: {
        "create": [
            r"\b(create|make|provision|deploy|setup|add|new|build|establish|launch)\b",
            r"\bneed\s+(?:a\s+)?(?:new|fresh)\b",
            r"\bspin\s+up\b",
            r"\bstand\s+up\b",
            r"\bbring\s+up\b",
        ],
        "delete": [
            r"\b(delete|remove|destroy|terminate|decommission|tear\s+down|clean\s+up)\b",
            r"\b(dispose|purge|wipe|eliminate)\b",
        ],
        "update": [
            r"\b(update|modify|change|alter|adjust|reconfigure|patch|upgrade|resize|expand|enhance)\b"
        ],
        "scale": [r"\b(scale|resize|expand|contract|grow|shrink|autoscale)\b"],
        "backup": [r"\b(backup|snapshot|archive|preserve)\b"],
        "restore": [r"\b(restore|recover|revert)\b"],
        "migrate": [r"\b(migrate|move|transfer|relocate|shift)\b"],
        "monitor": [r"\b(monitor|watch|track|alert)\b"],
        "secure": [r"\b(secure|harden|protect|encrypt|lock\s*down)\b"],
        "optimize": [r"\b(optimize|tune|reduce\s+cost|improve\s+performance)\b"],
        "validate": [r"\b(validate|check|verify|test|ensure|confirm)\b"],
        "cost_analyze": [r"\b(cost\s+analysis|analyze\s+cost|budget|forecast)\b"],
        "drift_check": [r"\b(drift|configuration\s+drift|detect\s+changes)\b"],
        "rollback": [r"\b(rollback|undo\s+deployment|previous\s+version)\b"],
    })

    keyword_hints: dict[str, list[str]] = field(default_factory=lambda: {
        "resource_group": ["resource group", "rg"],
        "storage": ["storage", "blob", "file"],
        "webapp": ["web", "app", "website", "service"],
        "vm": ["virtual machine", "vm", "server", "compute"],
        "keyvault": ["key vault", "keyvault", "secrets", "certificates"],
        "aks": ["kubernetes", "aks", "k8s", "container"],
        "acr": ["container registry", "acr", "docker"],
        "sql": ["sql", "database", "db"],
        "vnet": ["network", "vnet", "networking"],
    })

    contextual_resources: set[str] = field(default_factory=lambda: {"resource_group"})

    in_context_patterns: list[str] = field(default_factory=lambda: [
        r"\bin\s+(?:resource\s+group|rg)\s+",
        r"(?:resource\s+group|rg)\s+[a-z0-9][\w-]*"
    ])

    compliance_patterns: dict[str, str] = field(default_factory=lambda: {
        "gdpr": r"\b(gdpr|general\s+data\s+protection)\b",
        "hipaa": r"\b(hipaa|health\s+insurance\s+portability)\b",
        "pci_dss": r"\b(pci|payment\s+card\s+industry)\b",
    })


def get_nlu_patterns() -> NLUPatterns:
    return NLUPatterns()