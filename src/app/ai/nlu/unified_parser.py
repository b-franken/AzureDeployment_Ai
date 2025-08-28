from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, cast

if TYPE_CHECKING:
    from app.ai.nlu.embeddings_classifier import EmbeddingsClassifierService


class DeploymentIntent(Enum):
    create = "create"
    update = "update"
    delete = "delete"
    scale = "scale"
    backup = "backup"
    restore = "restore"
    migrate = "migrate"
    monitor = "monitor"
    secure = "secure"
    optimize = "optimize"
    validate = "validate"
    cost_analyze = "cost_analyze"
    drift_check = "drift_check"
    rollback = "rollback"


@dataclass
class UnifiedParseResult:
    text: str
    intent: DeploymentIntent
    confidence: float
    resource_type: str
    resource_name: str | None
    action: str
    parameters: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    advanced_context: dict[str, Any] = field(default_factory=dict)
    embeddings_scores: list[float] | None = None

    def to_provision_args(self) -> dict[str, Any]:
        d = dict(self.parameters)
        d["action"] = self.action
        return d

    def to_orchestrator_args(self) -> dict[str, Any] | None:
        try:
            from app.common.envs import normalize_env
        except Exception:

            def normalize_env(v: str) -> str:
                return "dev"

        rtype = self.resource_type
        params = dict(self.parameters)
        name = params.get("name")
        rg = params.get("resource_group")
        loc = params.get("location", "westeurope")
        env_in = params.get("environment", "dev")
        env = normalize_env(str(env_in))
        product: str | None = None
        spec_params: dict[str, Any] = {}
        if rtype == "webapp" and name and rg:
            plan_name = params.get("plan") or f"{name}-{env}-plan"
            runtime = params.get("runtime")
            sku = params.get("sku", "P1v3")
            spec_params = {
                "resource_group": rg,
                "location": loc,
                "name": name,
                "runtime": runtime,
                "plan": {"name": plan_name, "sku": sku, "linux": True},
                "tags": self.context.get("tags", {}),
            }
            product = "web_app"
        elif rtype == "storage" and name and rg:
            sku = params.get("sku", "Standard_LRS")
            access_tier = params.get("access_tier", "Hot")
            spec_params = {
                "resource_group": rg,
                "location": loc,
                "name": name,
                "sku": sku,
                "access_tier": access_tier,
                "tags": self.context.get("tags", {}),
            }
            product = "storage_account"
        else:
            return None
        return {
            "product": product,
            "backend": "auto",
            "env": env,
            "plan_only": False,
            "parameters": spec_params,
        }


def _to_scores_list(x: Any) -> list[float]:
    try:
        import numpy as np

        if isinstance(x, np.ndarray):
            return cast("list[float]", x.tolist()[0])
    except Exception:
        pass
    if hasattr(x, "detach"):
        try:
            return cast("list[float]", x.detach().cpu().tolist()[0])
        except Exception:
            return []
    if isinstance(x, list):
        if x and isinstance(x[0], list):
            return cast("list[float]", x[0])
        return cast("list[float]", x)
    return []


def safe_literal_search(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    return re.compile(re.escape(needle), re.IGNORECASE).search(haystack) is not None


class unified_nlu_parser:
    LOCATION_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        (r"\b(?:in|at|to|for)\s+(west\s*europe|westeurope)\b", "westeurope"),
        (r"\b(?:in|at|to|for)\s+(north\s*europe|northeurope)\b", "northeurope"),
        (r"\b(?:in|at|to|for)\s+(uk\s*south|uksouth)\b", "uksouth"),
        (r"\b(?:in|at|to|for)\s+(east\s*us|eastus)\b", "eastus"),
        (r"\bwest\s*europe\b", "westeurope"),
        (r"\bnorth\s*europe\b", "northeurope"),
        (r"\buk\s*south\b", "uksouth"),
        (r"\beast\s*us\b", "eastus"),
        (r"\beurope\b", "westeurope"),
    ]

    RESOURCE_PATTERNS: ClassVar[dict[str, list[str]]] = {
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
    }

    INTENT_PATTERNS: ClassVar[dict[DeploymentIntent, list[str]]] = {
        DeploymentIntent.create: [
            r"\b(create|make|provision|deploy|setup|add|new|build|establish|launch)\b",
            r"\bneed\s+(?:a\s+)?(?:new|fresh)\b",
            r"\bspin\s+up\b",
            r"\bstand\s+up\b",
            r"\bbring\s+up\b",
        ],
        DeploymentIntent.delete: [
            r"\b(delete|remove|destroy|terminate|decommission|tear\s+down|clean\s+up)\b",
            r"\b(dispose|purge|wipe|eliminate)\b",
        ],
        DeploymentIntent.update: [
            r"\b(update|modify|change|alter|adjust|reconfigure|patch|upgrade|resize|expand|enhance)\b"
        ],
        DeploymentIntent.scale: [r"\b(scale|resize|expand|contract|grow|shrink|autoscale)\b"],
        DeploymentIntent.backup: [r"\b(backup|snapshot|archive|preserve)\b"],
        DeploymentIntent.restore: [r"\b(restore|recover|revert)\b"],
        DeploymentIntent.migrate: [r"\b(migrate|move|transfer|relocate|shift)\b"],
        DeploymentIntent.monitor: [r"\b(monitor|watch|track|alert)\b"],
        DeploymentIntent.secure: [r"\b(secure|harden|protect|encrypt|lock\s*down)\b"],
        DeploymentIntent.optimize: [r"\b(optimize|tune|reduce\s+cost|improve\s+performance)\b"],
        DeploymentIntent.validate: [r"\b(validate|check|verify|test|ensure|confirm)\b"],
        DeploymentIntent.cost_analyze: [r"\b(cost\s+analysis|analyze\s+cost|budget|forecast)\b"],
        DeploymentIntent.drift_check: [r"\b(drift|configuration\s+drift|detect\s+changes)\b"],
        DeploymentIntent.rollback: [r"\b(rollback|undo\s+deployment|previous\s+version)\b"],
    }

    def __init__(
        self,
        use_embeddings: bool = False,
        embeddings_provider: str | None = None,
        num_labels: int = 2,
        ckpt: str | None = None,
        dimensions: int | None = None,
        local_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self.location_patterns: list[tuple[re.Pattern[str], str]] = [
            (re.compile(p, re.IGNORECASE), loc) for p, loc in self.LOCATION_PATTERNS
        ]
        self.resource_patterns: dict[str, list[re.Pattern[str]]] = {
            k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in self.RESOURCE_PATTERNS.items()
        }
        self.intent_patterns: dict[DeploymentIntent, list[re.Pattern[str]]] = {
            k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in self.INTENT_PATTERNS.items()
        }
        self._emb: EmbeddingsClassifierService | None = None
        if use_embeddings:
            self._emb = self._load_embeddings_service(
                embeddings_provider, num_labels, ckpt, dimensions, local_model_name
            )

    def _load_embeddings_service(
        self,
        provider: str | None,
        num_labels: int,
        ckpt: str | None,
        dimensions: int | None,
        local_model_name: str,
    ) -> EmbeddingsClassifierService:
        from app.ai.nlu.embeddings_classifier import EmbeddingsClassifierService

        return EmbeddingsClassifierService(
            num_labels=num_labels,
            provider=provider,
            dimensions=dimensions,
            ckpt=ckpt,
            local_model_name=local_model_name,
        )

    def parse(self, text: str) -> UnifiedParseResult:
        t = text.lower().strip()
        intent = self._detect_intent(t)
        rtype = self._detect_resource_type(t)
        rname = self._extract_resource_name(t, rtype)
        params = self._extract_parameters(t, rtype)
        if rname and "name" not in params:
            params["name"] = rname
        ctx = self._build_context(t, params)
        adv = self._build_advanced_context(t, intent, rtype)
        conf = self._confidence(t, intent, rtype, bool(rname))
        emb_scores: list[float] | None = None
        if self._emb:
            try:
                probs = self._emb.predict_proba([text])
                emb_scores = _to_scores_list(probs)
            except Exception:
                emb_scores = None
        action = self._action(intent, rtype)
        return UnifiedParseResult(
            text=text,
            intent=intent,
            confidence=conf,
            resource_type=rtype,
            resource_name=rname,
            action=action,
            parameters=params,
            context=ctx,
            advanced_context=adv,
            embeddings_scores=emb_scores,
        )

    def parse_action(self, text: str) -> tuple[str, dict[str, Any]]:
        r = self.parse(text)
        return r.action, r.parameters

    def _detect_intent(self, text: str) -> DeploymentIntent:
        scores: dict[DeploymentIntent, int] = {}
        for k, pats in self.intent_patterns.items():
            s = 0
            for pat in pats:
                if pat.search(text):
                    s += 2
            if s > 0:
                scores[k] = s
        if not scores:
            return DeploymentIntent.create
        return max(scores, key=lambda k: scores[k])

    def _detect_resource_type(self, text: str) -> str:
        scores: dict[str, int] = {}
        for rtype, pats in self.resource_patterns.items():
            s = 0
            for pat in pats:
                if pat.search(text):
                    s += 2
            keyword_hints: dict[str, list[str]] = {
                "resource_group": ["resource group", "rg"],
                "storage": ["storage", "blob", "file"],
                "webapp": ["web", "app", "website", "service"],
                "vm": ["virtual machine", "vm", "server", "compute"],
                "keyvault": ["key vault", "keyvault", "secrets", "certificates"],
                "aks": ["kubernetes", "aks", "k8s", "container"],
                "acr": ["container registry", "acr", "docker"],
                "sql": ["sql", "database", "db"],
                "vnet": ["network", "vnet", "networking"],
            }
            for hint in keyword_hints.get(rtype, []):
                if hint in text:
                    s += 1
            if s > 0:
                scores[rtype] = s
        if not scores:
            return "generic"
        return max(scores, key=lambda k: scores[k])

    def _extract_resource_name(self, text: str, rtype: str) -> str | None:
        if rtype in self.resource_patterns:
            for pat in self.resource_patterns[rtype]:
                m = pat.search(text)
                if m and m.groups():
                    return m.group(m.lastindex or 1)
        for pat2 in [
            re.compile(r"(?:named|called|name)\s+([a-z0-9][\w-]{2,79})", re.IGNORECASE),
            re.compile(r"([a-z0-9][\w-]{2,79})\s+(?:in|for|at)", re.IGNORECASE),
        ]:
            m2 = pat2.search(text)
            if m2:
                c = m2.group(1)
                if c not in {"in", "at", "to", "from", "with", "for", "the", "and", "or"}:
                    return c
        return None

    def _extract_parameters(self, text: str, rtype: str) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for pat, loc in self.location_patterns:
            if pat.search(text):
                params["location"] = loc
                break
        for pat in [
            re.compile(r"resource\s+group\s+([a-z0-9][\w-]{0,89})", re.IGNORECASE),
            re.compile(r"rg\s+([a-z0-9][\w-]{0,89})", re.IGNORECASE),
            re.compile(r"in\s+(?:resource\s+group|rg)\s+([a-z0-9][\w-]{0,89})", re.IGNORECASE),
        ]:
            m = pat.search(text)
            if m:
                params["resource_group"] = m.group(1)
                break
        m_env = re.compile(
            r"\b(dev|development|test|testing|staging|stage|prod|production|uat)\b", re.IGNORECASE
        ).search(text)
        if m_env:
            params["environment"] = m_env.group(1).lower()
        m_sku = re.compile(r"(?:sku|tier|size)\s+([a-z0-9_]+)", re.IGNORECASE).search(text)
        if m_sku:
            params["sku"] = m_sku.group(1).upper()
        if rtype == "storage":
            if safe_literal_search(text, "cool"):
                params["access_tier"] = "Cool"
            elif safe_literal_search(text, "hot"):
                params["access_tier"] = "Hot"
        return params

    def _build_context(self, text: str, params: dict[str, Any]) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "location": params.get("location", "westeurope"),
            "environment": params.get("environment", "dev"),
            "resource_group": params.get("resource_group", ""),
            "subscription_id": "",
            "tags": {
                "environment": params.get("environment", "dev"),
                "managed_by": "devops-ai",
                "created_date": datetime.now(UTC).isoformat(),
            },
        }
        if safe_literal_search(text, "high availability") or safe_literal_search(text, "ha"):
            ctx["high_availability"] = True
        if safe_literal_search(text, "disaster recovery") or safe_literal_search(text, "dr"):
            ctx["disaster_recovery"] = True
        return ctx

    def _build_advanced_context(
        self, text: str, intent: DeploymentIntent, rtype: str
    ) -> dict[str, Any]:
        adv: dict[str, Any] = {}
        comp: list[str] = []
        for name, pat in {
            "gdpr": re.compile(r"\b(gdpr|general\s+data\s+protection)\b", re.IGNORECASE),
            "hipaa": re.compile(r"\b(hipaa|health\s+insurance\s+portability)\b", re.IGNORECASE),
            "pci_dss": re.compile(r"\b(pci|payment\s+card\s+industry)\b", re.IGNORECASE),
        }.items():
            if pat.search(text):
                comp.append(name)
        if comp:
            adv["compliance_requirements"] = comp
        if any(s in text for s in ["encrypt", "secure", "private", "isolated"]):
            adv["security_enhanced"] = True
        if intent in {DeploymentIntent.update, DeploymentIntent.migrate}:
            if "blue green" in text or "blue-green" in text:
                adv["deployment_strategy"] = "blue_green"
            elif "canary" in text:
                adv["deployment_strategy"] = "canary"
            elif "rolling" in text:
                adv["deployment_strategy"] = "rolling"
        return adv

    def _confidence(self, text: str, intent: DeploymentIntent, rtype: str, has_name: bool) -> float:
        c = 0.5
        if intent != DeploymentIntent.create:
            c += 0.1
        if rtype != "generic":
            c += 0.2
        if has_name:
            c += 0.15
        if "resource group" in text or "rg" in text:
            c += 0.1
        if len(text.split()) > 10:
            c += 0.05
        return min(c, 1.0)

    def _action(self, intent: DeploymentIntent, rtype: str) -> str:
        if rtype == "generic":
            return intent.value
        m: dict[str, str] = {
            "aks": "aks",
            "storage": "storage",
            "webapp": "webapp",
            "vm": "vm",
            "sql": "sql",
            "keyvault": "keyvault",
            "vnet": "vnet",
            "acr": "acr",
            "resource_group": "rg",
        }
        res = m.get(rtype, rtype)
        return f"{intent.value}_{res}"


def parse_provision_request(text: str) -> UnifiedParseResult:
    return unified_nlu_parser(use_embeddings=True).parse(text)


def parse_action(text: str) -> tuple[str, dict[str, Any]]:
    return unified_nlu_parser(use_embeddings=True).parse_action(text)


def maybe_map_provision(text: str) -> dict[str, object] | None:
    r = parse_provision_request(text)
    if r.confidence < 0.3:
        return None
    args = r.to_orchestrator_args()
    if not isinstance(args, dict):
        return None
    return {"tool": "azure_provision", "args": {"request": text}}


async def maybe_map_provision_async(text: str) -> dict[str, object] | None:
    # Try fast rule-based parsing first (no embeddings)
    r = unified_nlu_parser(use_embeddings=False).parse(text)
    if r.confidence >= 0.5:  # Higher threshold for rule-based confidence
        args = r.to_orchestrator_args()
        if isinstance(args, dict):
            return {"tool": "azure_provision", "args": {"request": text}}

    # Only use embeddings if rule-based parsing has low confidence
    r = parse_provision_request(text)
    if r.confidence >= 0.3:
        args = r.to_orchestrator_args()
        if isinstance(args, dict):
            return {"tool": "azure_provision", "args": {"request": text}}

    # LLM parsing as final fallback (this doesn't use embeddings for classification)
    from app.ai.nlu.llm_parser import parse_with_llm

    r2 = await parse_with_llm(text)
    args2 = r2.to_orchestrator_args()
    if not isinstance(args2, dict):
        return None
    return {"tool": "azure_provision", "args": {"request": text}}
