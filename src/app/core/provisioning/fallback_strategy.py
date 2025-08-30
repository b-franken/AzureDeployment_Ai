from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Any, Dict
from datetime import datetime, UTC

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from app.observability.app_insights import app_insights
from app.observability.distributed_tracing import get_service_tracer

from .execution_context import ProvisionContext, ExecutionResult, ProvisioningPhase

tracer = trace.get_tracer(__name__)


class ProvisioningStrategy(ABC):
    def __init__(self, name: str, priority: int = 0):
        self.name = name
        self.priority = priority
        self._initialized = False
    
    @abstractmethod
    async def can_handle(self, context: ProvisionContext) -> bool:
        pass
    
    @abstractmethod
    async def execute(self, context: ProvisionContext) -> ExecutionResult:
        pass
    
    @abstractmethod
    async def initialize(self) -> None:
        pass
    
    async def cleanup(self) -> None:
        pass
    
    def __str__(self) -> str:
        return f"{self.name}(priority={self.priority})"


class ProvisioningOrchestrator:
    def __init__(self):
        self._strategies: List[ProvisioningStrategy] = []
        self._strategy_stats: Dict[str, Dict[str, Any]] = {}
        self.service_tracer = get_service_tracer("provisioning_orchestrator")
    
    def register_strategy(self, strategy: ProvisioningStrategy) -> None:
        with tracer.start_as_current_span("orchestrator_register_strategy") as span:
            self._strategies.append(strategy)
            self._strategies.sort(key=lambda s: s.priority, reverse=True)
            
            self._strategy_stats[strategy.name] = {
                "total_attempts": 0,
                "successful_attempts": 0,
                "failed_attempts": 0,
                "avg_execution_time_ms": 0.0,
                "last_used": None
            }
            
            span.set_attributes({
                "strategy.name": strategy.name,
                "strategy.priority": strategy.priority,
                "orchestrator.total_strategies": len(self._strategies)
            })
            span.set_status(Status(StatusCode.OK))
    
    async def initialize_all_strategies(self) -> None:
        with tracer.start_as_current_span("orchestrator_initialize_strategies") as span:
            initialization_results = []
            
            for strategy in self._strategies:
                try:
                    if not strategy._initialized:
                        await strategy.initialize()
                        strategy._initialized = True
                        initialization_results.append(f"{strategy.name}:success")
                        
                        app_insights.track_custom_event(
                            "strategy_initialized",
                            {
                                "strategy_name": strategy.name,
                                "strategy_priority": str(strategy.priority)
                            }
                        )
                except Exception as e:
                    initialization_results.append(f"{strategy.name}:failed")
                    span.add_event("strategy_initialization_failed", {
                        "strategy": strategy.name,
                        "error": str(e)
                    })
            
            successful_count = len([r for r in initialization_results if r.endswith(":success")])
            
            span.set_attributes({
                "initialization.total_strategies": len(self._strategies),
                "initialization.successful": successful_count,
                "initialization.failed": len(self._strategies) - successful_count,
                "initialization.results": initialization_results
            })
            
            if successful_count == len(self._strategies):
                span.set_status(Status(StatusCode.OK))
            else:
                span.set_status(Status(StatusCode.ERROR, f"Only {successful_count}/{len(self._strategies)} strategies initialized"))
    
    async def execute_with_fallback(self, context: ProvisionContext) -> ExecutionResult:
        async with self.service_tracer.start_distributed_span(
            operation_name="execute_with_fallback",
            correlation_id=context.correlation_id,
            user_id=context.user_id,
            attributes={
                "available_strategies": len(self._strategies),
                "current_phase": context.current_phase.value if hasattr(context.current_phase, 'value') else str(context.current_phase),
                "dry_run": context.dry_run
            }
        ) as span:
            span.set_attributes({
                "context.user_id": context.user_id,
                "context.correlation_id": context.correlation_id,
                "context.current_phase": context.current_phase.value if hasattr(context.current_phase, 'value') else str(context.current_phase),
                "context.dry_run": context.dry_run,
                "orchestrator.available_strategies": len(self._strategies)
            })
            
            app_insights.track_custom_event(
                "provisioning_orchestration_started",
                {
                    "user_id": context.user_id,
                    "correlation_id": context.correlation_id,
                    "phase": context.current_phase.value if hasattr(context.current_phase, 'value') else str(context.current_phase),
                    "dry_run": str(context.dry_run)
                },
                {
                    "available_strategies": len(self._strategies),
                    "attempted_strategies": len(context.attempted_strategies)
                }
            )
            
            context.advance_phase(ProvisioningPhase.EXECUTION)
            
            last_error = None
            execution_attempts = []
            
            for strategy in self._strategies:
                strategy_start_time = datetime.now(UTC)
                
                try:
                    if not strategy._initialized:
                        span.add_event("strategy_not_initialized", {"strategy": strategy.name})
                        continue
                    
                    can_handle = await strategy.can_handle(context)
                    if not can_handle:
                        span.add_event("strategy_cannot_handle", {"strategy": strategy.name})
                        continue
                    
                    context.add_attempted_strategy(strategy.name)
                    
                    with tracer.start_as_current_span("strategy_execution") as strategy_span:
                        strategy_span.set_attributes({
                            "strategy.name": strategy.name,
                            "strategy.priority": strategy.priority,
                            "context.correlation_id": context.correlation_id
                        })
                        
                        result = await strategy.execute(context)
                        execution_time = (datetime.now(UTC) - strategy_start_time).total_seconds() * 1000
                        result.execution_time_ms = execution_time
                        
                        self._update_strategy_stats(strategy.name, result.success, execution_time)
                        
                        execution_attempts.append({
                            "strategy": strategy.name,
                            "success": result.success,
                            "execution_time_ms": execution_time,
                            "error": result.error_message
                        })
                        
                        strategy_span.set_attributes({
                            "strategy.success": result.success,
                            "strategy.execution_time_ms": execution_time,
                            "strategy.resources_affected": len(result.resources_affected),
                            "strategy.warnings_count": len(result.warnings)
                        })
                        
                        if result.success:
                            context.advance_phase(ProvisioningPhase.COMPLETION)
                            
                            app_insights.track_custom_event(
                                "provisioning_strategy_succeeded",
                                {
                                    "strategy_name": strategy.name,
                                    "user_id": context.user_id,
                                    "correlation_id": context.correlation_id
                                },
                                {
                                    "execution_time_ms": execution_time,
                                    "resources_affected": len(result.resources_affected)
                                }
                            )
                            
                            strategy_span.set_status(Status(StatusCode.OK))
                            span.set_status(Status(StatusCode.OK))
                            
                            return result
                        else:
                            last_error = result.error_message
                            context.advance_phase(ProvisioningPhase.FALLBACK)
                            
                            app_insights.track_custom_event(
                                "provisioning_strategy_failed",
                                {
                                    "strategy_name": strategy.name,
                                    "user_id": context.user_id,
                                    "correlation_id": context.correlation_id,
                                    "error": result.error_message or "Unknown error"
                                },
                                {
                                    "execution_time_ms": execution_time
                                }
                            )
                            
                            strategy_span.set_status(Status(StatusCode.ERROR, result.error_message or "Strategy failed"))
                            
                            span.add_event("strategy_failed", {
                                "strategy": strategy.name,
                                "error": result.error_message,
                                "execution_time_ms": execution_time
                            })
                
                except Exception as e:
                    execution_time = (datetime.now(UTC) - strategy_start_time).total_seconds() * 1000
                    last_error = str(e)
                    
                    self._update_strategy_stats(strategy.name, False, execution_time)
                    
                    execution_attempts.append({
                        "strategy": strategy.name,
                        "success": False,
                        "execution_time_ms": execution_time,
                        "error": str(e)
                    })
                    
                    span.add_event("strategy_exception", {
                        "strategy": strategy.name,
                        "error": str(e),
                        "exception_type": type(e).__name__
                    })
                    
                    app_insights.track_exception(
                        e,
                        {
                            "strategy_name": strategy.name,
                            "user_id": context.user_id,
                            "correlation_id": context.correlation_id
                        }
                    )
            
            total_execution_time = sum(attempt["execution_time_ms"] for attempt in execution_attempts)
            
            final_result = ExecutionResult.failure_result(
                strategy="orchestrator_all_failed",
                error=f"All {len(self._strategies)} strategies failed. Last error: {last_error}",
                execution_time=total_execution_time,
                warnings=[f"Attempted strategies: {', '.join(context.attempted_strategies)}"]
            )
            
            app_insights.track_custom_event(
                "provisioning_orchestration_failed",
                {
                    "user_id": context.user_id,
                    "correlation_id": context.correlation_id,
                    "last_error": last_error or "Unknown error"
                },
                {
                    "total_strategies_attempted": len(execution_attempts),
                    "total_execution_time_ms": total_execution_time
                }
            )
            
            span.set_attributes({
                "orchestration.success": False,
                "orchestration.strategies_attempted": len(execution_attempts),
                "orchestration.total_execution_time_ms": total_execution_time,
                "orchestration.last_error": last_error or "Unknown error"
            })
            span.set_status(Status(StatusCode.ERROR, f"All strategies failed: {last_error}"))
            
            return final_result
    
    def _update_strategy_stats(self, strategy_name: str, success: bool, execution_time_ms: float) -> None:
        if strategy_name not in self._strategy_stats:
            return
        
        stats = self._strategy_stats[strategy_name]
        stats["total_attempts"] += 1
        stats["last_used"] = datetime.now(UTC).isoformat()
        
        if success:
            stats["successful_attempts"] += 1
        else:
            stats["failed_attempts"] += 1
        
        current_avg = stats["avg_execution_time_ms"]
        total_attempts = stats["total_attempts"]
        stats["avg_execution_time_ms"] = ((current_avg * (total_attempts - 1)) + execution_time_ms) / total_attempts
    
    def get_orchestrator_stats(self) -> Dict[str, Any]:
        return {
            "total_strategies": len(self._strategies),
            "strategy_names": [s.name for s in self._strategies],
            "strategy_priorities": {s.name: s.priority for s in self._strategies},
            "strategy_stats": self._strategy_stats.copy(),
            "initialized_strategies": len([s for s in self._strategies if s._initialized])
        }
    
    async def cleanup_all_strategies(self) -> None:
        with tracer.start_as_current_span("orchestrator_cleanup_strategies") as span:
            cleanup_results = []
            
            for strategy in self._strategies:
                try:
                    await strategy.cleanup()
                    cleanup_results.append(f"{strategy.name}:success")
                except Exception as e:
                    cleanup_results.append(f"{strategy.name}:failed")
                    span.add_event("strategy_cleanup_failed", {
                        "strategy": strategy.name,
                        "error": str(e)
                    })
            
            span.set_attributes({
                "cleanup.total_strategies": len(self._strategies),
                "cleanup.results": cleanup_results
            })
            span.set_status(Status(StatusCode.OK))