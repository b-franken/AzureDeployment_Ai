from __future__ import annotations

from typing import Dict, List, Any, Optional
from datetime import datetime, UTC

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.logging import get_logger
from app.observability.app_insights import app_insights
from app.observability.distributed_tracing import (
    get_service_tracer,
    get_cross_service_tracer,
    ServiceRegistry,
    get_trace_context
)

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class ObservabilityHealthChecker:
    def __init__(self):
        self.service_tracer = get_service_tracer("observability_health_service")
        
    async def comprehensive_health_check(self) -> Dict[str, Any]:
        async with self.service_tracer.start_distributed_span(
            operation_name="comprehensive_health_check",
            correlation_id=f"health_{datetime.now(UTC).isoformat()}",
            user_id="system"
        ) as span:
            try:
                results = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "overall_status": "healthy",
                    "checks": {}
                }
                
                tracing_health = await self._check_distributed_tracing()
                results["checks"]["distributed_tracing"] = tracing_health
                
                app_insights_health = self._check_app_insights()
                results["checks"]["app_insights"] = app_insights_health
                
                service_registry_health = self._check_service_registry()
                results["checks"]["service_registry"] = service_registry_health
                
                context_management_health = self._check_context_management()
                results["checks"]["context_management"] = context_management_health
                
                failed_checks = [
                    name for name, check in results["checks"].items() 
                    if not check.get("healthy", False)
                ]
                
                if failed_checks:
                    results["overall_status"] = "degraded"
                    results["failed_checks"] = failed_checks
                
                span.set_attributes({
                    "health.overall_status": results["overall_status"],
                    "health.checks_count": len(results["checks"]),
                    "health.failed_count": len(failed_checks)
                })
                
                if failed_checks:
                    span.set_status(Status(StatusCode.ERROR, f"Failed checks: {', '.join(failed_checks)}"))
                else:
                    span.set_status(Status(StatusCode.OK))
                
                app_insights.track_custom_event(
                    "observability_health_check_completed",
                    {
                        "overall_status": results["overall_status"],
                        "failed_checks": ",".join(failed_checks) if failed_checks else "none"
                    },
                    {
                        "checks_count": len(results["checks"]),
                        "failed_count": len(failed_checks)
                    }
                )
                
                return results
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                logger.error(
                    "Observability health check failed",
                    error=str(e),
                    exc_info=True
                )
                
                return {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "overall_status": "unhealthy",
                    "error": str(e)
                }
    
    async def _check_distributed_tracing(self) -> Dict[str, Any]:
        try:
            test_tracer = get_service_tracer("health_check_test")
            
            async with test_tracer.start_distributed_span(
                operation_name="health_test",
                correlation_id="health_test_123",
                user_id="system"
            ) as span:
                span.set_attribute("test.type", "health_check")
                span.set_status(Status(StatusCode.OK))
                
                return {
                    "healthy": True,
                    "tracer_available": True,
                    "span_creation": True,
                    "attribute_setting": True
                }
                
        except Exception as e:
            logger.warning("Distributed tracing health check failed", error=str(e))
            return {
                "healthy": False,
                "error": str(e),
                "tracer_available": False
            }
    
    def _check_app_insights(self) -> Dict[str, Any]:
        try:
            if app_insights is None:
                return {
                    "healthy": False,
                    "available": False,
                    "error": "App Insights not initialized"
                }
            
            app_insights.track_custom_event(
                "observability_health_test",
                {"test": "health_check"},
                {"timestamp": datetime.now(UTC).timestamp()}
            )
            
            return {
                "healthy": True,
                "available": True,
                "event_tracking": True
            }
            
        except Exception as e:
            logger.warning("App Insights health check failed", error=str(e))
            return {
                "healthy": False,
                "available": True,
                "event_tracking": False,
                "error": str(e)
            }
    
    def _check_service_registry(self) -> Dict[str, Any]:
        try:
            registered_services = list(ServiceRegistry._tracers.keys())
            
            return {
                "healthy": True,
                "services_registered": len(registered_services),
                "service_names": registered_services,
                "registry_accessible": True
            }
            
        except Exception as e:
            logger.warning("Service registry health check failed", error=str(e))
            return {
                "healthy": False,
                "error": str(e),
                "registry_accessible": False
            }
    
    def _check_context_management(self) -> Dict[str, Any]:
        try:
            context_manager = get_trace_context()
            
            test_correlation_id = "health_test_context_123"
            context_manager.set_context(
                correlation_id=test_correlation_id,
                user_id="health_test"
            )
            
            retrieved_id = context_manager.get_correlation_id()
            retrieved_user = context_manager.get_user_id()
            
            return {
                "healthy": True,
                "context_setting": retrieved_id == test_correlation_id,
                "context_retrieval": retrieved_user == "health_test",
                "manager_accessible": True
            }
            
        except Exception as e:
            logger.warning("Context management health check failed", error=str(e))
            return {
                "healthy": False,
                "error": str(e),
                "manager_accessible": False
            }


_health_checker: Optional[ObservabilityHealthChecker] = None


def get_health_checker() -> ObservabilityHealthChecker:
    global _health_checker
    if _health_checker is None:
        _health_checker = ObservabilityHealthChecker()
    return _health_checker


async def quick_health_check() -> Dict[str, Any]:
    checker = get_health_checker()
    return await checker.comprehensive_health_check()