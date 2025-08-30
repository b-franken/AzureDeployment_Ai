from __future__ import annotations

from typing import Any, Callable, Dict, Type, Optional, Literal
from dataclasses import dataclass
from enum import Enum

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel

tracer = trace.get_tracer(__name__)


class FunctionType(str, Enum):
    RESOURCE_ANALYSIS = "resource_analysis"
    DEPLOYMENT_PLANNING = "deployment_planning"
    COST_ESTIMATION = "cost_estimation"
    DEPENDENCY_ANALYSIS = "dependency_analysis"
    VALIDATION_CHECK = "validation_check"
    RESOURCE_RECOMMENDATION = "resource_recommendation"
    CUSTOM = "custom"


@dataclass
class FunctionInfo:
    name: str
    handler: Callable
    function_type: FunctionType
    description: str
    input_schema: Type[BaseModel] | None = None
    output_schema: Type[BaseModel] | None = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class FunctionRegistry:
    _instance: "FunctionRegistry | None" = None
    _functions: Dict[str, FunctionInfo] = {}
    _categories: Dict[FunctionType, list[str]] = {}
    
    def __new__(cls) -> "FunctionRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._initialized = True
            for func_type in FunctionType:
                self._categories[func_type] = []
    
    def register_function(self,
                         name: str,
                         handler: Callable,
                         function_type: FunctionType,
                         description: str,
                         input_schema: Type[BaseModel] | None = None,
                         output_schema: Type[BaseModel] | None = None,
                         **metadata: Any) -> FunctionInfo:
        
        with tracer.start_as_current_span("function_registration") as span:
            span.set_attributes({
                "function.name": name,
                "function.type": function_type.value,
                "function.has_input_schema": input_schema is not None,
                "function.has_output_schema": output_schema is not None,
                "function.handler_module": handler.__module__,
                "function.handler_name": handler.__name__
            })
            
            if name in self._functions:
                span.add_event("function_already_registered", {"existing_type": self._functions[name].function_type.value})
            
            func_info = FunctionInfo(
                name=name,
                handler=handler,
                function_type=function_type,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                metadata=metadata
            )
            
            self._functions[name] = func_info
            if name not in self._categories[function_type]:
                self._categories[function_type].append(name)
            
            span.set_status(Status(StatusCode.OK))
            return func_info
    
    def get_function(self, name: str) -> FunctionInfo | None:
        with tracer.start_as_current_span("function_retrieval") as span:
            span.set_attribute("function.name", name)
            
            func_info = self._functions.get(name)
            span.set_attributes({
                "function.found": func_info is not None,
                "function.type": func_info.function_type.value if func_info else "None"
            })
            
            if func_info is None:
                span.set_status(Status(StatusCode.ERROR, f"Function {name} not found"))
            else:
                span.set_status(Status(StatusCode.OK))
            
            return func_info
    
    def list_functions(self, function_type: FunctionType | None = None) -> Dict[str, FunctionInfo]:
        with tracer.start_as_current_span("function_listing") as span:
            span.set_attributes({
                "filter.type": function_type.value if function_type else "all",
                "total_functions": len(self._functions)
            })
            
            if function_type is None:
                result = self._functions.copy()
            else:
                result = {
                    name: func_info for name, func_info in self._functions.items()
                    if func_info.function_type == function_type
                }
            
            span.set_attributes({
                "filtered_functions": len(result),
                "available_types": [ft.value for ft in self._categories.keys()]
            })
            span.set_status(Status(StatusCode.OK))
            return result
    
    def get_openai_function_definitions(self) -> list[Dict[str, Any]]:
        with tracer.start_as_current_span("openai_definitions_generation") as span:
            definitions = []
            
            for func_info in self._functions.values():
                if func_info.input_schema:
                    schema = func_info.input_schema.model_json_schema()
                    definition = {
                        "name": func_info.name,
                        "description": func_info.description,
                        "parameters": schema
                    }
                    definitions.append(definition)
            
            span.set_attributes({
                "definitions.count": len(definitions),
                "total_functions": len(self._functions),
                "functions_with_schema": len(definitions)
            })
            span.set_status(Status(StatusCode.OK))
            
            return definitions
    
    def unregister_function(self, name: str) -> bool:
        with tracer.start_as_current_span("function_unregistration") as span:
            span.set_attribute("function.name", name)
            
            if name in self._functions:
                func_info = self._functions[name]
                del self._functions[name]
                
                if name in self._categories[func_info.function_type]:
                    self._categories[func_info.function_type].remove(name)
                
                span.set_attributes({
                    "function.unregistered": True,
                    "function.type": func_info.function_type.value
                })
                span.set_status(Status(StatusCode.OK))
                return True
            else:
                span.set_attribute("function.unregistered", False)
                span.set_status(Status(StatusCode.ERROR, f"Function {name} not found"))
                return False
    
    def get_function_stats(self) -> Dict[str, Any]:
        with tracer.start_as_current_span("function_registry_stats") as span:
            stats = {
                "total_functions": len(self._functions),
                "functions_by_type": {
                    func_type.value: len(func_list) 
                    for func_type, func_list in self._categories.items()
                },
                "functions_with_input_schema": len([
                    f for f in self._functions.values() if f.input_schema
                ]),
                "functions_with_output_schema": len([
                    f for f in self._functions.values() if f.output_schema
                ]),
                "registered_function_names": list(self._functions.keys())
            }
            
            span.set_attributes({
                "stats.total_functions": stats["total_functions"],
                "stats.with_input_schema": stats["functions_with_input_schema"],
                "stats.with_output_schema": stats["functions_with_output_schema"]
            })
            span.set_status(Status(StatusCode.OK))
            
            return stats


_registry = FunctionRegistry()


def register_function(name: str | None = None,
                     function_type: FunctionType = FunctionType.CUSTOM,
                     description: str = "",
                     input_schema: Type[BaseModel] | None = None,
                     output_schema: Type[BaseModel] | None = None,
                     **metadata: Any):
    def decorator(func: Callable) -> Callable:
        func_name = name or func.__name__
        func_description = description or func.__doc__ or f"Function {func_name}"
        
        _registry.register_function(
            name=func_name,
            handler=func,
            function_type=function_type,
            description=func_description,
            input_schema=input_schema,
            output_schema=output_schema,
            **metadata
        )
        return func
    return decorator


def get_function_registry() -> FunctionRegistry:
    return _registry