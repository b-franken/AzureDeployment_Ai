from __future__ import annotations

import inspect
from typing import Any, TypeVar, Type, Dict, Set, get_origin, get_args
from functools import wraps
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel

tracer = trace.get_tracer(__name__)

T = TypeVar("T", bound=BaseModel)


class SchemaRegistry:
    _instance: "SchemaRegistry | None" = None
    _schemas: Dict[str, Type[BaseModel]] = {}
    _schema_metadata: Dict[str, Dict[str, Any]] = {}
    _schema_dependencies: Dict[str, Set[str]] = {}
    
    def __new__(cls) -> "SchemaRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._initialized = True
    
    def register_schema(self, 
                       schema_cls: Type[T], 
                       version: str = "1.0.0",
                       category: str = "general") -> Type[T]:
        with tracer.start_as_current_span("schema_registration") as span:
            schema_name = schema_cls.__name__
            
            span.set_attributes({
                "schema.name": schema_name,
                "schema.version": version,
                "schema.category": category,
                "schema.module": schema_cls.__module__
            })
            
            if schema_name in self._schemas:
                existing_version = self._schema_metadata[schema_name].get("version", "unknown")
                span.add_event("schema_already_registered", {
                    "existing_version": existing_version,
                    "new_version": version
                })
            
            self._schemas[schema_name] = schema_cls
            self._schema_metadata[schema_name] = {
                "version": version,
                "category": category,
                "module": schema_cls.__module__,
                "fields": list(schema_cls.model_fields.keys()),
                "field_count": len(schema_cls.model_fields)
            }
            
            self._analyze_dependencies(schema_cls)
            
            span.set_status(Status(StatusCode.OK))
            return schema_cls
    
    def _analyze_dependencies(self, schema_cls: Type[BaseModel]) -> None:
        schema_name = schema_cls.__name__
        dependencies = set()
        
        for field_name, field_info in schema_cls.model_fields.items():
            annotation = field_info.annotation
            if annotation:
                deps = self._extract_type_dependencies(annotation)
                dependencies.update(deps)
        
        self._schema_dependencies[schema_name] = dependencies
    
    def _extract_type_dependencies(self, annotation: Any) -> Set[str]:
        dependencies = set()
        
        origin = get_origin(annotation)
        if origin is not None:
            args = get_args(annotation)
            for arg in args:
                if inspect.isclass(arg) and issubclass(arg, BaseModel):
                    dependencies.add(arg.__name__)
                else:
                    dependencies.update(self._extract_type_dependencies(arg))
        elif inspect.isclass(annotation) and issubclass(annotation, BaseModel):
            dependencies.add(annotation.__name__)
        
        return dependencies
    
    def get_schema(self, schema_name: str) -> Type[BaseModel] | None:
        with tracer.start_as_current_span("schema_retrieval") as span:
            span.set_attribute("schema.name", schema_name)
            
            schema = self._schemas.get(schema_name)
            span.set_attributes({
                "schema.found": schema is not None,
                "schema.type": type(schema).__name__ if schema else "None"
            })
            
            if schema is None:
                span.set_status(Status(StatusCode.ERROR, f"Schema {schema_name} not found"))
            else:
                span.set_status(Status(StatusCode.OK))
            
            return schema
    
    def get_schema_metadata(self, schema_name: str) -> Dict[str, Any] | None:
        with tracer.start_as_current_span("schema_metadata_retrieval") as span:
            span.set_attribute("schema.name", schema_name)
            
            metadata = self._schema_metadata.get(schema_name)
            span.set_attribute("metadata.found", metadata is not None)
            
            return metadata
    
    def list_schemas(self, category: str | None = None) -> Dict[str, Type[BaseModel]]:
        with tracer.start_as_current_span("schema_listing") as span:
            span.set_attributes({
                "filter.category": category or "all",
                "total_schemas": len(self._schemas)
            })
            
            if category is None:
                result = self._schemas.copy()
            else:
                result = {
                    name: schema for name, schema in self._schemas.items()
                    if self._schema_metadata.get(name, {}).get("category") == category
                }
            
            span.set_attributes({
                "filtered_schemas": len(result),
                "categories": list(set(
                    meta.get("category", "general") 
                    for meta in self._schema_metadata.values()
                ))
            })
            span.set_status(Status(StatusCode.OK))
            return result
    
    def get_dependencies(self, schema_name: str) -> Set[str]:
        with tracer.start_as_current_span("schema_dependencies") as span:
            span.set_attribute("schema.name", schema_name)
            
            deps = self._schema_dependencies.get(schema_name, set())
            span.set_attributes({
                "dependencies.count": len(deps),
                "dependencies.list": list(deps)
            })
            span.set_status(Status(StatusCode.OK))
            return deps
    
    def validate_schema_integrity(self) -> Dict[str, Any]:
        with tracer.start_as_current_span("schema_integrity_check") as span:
            missing_deps = {}
            circular_deps = []
            
            for schema_name, deps in self._schema_dependencies.items():
                missing = deps - set(self._schemas.keys())
                if missing:
                    missing_deps[schema_name] = list(missing)
                
                if self._has_circular_dependency(schema_name, set()):
                    circular_deps.append(schema_name)
            
            integrity_report = {
                "total_schemas": len(self._schemas),
                "missing_dependencies": missing_deps,
                "circular_dependencies": circular_deps,
                "integrity_ok": not missing_deps and not circular_deps
            }
            
            span.set_attributes({
                "integrity.total_schemas": len(self._schemas),
                "integrity.missing_deps": len(missing_deps),
                "integrity.circular_deps": len(circular_deps),
                "integrity.ok": integrity_report["integrity_ok"]
            })
            
            if not integrity_report["integrity_ok"]:
                span.set_status(Status(StatusCode.ERROR, "Schema integrity issues found"))
            else:
                span.set_status(Status(StatusCode.OK))
            
            return integrity_report
    
    def _has_circular_dependency(self, schema_name: str, visited: Set[str]) -> bool:
        if schema_name in visited:
            return True
        
        visited.add(schema_name)
        deps = self._schema_dependencies.get(schema_name, set())
        
        for dep in deps:
            if self._has_circular_dependency(dep, visited.copy()):
                return True
        
        return False


_registry = SchemaRegistry()


def register_schema(version: str = "1.0.0", category: str = "general"):
    def decorator(cls: Type[T]) -> Type[T]:
        return _registry.register_schema(cls, version, category)
    return decorator


def get_schema(schema_name: str) -> Type[BaseModel] | None:
    return _registry.get_schema(schema_name)


def list_schemas(category: str | None = None) -> Dict[str, Type[BaseModel]]:
    return _registry.list_schemas(category)