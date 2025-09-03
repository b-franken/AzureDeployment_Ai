from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.logging import get_logger
from app.observability.app_insights import app_insights

from .execution_context import ExecutionResult, ProvisionContext
from .fallback_strategy import ProvisioningStrategy

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


class AVMStrategy(ProvisioningStrategy):
    def __init__(self) -> None:
        super().__init__("avm_bicep", priority=100)
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from app.tools.provision.backends.avm_bicep.engine import BicepAvmBackend
        self._avm_backend: BicepAvmBackend | None = None

    async def initialize(self) -> None:
        with tracer.start_as_current_span("avm_strategy_initialize") as span:
            try:
                from app.tools.provision.backends.avm_bicep.engine import BicepAvmBackend

                self._avm_backend = BicepAvmBackend()
                self._initialized = True

                span.set_attributes(
                    {
                        "strategy.name": self.name,
                        "strategy.backend_type": "BicepAvmBackend",
                        "strategy.initialized": True,
                    }
                )
                span.set_status(Status(StatusCode.OK))

                app_insights.track_custom_event(
                    "avm_strategy_initialized", {"backend_type": "BicepAvmBackend"}
                )

            except ImportError as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, f"Failed to import AVM backend: {str(e)}"))
                raise
            except Exception as e:
                span.record_exception(e)
                span.set_status(
                    Status(StatusCode.ERROR, f"Failed to initialize AVM backend: {str(e)}")
                )
                raise

    async def can_handle(self, context: ProvisionContext) -> bool:
        with tracer.start_as_current_span("avm_strategy_can_handle") as span:
            span.set_attributes(
                {
                    "strategy.name": self.name,
                    "context.user_id": context.user_id,
                    "context.correlation_id": context.correlation_id,
                    "context.parsed_resources_count": len(context.parsed_resources),
                    "context.has_deployment_plan": bool(context.deployment_plan),
                }
            )

            # Check if we have parsed resources OR if we can parse the request text
            has_resources = len(context.parsed_resources) > 0 or bool(
                context.request_text and len(context.request_text.strip()) > 0
            )

            can_handle = (
                self._avm_backend is not None
                and has_resources
                and self.name not in context.attempted_strategies
            )

            span.set_attributes(
                {
                    "strategy.can_handle": can_handle,
                    "strategy.has_backend": self._avm_backend is not None,
                    "strategy.not_attempted": self.name not in context.attempted_strategies,
                }
            )
            span.set_status(Status(StatusCode.OK))

            return can_handle

    async def execute(self, context: ProvisionContext) -> ExecutionResult:
        start_time = datetime.now(UTC)

        with tracer.start_as_current_span("avm_strategy_execute") as span:
            span.set_attributes(
                {
                    "strategy.name": self.name,
                    "context.user_id": context.user_id,
                    "context.correlation_id": context.correlation_id,
                    "context.dry_run": context.dry_run,
                    "context.environment": context.environment,
                }
            )

            try:
                from app.ai.nlu.unified_parser import parse_provision_request
                from app.tools.provision.backends.avm_bicep.engine import (
                    ProvisionContext as AVMContext,
                )

                nlu_result = parse_provision_request(context.request_text)

                if not context.subscription_id:
                    raise ValueError("Subscription ID is required for AVM provisioning")

                avm_context = AVMContext(
                    subscription_id=context.subscription_id,
                    resource_group=nlu_result.parameters.get("resource_group")
                    or context.resource_group
                    or "default-rg",
                    location=nlu_result.parameters.get("location")
                    or context.location
                    or "westeurope",
                    environment=context.environment,
                    name_prefix=context.name_prefix,
                    tags=context.tags,
                )

                app_insights.track_custom_event(
                    "avm_strategy_execution_started",
                    {
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "environment": context.environment,
                        "dry_run": str(context.dry_run),
                    },
                    {"parsed_resources_count": len(context.parsed_resources)},
                )

                if not self._avm_backend:
                    raise RuntimeError("AVM backend not initialized")

                if context.dry_run:
                    result = await self._avm_backend.plan_from_nlu(
                        nlu_result, avm_context, context.dry_run
                    )
                    operation_type = "plan"
                else:
                    plan_result = await self._avm_backend.plan_from_nlu(
                        nlu_result, avm_context, False
                    )
                    if hasattr(plan_result, "bicep_path") and plan_result.bicep_path:
                        apply_result = await self._avm_backend.apply(
                            avm_context, plan_result.bicep_path
                        )
                        # Log apply operation for observability with type-safe attribute access
                        apply_success = False
                        if isinstance(apply_result, dict):
                            apply_success = (
                                apply_result.get("status") == "succeeded" or
                                bool(apply_result.get("deployment_id"))
                            )
                        else:
                            apply_success = getattr(apply_result, "success", False)

                        logger.info(
                            "AVM apply operation completed",
                            bicep_path=plan_result.bicep_path,
                            apply_success=apply_success,
                            apply_result_type=type(apply_result).__name__,
                            apply_result_keys=(
                                list(apply_result.keys()) if isinstance(apply_result, dict) else []
                            ),
                        )
                        
                        # Use plan_result as the primary result since it contains the preview info
                        # Apply result mainly contains deployment confirmation
                        result = plan_result
                        
                        logger.info(
                            "Merging apply result with plan result",
                            plan_result_type=type(plan_result).__name__,
                            apply_result_type=type(apply_result).__name__,
                            plan_is_dict=isinstance(plan_result, dict),
                            apply_is_dict=isinstance(apply_result, dict),
                            plan_keys=(
                                list(plan_result.keys()) 
                                if isinstance(plan_result, dict) 
                                else []
                            ),
                            apply_keys=(
                                list(apply_result.keys()) 
                                if isinstance(apply_result, dict) 
                                else []
                            ),
                        )
                        
                        # Add apply result info as metadata if it's a dict
                        if isinstance(apply_result, dict):
                            if isinstance(result, dict):
                                # If both are dicts, merge them
                                result.update(apply_result)
                                result["apply_result"] = apply_result
                                
                                logger.info(
                                    "Merged apply result into plan result",
                                    merged_keys=list(result.keys()),
                                    has_status=("status" in result),
                                    has_deployment_id=("deployment_id" in result),
                                    status_value=result.get("status"),
                                )
                            elif hasattr(result, "__dict__"):
                                # Add apply_result as an attribute if result is an object
                                if isinstance(result, dict):
                                    result["apply_result"] = apply_result
                                else:
                                    setattr(result, "apply_result", apply_result)  # noqa: B010
                    else:
                        raise Exception("Failed to generate bicep template for deployment")
                    operation_type = "apply"

                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

                # Type-safe success determination with comprehensive logging
                logger.info(
                    "Starting AVM success evaluation",
                    strategy_name=self.name,
                    operation_type=operation_type,
                    result_type=type(result).__name__,
                    is_dict=isinstance(result, dict),
                    execution_time_ms=execution_time,
                )
                
                success = False
                if isinstance(result, dict):
                    # Check multiple status indicators for success
                    status = result.get("status")
                    has_deployment_id = bool(result.get("deployment_id"))
                    has_bicep_path = bool(result.get("bicep_path"))
                    
                    # For apply operations, also check the apply_result data
                    apply_result_data = result.get("apply_result", {})
                    apply_status = (
                        apply_result_data.get("status") 
                        if isinstance(apply_result_data, dict) 
                        else None
                    )
                    apply_deployment_id = (
                        bool(apply_result_data.get("deployment_id")) 
                        if isinstance(apply_result_data, dict) 
                        else False
                    )
                    
                    success = (
                        status == "succeeded" or 
                        apply_status == "succeeded" or
                        has_deployment_id or 
                        apply_deployment_id or
                        (operation_type == "plan" and has_bicep_path)
                    )
                    
                    logger.info(
                        "AVM result success evaluation",
                        strategy_name=self.name,
                        result_status=status,
                        apply_status=apply_status,
                        has_deployment_id=has_deployment_id,
                        apply_deployment_id=apply_deployment_id,
                        has_bicep_path=has_bicep_path,
                        operation_type=operation_type,
                        success=success,
                        result_keys=list(result.keys()),
                        apply_result_keys=(
                            list(apply_result_data.keys()) 
                            if isinstance(apply_result_data, dict) 
                            else []
                        ),
                    )
                else:
                    success = getattr(result, "success", False)
                    logger.debug(
                        "AVM result success check from object",
                        result_type=type(result).__name__,
                        success=success,
                        has_success_attr=hasattr(result, "success"),
                    )

                span.set_attributes(
                    {
                        "avm.operation_type": operation_type,
                        "avm.success": success,
                        "avm.execution_time_ms": execution_time,
                    }
                )

                if success:
                    resources_affected = []
                    warnings = []

                    # Type-safe resource and warning extraction with enhanced logging
                    if isinstance(result, dict):
                        # Handle dict-based results (from apply operations)
                        if "resources" in result and result["resources"]:
                            try:
                                resources_affected = [
                                    r.get("name", "unnamed") if isinstance(r, dict) else str(r)
                                    for r in result["resources"]
                                ]
                                logger.debug(
                                    "Extracted resources from dict result",
                                    resource_count=len(resources_affected),
                                    # Log first 5 for brevity
                                    resources=resources_affected[:5],
                                )
                            except (TypeError, AttributeError) as e:
                                logger.warning(
                                    "Failed to extract resource names from dict result",
                                    error=str(e),
                                    resources_type=type(result.get("resources")).__name__,
                                )
                                resources_affected = []

                        if "warnings" in result and result["warnings"]:
                            try:
                                warnings = list(result["warnings"]) if result["warnings"] else []
                                logger.debug(
                                    "Extracted warnings from dict result",
                                    warning_count=len(warnings),
                                )
                            except (TypeError, ValueError) as e:
                                logger.warning(
                                    "Failed to extract warnings from dict result",
                                    error=str(e),
                                    warnings_type=type(result.get("warnings")).__name__,
                                )
                                warnings = []

                        deployment_id = result.get("deployment_id", "")
                        if deployment_id and isinstance(deployment_id, str):
                            try:
                                resource_name_from_deployment = deployment_id.split("/")[
                                    -1
                                ].replace("avm-deployment-", "")
                                if (
                                    resource_name_from_deployment
                                    and resource_name_from_deployment != deployment_id
                                ):
                                    resources_affected.append(resource_name_from_deployment)
                                    logger.debug(
                                        "Extracted resource name from deployment ID",
                                        deployment_id=deployment_id,
                                        extracted_name=resource_name_from_deployment,
                                    )
                            except (IndexError, AttributeError) as e:
                                logger.warning(
                                    "Failed to extract resource name from deployment ID",
                                    deployment_id=deployment_id,
                                    error=str(e),
                                )
                    else:
                        logger.debug(
                            "Processing non-dict result object",
                            result_type=type(result).__name__,
                            result_attributes=[
                                attr for attr in dir(result) if not attr.startswith("_")
                            ],
                        )

                        if hasattr(result, "validation_results") and result.validation_results:
                            try:
                                validation_data = result.validation_results
                                if (
                                    isinstance(validation_data, dict)
                                    and "warnings" in validation_data
                                ):
                                    warnings = list(validation_data["warnings"])
                                    logger.debug(
                                        "Extracted warnings from validation results",
                                        warning_count=len(warnings),
                                    )
                            except (TypeError, AttributeError) as e:
                                logger.warning(
                                    "Failed to extract warnings from validation results",
                                    error=str(e),
                                )

                        if hasattr(result, "cost_estimate") and result.cost_estimate:
                            try:
                                cost_data = result.cost_estimate
                                if isinstance(cost_data, dict) and "resources" in cost_data:
                                    cost_resources = cost_data["resources"]
                                    if isinstance(cost_resources, list):
                                        resources_affected = [
                                            (
                                                r.get("name", "unnamed")
                                                if isinstance(r, dict)
                                                else str(r)
                                            )
                                            for r in cost_resources
                                        ]
                                        logger.debug(
                                            "Extracted resources from cost estimate",
                                            resource_count=len(resources_affected),
                                        )
                            except (TypeError, AttributeError) as e:
                                logger.warning(
                                    "Failed to extract resources from cost estimate",
                                    error=str(e),
                                )

                    app_insights.track_custom_event(
                        "avm_strategy_succeeded",
                        {
                            "user_id": context.user_id,
                            "correlation_id": context.correlation_id,
                            "operation_type": operation_type,
                        },
                        {
                            "execution_time_ms": execution_time,
                            "resources_affected": len(resources_affected),
                        },
                    )

                    span.set_status(Status(StatusCode.OK))

                    logger.info(
                        "Creating AVM success ExecutionResult",
                        strategy_name=self.name,
                        execution_time_ms=execution_time,
                        resources_count=len(resources_affected),
                    )
                    
                    return ExecutionResult.success_result(
                        strategy=self.name,
                        data=result,
                        execution_time=execution_time,
                        resources=resources_affected,
                        warnings=warnings,
                    )
                else:
                    if isinstance(result, dict):
                        error_message = result.get("message", "AVM execution failed")
                    else:
                        error_message = getattr(result, "error_message", "AVM execution failed")

                    app_insights.track_custom_event(
                        "avm_strategy_failed",
                        {
                            "user_id": context.user_id,
                            "correlation_id": context.correlation_id,
                            "operation_type": operation_type,
                            "error": error_message,
                        },
                        {"execution_time_ms": execution_time},
                    )

                    span.set_status(Status(StatusCode.ERROR, error_message))

                    return ExecutionResult.failure_result(
                        strategy=self.name, error=error_message, execution_time=execution_time
                    )

            except ImportError as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                error_msg = f"AVM backend import failed: {str(e)}"

                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, error_msg))

                app_insights.track_exception(
                    e,
                    {
                        "strategy_name": self.name,
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "error_type": "import_error",
                    },
                )

                return ExecutionResult.failure_result(
                    strategy=self.name, error=error_msg, execution_time=execution_time
                )

            except Exception as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                error_msg = f"AVM execution failed: {str(e)}"

                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, error_msg))

                app_insights.track_exception(
                    e,
                    {
                        "strategy_name": self.name,
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "error_type": "execution_error",
                    },
                )

                return ExecutionResult.failure_result(
                    strategy=self.name, error=error_msg, execution_time=execution_time
                )

    async def cleanup(self) -> None:
        """Clean up AVM backend resources."""
        with tracer.start_as_current_span("avm_cleanup") as span:
            try:
                if self._avm_backend:
                    # AVM backend cleanup if needed
                    pass
                span.set_status(Status(StatusCode.OK))
                logger.debug("AVM strategy cleanup completed")
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.warning("AVM strategy cleanup failed", error=str(e))


class SDKFallbackStrategy(ProvisioningStrategy):
    def __init__(self) -> None:
        super().__init__("azure_sdk_fallback", priority=50)
        self._intelligent_tool: SDKFallbackStrategy | None = None

    async def initialize(self) -> None:
        with tracer.start_as_current_span("sdk_fallback_initialize") as span:
            try:
                from app.tools.azure.actions.registry import get_action

                self._action_registry = get_action  # Use existing action registry
                self._intelligent_tool = self  # Use self as the tool
                self._initialized = True

                span.set_attributes(
                    {
                        "strategy.name": self.name,
                        "strategy.backend_type": "AzureActionRegistry",
                        "strategy.initialized": True,
                    }
                )
                span.set_status(Status(StatusCode.OK))

                app_insights.track_custom_event(
                    "sdk_fallback_strategy_initialized", {"backend_type": "AzureActionRegistry"}
                )

            except ImportError as e:
                span.record_exception(e)
                span.set_status(
                    Status(StatusCode.ERROR, f"Failed to import SDK fallback: {str(e)}")
                )
                raise
            except Exception as e:
                span.record_exception(e)
                span.set_status(
                    Status(StatusCode.ERROR, f"Failed to initialize SDK fallback: {str(e)}")
                )
                raise

    async def can_handle(self, context: ProvisionContext) -> bool:
        with tracer.start_as_current_span("sdk_fallback_can_handle") as span:
            span.set_attributes(
                {
                    "strategy.name": self.name,
                    "context.user_id": context.user_id,
                    "context.correlation_id": context.correlation_id,
                    "context.attempted_strategies": context.attempted_strategies,
                }
            )

            can_handle = (
                self._intelligent_tool is not None
                and self.name not in context.attempted_strategies
                and "avm_bicep" in context.attempted_strategies
            )

            span.set_attributes(
                {
                    "strategy.can_handle": can_handle,
                    "strategy.has_tool": self._intelligent_tool is not None,
                    "strategy.avm_was_attempted": "avm_bicep" in context.attempted_strategies,
                }
            )
            span.set_status(Status(StatusCode.OK))

            return can_handle

    async def execute(self, context: ProvisionContext) -> ExecutionResult:
        start_time = datetime.now(UTC)

        with tracer.start_as_current_span("sdk_fallback_execute") as span:
            span.set_attributes(
                {
                    "strategy.name": self.name,
                    "context.user_id": context.user_id,
                    "context.correlation_id": context.correlation_id,
                    "context.dry_run": context.dry_run,
                }
            )

            try:

                app_insights.track_custom_event(
                    "sdk_fallback_execution_started",
                    {
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "environment": context.environment,
                        "dry_run": str(context.dry_run),
                        "fallback_reason": "AVM strategy failed",
                    },
                )

                from app.ai.nlu.unified_parser import parse_provision_request

                nlu_result = parse_provision_request(context.request_text)

                action_result = await self._execute_resource_action(
                    nlu_result, context, context.dry_run
                )
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

                # action_result is a tuple: (success, message, data)
                success, message, data = action_result

                span.set_attributes(
                    {
                        "sdk_fallback.execution_time_ms": execution_time,
                        "sdk_fallback.success": success,
                        "sdk_fallback.message": message,
                    }
                )

                if success:
                    resources_affected = self._extract_resource_names(nlu_result, message, data)
                    warnings: list[str] = []

                    app_insights.track_custom_event(
                        "sdk_fallback_succeeded",
                        {
                            "user_id": context.user_id,
                            "correlation_id": context.correlation_id,
                            "fallback_reason": "AVM strategy failed",
                        },
                        {
                            "execution_time_ms": execution_time,
                            "resources_affected": len(resources_affected),
                        },
                    )

                    span.set_status(Status(StatusCode.OK))

                    logger.info(
                        "Creating SDK fallback success ExecutionResult",
                        strategy_name=self.name,
                        execution_time_ms=execution_time,
                        resources_count=len(resources_affected),
                        fallback_reason="AVM strategy failed",
                    )
                    
                    return ExecutionResult.success_result(
                        strategy=self.name,
                        data=data,
                        execution_time=execution_time,
                        resources=resources_affected,
                        warnings=warnings,
                    )
                else:
                    error_message = f"SDK fallback failed with message: {message}"

                    app_insights.track_custom_event(
                        "sdk_fallback_failed",
                        {
                            "user_id": context.user_id,
                            "correlation_id": context.correlation_id,
                            "error": error_message,
                            "fallback_reason": "AVM strategy failed",
                        },
                        {"execution_time_ms": execution_time},
                    )

                    span.set_status(Status(StatusCode.ERROR, error_message))

                    return ExecutionResult.failure_result(
                        strategy=self.name, error=error_message, execution_time=execution_time
                    )

            except Exception as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                error_msg = f"SDK fallback execution failed: {str(e)}"

                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, error_msg))

                app_insights.track_exception(
                    e,
                    {
                        "strategy_name": self.name,
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "error_type": "fallback_execution_error",
                    },
                )

                return ExecutionResult.failure_result(
                    strategy=self.name, error=error_msg, execution_time=execution_time
                )

    async def _execute_resource_action(
        self, nlu_result: Any, context: ProvisionContext, dry_run: bool
    ) -> tuple[bool, str, dict[str, Any]]:

        resource_type = nlu_result.resource_type or ""
        action_name = self._map_resource_to_action(resource_type)

        if not action_name:
            return (False, f"No action mapping found for resource type: {resource_type}", {})

        action_fn = self._action_registry(action_name)
        if not action_fn:
            return (False, f"Action function not found: {action_name}", {})

        try:
            params = self._build_action_parameters(nlu_result, context, action_name)
            
            # Add clients using central azure auth
            from app.tools.azure.clients import get_clients
            clients = await get_clients(context.subscription_id)
            params["clients"] = clients

            if dry_run:
                plan_data = {
                    "action": action_name,
                    "parameters": params,
                    "resource_type": resource_type,
                    "dry_run": True,
                }
                return (True, "Dry run plan generated", plan_data)

            result = await action_fn(**params)

            if isinstance(result, tuple) and len(result) >= 2:
                status, data = result[0], result[1]
                success = status not in ["failed", "error"]
                result_data = data if isinstance(data, dict) else {"output": str(data)}
                return (success, str(data) if not isinstance(data, str) else data, result_data)
            elif isinstance(result, dict):
                status = result.get("status", "completed")
                success = status not in ["failed", "error"]
                return (success, status, result)
            else:
                return (True, str(result), {"output": str(result)})

        except Exception as e:
            return (False, str(e), {"error": str(e)})

    def _map_resource_to_action(self, resource_type: str) -> str:
        resource_action_map = {
            "storage": "create_storage",
            "webapp": "create_webapp",
            "aks": "create_aks",
            "acr": "create_acr",
            "vm": "create_vm",
            "sql": "create_sql",
            "keyvault": "create_keyvault",
            "cosmos": "create_cosmos",
            "redis": "create_redis",
            "vnet": "create_vnet",
            "subnet": "create_subnet",
            "nsg": "create_nsg",
            "public_ip": "create_public_ip",
            "lb": "create_lb",
            "app_gateway": "create_app_gateway",
            "resource_group": "create_rg",
            "plan": "create_plan",
            "log_analytics": "create_log_analytics_workspace",
            "app_insights": "create_app_insights",
            "managed_identity": "create_user_assigned_identity",
            "private_dns": "create_private_dns_zone",
            "private_endpoint": "create_private_endpoint",
            "apim": "create_apim",
            "eventhub": "create_eventhub",
        }
        return resource_action_map.get(resource_type, "")

    def _build_action_parameters(
        self, nlu_result: Any, context: ProvisionContext, action_name: str
    ) -> dict[str, Any]:
        _resource_type = nlu_result.resource_type or ""
        params = nlu_result.parameters or {}

        param_builders = {
            "create_storage": self._build_storage_params,
            "create_webapp": self._build_webapp_params,
            "create_aks": self._build_aks_params,
            "create_acr": self._build_acr_params,
            "create_vm": self._build_vm_params,
            "create_sql": self._build_sql_params,
            "create_keyvault": self._build_keyvault_params,
            "create_cosmos": self._build_cosmos_params,
            "create_redis": self._build_redis_params,
            "create_vnet": self._build_vnet_params,
            "create_subnet": self._build_subnet_params,
            "create_nsg": self._build_nsg_params,
            "create_public_ip": self._build_public_ip_params,
            "create_lb": self._build_lb_params,
            "create_app_gateway": self._build_app_gateway_params,
            "create_rg": self._build_rg_params,
            "create_plan": self._build_plan_params,
            "create_log_analytics_workspace": self._build_log_analytics_params,
            "create_app_insights": self._build_app_insights_params,
            "create_user_assigned_identity": self._build_managed_identity_params,
            "create_private_dns_zone": self._build_private_dns_params,
            "create_private_endpoint": self._build_private_endpoint_params,
            "create_apim": self._build_apim_params,
            "create_eventhub": self._build_eventhub_params,
        }

        builder = param_builders.get(action_name)
        if builder:
            return builder(params, context)

        return self._build_default_params(params, context)

    def _build_storage_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:        
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "name": params.get("name")
            or f"{context.name_prefix}storage{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "sku": params.get("sku")
            or ("Standard_ZRS" if context.environment == "prod" else "Standard_LRS"),
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_webapp_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "app_name": params.get("name") or f"{context.name_prefix}app{context.environment}",
            "plan_name": params.get("plan") or f"{context.name_prefix}plan{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "sku": params.get("sku") or self._determine_webapp_sku(context.environment),
            "runtime": params.get("runtime") or "python|3.11",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_aks_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "cluster_name": params.get("name") or f"{context.name_prefix}aks{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "dns_prefix": params.get("dns_prefix")
            or f"{context.name_prefix}aks{context.environment}",
            "node_count": params.get("node_count") or (3 if context.environment == "prod" else 1),
            "vm_size": params.get("vm_size") or "Standard_DS2_v2",
            "kubernetes_version": params.get("kubernetes_version") or "1.28.0",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_acr_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "registry_name": params.get("name") or f"{context.name_prefix}acr{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "sku": params.get("sku") or ("Premium" if context.environment == "prod" else "Basic"),
            "admin_user_enabled": params.get("admin_user_enabled")
            or (context.environment != "prod"),
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_vm_params(self, params: dict[str, Any], context: ProvisionContext) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "vm_name": params.get("name") or f"{context.name_prefix}vm{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "vm_size": params.get("vm_size") or "Standard_B2s",
            "admin_username": params.get("admin_username") or "azureuser",
            "admin_password": params.get("admin_password") or self._generate_secure_password(),
            "os_disk_type": params.get("os_disk_type") or "Premium_LRS",
            "image": params.get("image") or "Ubuntu2204",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_sql_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "server_name": params.get("server_name")
            or f"{context.name_prefix}sql{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "administrator_login": params.get("sql_admin_user") or "sqladmin",
            "administrator_password": params.get("sql_admin_password")
            or self._generate_secure_password(),
            "version": params.get("version") or "12.0",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_keyvault_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "vault_name": params.get("vault_name")
            or params.get("name")
            or f"{context.name_prefix}kv{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "sku_name": params.get("sku") or "standard",
            "tenant_id": None,  # Will be resolved by Azure SDK authentication
            "enable_rbac": True,
            "purge_protection": context.environment == "prod",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_cosmos_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "account_name": params.get("account_name")
            or params.get("name")
            or f"{context.name_prefix}cosmos{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "kind": params.get("kind") or "GlobalDocumentDB",
            "consistency_level": params.get("consistency_level") or "Session",
            "enable_automatic_failover": context.environment == "prod",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_redis_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "cache_name": params.get("name") or f"{context.name_prefix}redis{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "sku_name": "Premium" if context.environment == "prod" else "Standard",
            "capacity": 2 if context.environment == "prod" else 1,
            "enable_non_ssl_port": False,
            "minimum_tls_version": "1.2",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_vnet_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "vnet_name": params.get("name") or f"{context.name_prefix}vnet{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "address_prefixes": params.get("address_prefixes") or ["10.0.0.0/16"],
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_subnet_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "vnet_name": params.get("vnet_name")
            or f"{context.name_prefix}vnet{context.environment}",
            "subnet_name": params.get("name") or "default",
            "address_prefix": params.get("address_prefix") or "10.0.1.0/24",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_nsg_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "nsg_name": params.get("name") or f"{context.name_prefix}nsg{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "security_rules": params.get("security_rules") or [],
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_public_ip_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "pip_name": params.get("name") or f"{context.name_prefix}pip{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "allocation_method": params.get("allocation_method") or "Static",
            "sku": params.get("sku") or "Standard",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_lb_params(self, params: dict[str, Any], context: ProvisionContext) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "lb_name": params.get("name") or f"{context.name_prefix}lb{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "sku": params.get("sku") or "Standard",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_app_gateway_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "gateway_name": params.get("name")
            or f"{context.name_prefix}appgw{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "sku_name": params.get("sku")
            or ("WAF_v2" if context.environment == "prod" else "Standard_v2"),
            "capacity": params.get("capacity") or (3 if context.environment == "prod" else 1),
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_rg_params(self, params: dict[str, Any], context: ProvisionContext) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("name") or context.resource_group or "default-rg",
            "location": params.get("location") or context.location or "westeurope",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_plan_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "plan_name": params.get("name") or f"{context.name_prefix}plan{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "sku": params.get("sku") or self._determine_webapp_sku(context.environment),
            "is_linux": params.get("is_linux") or True,
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_log_analytics_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "workspace_name": params.get("name")
            or f"{context.name_prefix}law{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "sku": params.get("sku") or "PerGB2018",
            "retention_in_days": params.get("retention")
            or (90 if context.environment == "prod" else 30),
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_app_insights_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "app_insights_name": params.get("name")
            or f"{context.name_prefix}ai{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "application_type": params.get("application_type") or "web",
            "workspace_name": params.get("workspace_name"),
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_managed_identity_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "identity_name": params.get("name") or f"{context.name_prefix}id{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_private_dns_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "zone_name": params.get("zone_name") or params.get("name") or "privatelink.azure.com",
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_private_endpoint_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "endpoint_name": params.get("name") or f"{context.name_prefix}pe{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "subnet_name": params.get("subnet_name") or "private-endpoints",
            "vnet_name": params.get("vnet_name")
            or f"{context.name_prefix}vnet{context.environment}",
            "private_connection_resource_id": params.get("private_connection_resource_id"),
            "group_ids": params.get("group_ids") or [],
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_apim_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "service_name": params.get("name") or f"{context.name_prefix}apim{context.environment}",
            "location": params.get("location") or context.location or "westeurope",
            "publisher_name": params.get("publisher_name") or "API Publisher",
            "publisher_email": params.get("publisher_email") or "admin@company.com",
            "sku_name": params.get("sku")
            or ("Premium" if context.environment == "prod" else "Developer"),
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_eventhub_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "namespace_name": params.get("namespace_name")
            or f"{context.name_prefix}eh{context.environment}",
            "eventhub_name": params.get("name") or "events",
            "location": params.get("location") or context.location or "westeurope",
            "sku": params.get("sku") or "Standard",
            "partition_count": params.get("partition_count") or 2,
            "message_retention": params.get("message_retention") or 1,
            "tags": {**context.tags, "environment": context.environment},
        }

    def _build_default_params(
        self, params: dict[str, Any], context: ProvisionContext
    ) -> dict[str, Any]:
        return {
            "subscription_id": context.subscription_id,
            "resource_group": params.get("resource_group")
            or context.resource_group
            or "default-rg",
            "location": params.get("location") or context.location or "westeurope",
            "tags": {**context.tags, "environment": context.environment},
            **params,
        }

    def _extract_resource_names(self, nlu_result: Any, status: str, result: Any) -> list[str]:
        resource_names = []

        if status == "created" or status == "exists":
            if isinstance(result, dict):
                if "name" in result:
                    resource_names.append(result["name"])
                elif "id" in result:
                    resource_id = result["id"]
                    if "/" in resource_id:
                        resource_names.append(resource_id.split("/")[-1])

            if not resource_names and nlu_result.parameters:
                name = nlu_result.parameters.get("name")
                if name:
                    resource_names.append(name)

        return resource_names

    def _determine_webapp_sku(self, environment: str) -> str:
        sku_map = {"dev": "B1", "test": "B2", "staging": "P1v3", "prod": "P2v3"}
        return sku_map.get(environment, "B1")

    def _generate_secure_password(self) -> str:
        import secrets
        import string

        length = 16
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        password = "".join(secrets.choice(chars) for _ in range(length))

        return password

    async def cleanup(self) -> None:
        """Clean up SDK fallback strategy resources."""
        with tracer.start_as_current_span("sdk_fallback_cleanup") as span:
            try:
                if hasattr(self, "_action_registry"):
                    # SDK fallback cleanup if needed
                    pass
                span.set_status(Status(StatusCode.OK))
                logger.debug("SDK fallback strategy cleanup completed")
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.warning("SDK fallback strategy cleanup failed", error=str(e))
