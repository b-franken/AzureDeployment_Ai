from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Protocol

import redis.asyncio as redis


class DeploymentState(Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    APPROVED = "approved"
    PROVISIONING = "provisioning"
    CONFIGURING = "configuring"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class StateTransition(Enum):
    START = "start"
    VALIDATE = "validate"
    APPROVE = "approve"
    PROVISION = "provision"
    CONFIGURE = "configure"
    VERIFY = "verify"
    COMPLETE = "complete"
    FAIL = "fail"
    ROLLBACK = "rollback"
    CANCEL = "cancel"


@dataclass
class DeploymentContext:
    deployment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subscription_id: str = ""
    resource_group: str = ""
    location: str = "westeurope"
    environment: str = "dev"
    initiated_by: str = ""
    initiated_at: datetime = field(default_factory=datetime.utcnow)
    state: DeploymentState = DeploymentState.PENDING
    state_history: list[tuple[DeploymentState, datetime]] = field(default_factory=list)
    resources: list[dict[str, Any]] = field(default_factory=list)
    deployed_resources: list[dict[str, Any]] = field(default_factory=list)
    validation_results: dict[str, Any] = field(default_factory=dict)
    error_details: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    timeout_minutes: int = 60
    approval_token: str | None = None
    rollback_enabled: bool = True
    dry_run: bool = False


class StateHandler(Protocol):
    async def handle(self, context: DeploymentContext) -> tuple[bool, DeploymentContext]: ...


class DeploymentStateMachine:
    def __init__(self, redis_client: redis.Redis | None = None):
        self.redis_client = redis_client
        self.state_handlers: dict[DeploymentState, StateHandler] = {}
        self.transitions: dict[tuple[DeploymentState, StateTransition], DeploymentState] = {
            (DeploymentState.PENDING, StateTransition.VALIDATE): DeploymentState.VALIDATING,
            (DeploymentState.VALIDATING, StateTransition.APPROVE): DeploymentState.APPROVED,
            (DeploymentState.APPROVED, StateTransition.PROVISION): DeploymentState.PROVISIONING,
            (DeploymentState.PROVISIONING, StateTransition.CONFIGURE): DeploymentState.CONFIGURING,
            (DeploymentState.CONFIGURING, StateTransition.VERIFY): DeploymentState.VERIFYING,
            (DeploymentState.VERIFYING, StateTransition.COMPLETE): DeploymentState.COMPLETED,
            (DeploymentState.VALIDATING, StateTransition.FAIL): DeploymentState.FAILED,
            (DeploymentState.PROVISIONING, StateTransition.FAIL): DeploymentState.FAILED,
            (DeploymentState.CONFIGURING, StateTransition.FAIL): DeploymentState.FAILED,
            (DeploymentState.VERIFYING, StateTransition.FAIL): DeploymentState.FAILED,
            (DeploymentState.FAILED, StateTransition.ROLLBACK): DeploymentState.ROLLING_BACK,
            (DeploymentState.ROLLING_BACK, StateTransition.COMPLETE): DeploymentState.ROLLED_BACK,
            (DeploymentState.PENDING, StateTransition.CANCEL): DeploymentState.CANCELLED,
            (DeploymentState.VALIDATING, StateTransition.CANCEL): DeploymentState.CANCELLED,
            (DeploymentState.APPROVED, StateTransition.CANCEL): DeploymentState.CANCELLED,
        }
        self._initialize_handlers()

    def _initialize_handlers(self) -> None:
        self.state_handlers[DeploymentState.VALIDATING] = ValidationHandler()
        self.state_handlers[DeploymentState.APPROVED] = ApprovalHandler()
        self.state_handlers[DeploymentState.PROVISIONING] = ProvisioningHandler()
        self.state_handlers[DeploymentState.CONFIGURING] = ConfigurationHandler()
        self.state_handlers[DeploymentState.VERIFYING] = VerificationHandler()
        self.state_handlers[DeploymentState.ROLLING_BACK] = RollbackHandler()

    async def execute(self, context: DeploymentContext) -> DeploymentContext:
        start_time = datetime.utcnow()
        timeout = timedelta(minutes=context.timeout_minutes)

        while context.state not in [
            DeploymentState.COMPLETED,
            DeploymentState.FAILED,
            DeploymentState.ROLLED_BACK,
            DeploymentState.CANCELLED,
        ]:
            if datetime.utcnow() - start_time > timeout:
                context.state = DeploymentState.FAILED
                context.error_details = {"reason": "Deployment timeout exceeded"}
                await self._save_context(context)
                break

            await self._save_checkpoint(context)
            next_transition = self._determine_next_transition(context)

            if not next_transition:
                break

            next_state = self.transitions.get((context.state, next_transition))
            if not next_state:
                context.state = DeploymentState.FAILED
                context.error_details = {
                    "reason": f"Invalid transition: {context.state} -> {next_transition}"
                }
                await self._save_context(context)
                break

            context.state_history.append((context.state, datetime.utcnow()))
            context.state = next_state
            await self._save_context(context)

            handler = self.state_handlers.get(context.state)
            if handler:
                try:
                    success, context = await handler.handle(context)
                    if not success and context.retry_count < context.max_retries:
                        context.retry_count += 1
                        await asyncio.sleep(2**context.retry_count)
                        context.state = (
                            context.state_history[-1][0]
                            if context.state_history
                            else DeploymentState.PENDING
                        )
                    elif not success:
                        if context.rollback_enabled and context.state != DeploymentState.VALIDATING:
                            context.state = DeploymentState.ROLLING_BACK
                        else:
                            context.state = DeploymentState.FAILED
                except Exception as e:
                    context.error_details = {"exception": str(e), "state": context.state.value}
                    if context.rollback_enabled and context.deployed_resources:
                        context.state = DeploymentState.ROLLING_BACK
                    else:
                        context.state = DeploymentState.FAILED

        await self._save_context(context)
        return context

    def _determine_next_transition(self, context: DeploymentContext) -> StateTransition | None:
        transitions_map = {
            DeploymentState.PENDING: StateTransition.VALIDATE,
            DeploymentState.VALIDATING: (
                StateTransition.APPROVE
                if context.validation_results.get("valid")
                else StateTransition.FAIL
            ),
            DeploymentState.APPROVED: StateTransition.PROVISION,
            DeploymentState.PROVISIONING: (
                StateTransition.CONFIGURE if context.deployed_resources else StateTransition.FAIL
            ),
            DeploymentState.CONFIGURING: StateTransition.VERIFY,
            DeploymentState.VERIFYING: (
                StateTransition.COMPLETE
                if context.validation_results.get("verified")
                else StateTransition.FAIL
            ),
            DeploymentState.FAILED: (
                StateTransition.ROLLBACK
                if context.rollback_enabled and context.deployed_resources
                else None
            ),
            DeploymentState.ROLLING_BACK: StateTransition.COMPLETE,
        }
        return transitions_map.get(context.state)

    async def _save_context(self, context: DeploymentContext) -> None:
        if self.redis_client:
            key = f"deployment:{context.deployment_id}"
            value = json.dumps(self._serialize_context(context))
            await self.redis_client.setex(key, 86400, value)

    async def _save_checkpoint(self, context: DeploymentContext) -> None:
        checkpoint = {
            "timestamp": datetime.utcnow().isoformat(),
            "state": context.state.value,
            "deployed_resources": len(context.deployed_resources),
            "retry_count": context.retry_count,
        }
        context.checkpoints.append(checkpoint)
        if self.redis_client:
            key = f"deployment:checkpoint:{context.deployment_id}:{len(context.checkpoints)}"
            await self.redis_client.setex(key, 86400, json.dumps(checkpoint))

    def _serialize_context(self, context: DeploymentContext) -> dict[str, Any]:
        return {
            "deployment_id": context.deployment_id,
            "subscription_id": context.subscription_id,
            "resource_group": context.resource_group,
            "location": context.location,
            "environment": context.environment,
            "initiated_by": context.initiated_by,
            "initiated_at": context.initiated_at.isoformat(),
            "state": context.state.value,
            "state_history": [(s.value, t.isoformat()) for s, t in context.state_history],
            "resources": context.resources,
            "deployed_resources": context.deployed_resources,
            "validation_results": context.validation_results,
            "error_details": context.error_details,
            "metadata": context.metadata,
            "checkpoints": context.checkpoints,
            "retry_count": context.retry_count,
        }

    async def get_deployment_status(self, deployment_id: str) -> dict[str, Any] | None:
        if self.redis_client:
            key = f"deployment:{deployment_id}"
            value = await self.redis_client.get(key)
            if value:
                return json.loads(value)
        return None


class ValidationHandler:
    async def handle(self, context: DeploymentContext) -> tuple[bool, DeploymentContext]:
        validators = [
            self._validate_subscription,
            self._validate_resource_group,
            self._validate_resources,
            self._validate_dependencies,
            self._validate_quotas,
            self._validate_permissions,
        ]

        validation_results: dict[str, Any] = {}
        for validator in validators:
            name = validator.__name__.replace("_validate_", "")
            result = await validator(context)
            validation_results[name] = result
            if not result["valid"]:
                context.validation_results = validation_results
                context.error_details = {"validation_failed": name, "details": result}
                return False, context

        validation_results["valid"] = True
        context.validation_results = validation_results
        return True, context

    async def _validate_subscription(self, context: DeploymentContext) -> dict[str, Any]:
        if not context.subscription_id:
            return {"valid": False, "message": "Subscription ID is required"}
        return {"valid": True}

    async def _validate_resource_group(self, context: DeploymentContext) -> dict[str, Any]:
        if not context.resource_group:
            return {"valid": False, "message": "Resource group is required"}
        if len(context.resource_group) > 90:
            return {"valid": False, "message": "Resource group name too long"}
        return {"valid": True}

    async def _validate_resources(self, context: DeploymentContext) -> dict[str, Any]:
        if not context.resources:
            return {"valid": False, "message": "No resources to deploy"}
        for resource in context.resources:
            if not resource.get("type") or not resource.get("name"):
                return {"valid": False, "message": f"Invalid resource definition: {resource}"}
        return {"valid": True}

    async def _validate_dependencies(self, context: DeploymentContext) -> dict[str, Any]:
        dependency_graph = self._build_dependency_graph(context.resources)
        if self._has_circular_dependency(dependency_graph):
            return {"valid": False, "message": "Circular dependency detected"}
        return {"valid": True}

    async def _validate_quotas(self, context: DeploymentContext) -> dict[str, Any]:
        return {"valid": True}

    async def _validate_permissions(self, context: DeploymentContext) -> dict[str, Any]:
        return {"valid": True}

    def _build_dependency_graph(self, resources: list[dict[str, Any]]) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        for resource in resources:
            name = resource.get("name", "")
            deps = resource.get("depends_on", [])
            graph[name] = deps
        return graph

    def _has_circular_dependency(self, graph: dict[str, list[str]]) -> bool:
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def visit(node: str) -> bool:
            if node in rec_stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            rec_stack.add(node)
            for neighbor in graph.get(node, []):
                if visit(neighbor):
                    return True
            rec_stack.remove(node)
            return False

        for node in graph:
            if visit(node):
                return True
        return False


class ApprovalHandler:
    async def handle(self, context: DeploymentContext) -> tuple[bool, DeploymentContext]:
        if context.environment in ["dev", "test"]:
            return True, context

        if context.dry_run:
            return True, context

        if not context.approval_token:
            context.approval_token = str(uuid.uuid4())
            return False, context

        return True, context


class ProvisioningHandler:
    async def handle(self, context: DeploymentContext) -> tuple[bool, DeploymentContext]:
        from app.tools.azure.clients import get_clients

        try:
            clients = await get_clients(context.subscription_id)
            deployment_order = self._determine_deployment_order(context.resources)

            for resource_name in deployment_order:
                resource = next(
                    (r for r in context.resources if r.get("name") == resource_name), None
                )
                if not resource:
                    continue

                if context.dry_run:
                    context.deployed_resources.append({**resource, "status": "dry_run"})
                    continue

                result = await self._deploy_resource(resource, clients, context)
                if result["success"]:
                    context.deployed_resources.append(result["resource"])
                else:
                    context.error_details = {
                        "resource": resource_name,
                        "error": result["error"],
                    }
                    return False, context

            return True, context
        except Exception as e:
            context.error_details = {"exception": str(e)}
            return False, context

    def _determine_deployment_order(self, resources: list[dict[str, Any]]) -> list[str]:
        graph = {r["name"]: r.get("depends_on", []) for r in resources}
        visited: set[str] = set()
        order: list[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for dep in graph.get(node, []):
                visit(dep)
            order.append(node)

        for node in graph:
            visit(node)

        return order

    async def _deploy_resource(
        self, resource: dict[str, Any], clients: Any, context: DeploymentContext
    ) -> dict[str, Any]:
        rid = (
            f"/subscriptions/{context.subscription_id}"
            f"/resourceGroups/{context.resource_group}"
            f"/providers/{resource['type']}/{resource['name']}"
        )
        return {"success": True, "resource": {**resource, "id": rid}}


class ConfigurationHandler:
    async def handle(self, context: DeploymentContext) -> tuple[bool, DeploymentContext]:
        for resource in context.deployed_resources:
            config_result = await self._configure_resource(resource, context)
            if not config_result["success"]:
                context.error_details = {
                    "resource": resource["name"],
                    "config_error": config_result["error"],
                }
                return False, context
        return True, context

    async def _configure_resource(
        self, resource: dict[str, Any], context: DeploymentContext
    ) -> dict[str, Any]:
        return {"success": True}


class VerificationHandler:
    async def handle(self, context: DeploymentContext) -> tuple[bool, DeploymentContext]:
        verifications = [
            self._verify_resource_state,
            self._verify_connectivity,
            self._verify_configuration,
            self._verify_security,
        ]

        for verification in verifications:
            result = await verification(context)
            if not result["success"]:
                context.validation_results["verified"] = False
                context.error_details = {
                    "verification_failed": verification.__name__,
                    "details": result,
                }
                return False, context

        context.validation_results["verified"] = True
        return True, context

    async def _verify_resource_state(self, context: DeploymentContext) -> dict[str, Any]:
        return {"success": True}

    async def _verify_connectivity(self, context: DeploymentContext) -> dict[str, Any]:
        return {"success": True}

    async def _verify_configuration(self, context: DeploymentContext) -> dict[str, Any]:
        return {"success": True}

    async def _verify_security(self, context: DeploymentContext) -> dict[str, Any]:
        return {"success": True}


class RollbackHandler:
    async def handle(self, context: DeploymentContext) -> tuple[bool, DeploymentContext]:
        from app.tools.azure.clients import get_clients

        try:
            clients = await get_clients(context.subscription_id)

            for resource in reversed(context.deployed_resources):
                await self._rollback_resource(resource, clients, context)

            return True, context
        except Exception as e:
            context.error_details = {"rollback_error": str(e)}
            return False, context

    async def _rollback_resource(
        self, resource: dict[str, Any], clients: Any, context: DeploymentContext
    ) -> None:
        pass
