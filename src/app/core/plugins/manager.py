from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime, UTC

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .base import Plugin, PluginStatus, PluginType, PluginContext, PluginResult
from .registry import PluginRegistry

tracer = trace.get_tracer(__name__)


class PluginManager:
    def __init__(self, registry: PluginRegistry | None = None):
        self._registry = registry or PluginRegistry()
        self._initialization_lock = asyncio.Lock()
        self._execution_locks: Dict[str, asyncio.Lock] = {}
    
    async def initialize_all(self) -> Dict[str, bool]:
        async with self._initialization_lock:
            with tracer.start_as_current_span("plugin_manager_initialize_all") as span:
                load_order = self._registry.get_load_order()
                initialization_results = {}
                
                span.set_attributes({
                    "plugins.count": len(load_order),
                    "plugins.load_order": load_order
                })
                
                for plugin_name in load_order:
                    plugin = self._registry.get_plugin(plugin_name)
                    if not plugin or not plugin.config.enabled:
                        initialization_results[plugin_name] = False
                        continue
                    
                    try:
                        await self._initialize_plugin(plugin)
                        initialization_results[plugin_name] = True
                        
                    except Exception as e:
                        plugin.set_status(PluginStatus.ERROR, e)
                        initialization_results[plugin_name] = False
                        span.add_event("plugin_initialization_failed", {
                            "plugin": plugin_name,
                            "error": str(e)
                        })
                
                successful_count = sum(1 for success in initialization_results.values() if success)
                
                span.set_attributes({
                    "initialization.successful": successful_count,
                    "initialization.total": len(load_order),
                    "initialization.success_rate": successful_count / len(load_order) if load_order else 0
                })
                
                if successful_count == len(load_order):
                    span.set_status(Status(StatusCode.OK))
                else:
                    span.set_status(Status(StatusCode.ERROR, f"Only {successful_count}/{len(load_order)} plugins initialized successfully"))
                
                return initialization_results
    
    async def _initialize_plugin(self, plugin: Plugin) -> None:
        with tracer.start_as_current_span("plugin_initialization") as span:
            span.set_attributes({
                "plugin.name": plugin.metadata.name,
                "plugin.type": plugin.metadata.plugin_type.value,
                "plugin.version": plugin.metadata.version
            })
            
            try:
                if plugin._initialized:
                    span.set_status(Status(StatusCode.OK, "Already initialized"))
                    return
                
                config_errors = await plugin.validate_configuration(plugin.config.configuration)
                if config_errors:
                    error_msg = f"Configuration validation failed: {', '.join(config_errors)}"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    raise ValueError(error_msg)
                
                await plugin.initialize()
                plugin._initialized = True
                plugin.set_status(PluginStatus.ACTIVE)
                
                self._execution_locks[plugin.metadata.name] = asyncio.Lock()
                
                span.set_attributes({
                    "plugin.initialized": True,
                    "plugin.status": PluginStatus.ACTIVE.value
                })
                span.set_status(Status(StatusCode.OK))
                
            except Exception as e:
                plugin.set_status(PluginStatus.ERROR, e)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
    
    async def execute_plugin(self, plugin_name: str, context: PluginContext) -> PluginResult:
        with tracer.start_as_current_span("plugin_execution") as span:
            span.set_attributes({
                "plugin.name": plugin_name,
                "context.correlation_id": context.correlation_id
            })
            
            plugin = self._registry.get_plugin(plugin_name)
            if not plugin:
                error_msg = f"Plugin {plugin_name} not found"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return PluginResult(
                    correlation_id=context.correlation_id,
                    success=False,
                    error_message=error_msg
                )
            
            if plugin.status != PluginStatus.ACTIVE:
                error_msg = f"Plugin {plugin_name} is not active (status: {plugin.status.value})"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return PluginResult(
                    correlation_id=context.correlation_id,
                    success=False,
                    error_message=error_msg
                )
            
            execution_lock = self._execution_locks.get(plugin_name)
            if execution_lock is None:
                error_msg = f"Plugin {plugin_name} not properly initialized"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return PluginResult(
                    correlation_id=context.correlation_id,
                    success=False,
                    error_message=error_msg
                )
            
            start_time = datetime.now(UTC)
            
            async with execution_lock:
                try:
                    result = await plugin.execute(context)
                    execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                    result.execution_time_ms = execution_time
                    
                    span.set_attributes({
                        "execution.success": result.success,
                        "execution.time_ms": execution_time,
                        "execution.warnings": len(result.warnings)
                    })
                    
                    if result.success:
                        span.set_status(Status(StatusCode.OK))
                    else:
                        span.set_status(Status(StatusCode.ERROR, result.error_message or "Plugin execution failed"))
                    
                    return result
                    
                except Exception as e:
                    execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                    plugin.set_status(PluginStatus.ERROR, e)
                    
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    
                    return PluginResult(
                        correlation_id=context.correlation_id,
                        success=False,
                        error_message=str(e),
                        execution_time_ms=execution_time,
                        metadata={"exception_type": type(e).__name__}
                    )
    
    async def execute_plugins_by_type(self, 
                                     plugin_type: PluginType, 
                                     context: PluginContext,
                                     parallel: bool = False) -> Dict[str, PluginResult]:
        with tracer.start_as_current_span("plugins_by_type_execution") as span:
            span.set_attributes({
                "plugin.type": plugin_type.value,
                "execution.parallel": parallel,
                "context.correlation_id": context.correlation_id
            })
            
            plugins = self._registry.get_plugins_by_type(plugin_type)
            active_plugins = [p for p in plugins if p.status == PluginStatus.ACTIVE and p.config.enabled]
            
            span.set_attributes({
                "plugins.total": len(plugins),
                "plugins.active": len(active_plugins)
            })
            
            if not active_plugins:
                span.set_status(Status(StatusCode.OK, "No active plugins found"))
                return {}
            
            if parallel:
                tasks = [
                    self.execute_plugin(plugin.metadata.name, context) 
                    for plugin in active_plugins
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                execution_results = {}
                for plugin, result in zip(active_plugins, results):
                    if isinstance(result, Exception):
                        execution_results[plugin.metadata.name] = PluginResult(
                            correlation_id=context.correlation_id,
                            success=False,
                            error_message=str(result)
                        )
                    else:
                        execution_results[plugin.metadata.name] = result
            else:
                execution_results = {}
                for plugin in active_plugins:
                    result = await self.execute_plugin(plugin.metadata.name, context)
                    execution_results[plugin.metadata.name] = result
            
            successful_count = sum(1 for r in execution_results.values() if r.success)
            
            span.set_attributes({
                "execution.successful": successful_count,
                "execution.total": len(execution_results),
                "execution.success_rate": successful_count / len(execution_results) if execution_results else 0
            })
            
            if successful_count == len(execution_results):
                span.set_status(Status(StatusCode.OK))
            else:
                span.set_status(Status(StatusCode.ERROR, f"Only {successful_count}/{len(execution_results)} executions successful"))
            
            return execution_results
    
    async def reload_plugin(self, plugin_name: str) -> bool:
        with tracer.start_as_current_span("plugin_reload") as span:
            span.set_attribute("plugin.name", plugin_name)
            
            plugin = self._registry.get_plugin(plugin_name)
            if not plugin:
                span.set_status(Status(StatusCode.ERROR, f"Plugin {plugin_name} not found"))
                return False
            
            if not plugin.config.auto_reload:
                span.set_status(Status(StatusCode.ERROR, "Plugin does not support auto-reload"))
                return False
            
            try:
                await plugin.shutdown()
                plugin.set_status(PluginStatus.INACTIVE)
                plugin._initialized = False
                
                await self._initialize_plugin(plugin)
                
                span.set_attributes({
                    "reload.success": True,
                    "plugin.status": plugin.status.value
                })
                span.set_status(Status(StatusCode.OK))
                
                return True
                
            except Exception as e:
                plugin.set_status(PluginStatus.ERROR, e)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False
    
    async def shutdown_all(self) -> Dict[str, bool]:
        async with self._initialization_lock:
            with tracer.start_as_current_span("plugin_manager_shutdown_all") as span:
                shutdown_results = {}
                
                load_order = self._registry.get_load_order()
                shutdown_order = reversed(load_order)
                
                for plugin_name in shutdown_order:
                    plugin = self._registry.get_plugin(plugin_name)
                    if not plugin or not plugin._initialized:
                        shutdown_results[plugin_name] = True
                        continue
                    
                    try:
                        await plugin.shutdown()
                        plugin.set_status(PluginStatus.INACTIVE)
                        plugin._initialized = False
                        
                        self._execution_locks.pop(plugin_name, None)
                        
                        shutdown_results[plugin_name] = True
                        
                    except Exception as e:
                        plugin.set_status(PluginStatus.ERROR, e)
                        shutdown_results[plugin_name] = False
                        span.add_event("plugin_shutdown_failed", {
                            "plugin": plugin_name,
                            "error": str(e)
                        })
                
                successful_count = sum(1 for success in shutdown_results.values() if success)
                
                span.set_attributes({
                    "shutdown.successful": successful_count,
                    "shutdown.total": len(shutdown_results),
                    "shutdown.success_rate": successful_count / len(shutdown_results) if shutdown_results else 0
                })
                
                if successful_count == len(shutdown_results):
                    span.set_status(Status(StatusCode.OK))
                else:
                    span.set_status(Status(StatusCode.ERROR, f"Only {successful_count}/{len(shutdown_results)} plugins shut down successfully"))
                
                return shutdown_results
    
    def get_manager_stats(self) -> Dict[str, Any]:
        registry_stats = self._registry.get_registry_stats()
        
        return {
            **registry_stats,
            "execution_locks_count": len(self._execution_locks),
            "manager_initialized": len(self._execution_locks) > 0
        }