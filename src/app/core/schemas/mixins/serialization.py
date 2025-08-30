from __future__ import annotations

from typing import Any, Literal
import json
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer(__name__)

SerializationFormat = Literal["json", "yaml", "compact", "debug"]


class SerializationMixin:
    
    def to_dict(self, exclude_none: bool = True, by_alias: bool = True) -> dict[str, Any]:
        with tracer.start_as_current_span("schema_serialization_dict") as span:
            span.set_attributes({
                "schema.name": self.__class__.__name__,
                "serialization.exclude_none": exclude_none,
                "serialization.by_alias": by_alias
            })
            
            data = self.model_dump(exclude_none=exclude_none, by_alias=by_alias)
            span.set_attribute("serialization.field_count", len(data))
            span.set_status(Status(StatusCode.OK))
            return data
    
    def to_json(self, 
                format_type: SerializationFormat = "json",
                exclude_none: bool = True) -> str:
        with tracer.start_as_current_span("schema_serialization_json") as span:
            span.set_attributes({
                "schema.name": self.__class__.__name__,
                "serialization.format": format_type,
                "serialization.exclude_none": exclude_none
            })
            
            data = self.model_dump(exclude_none=exclude_none)
            
            if format_type == "compact":
                result = json.dumps(data, separators=(',', ':'), default=str)
            elif format_type == "debug":
                result = json.dumps(data, indent=2, sort_keys=True, default=str)
            else:
                result = json.dumps(data, indent=None, default=str)
            
            span.set_attributes({
                "serialization.size_bytes": len(result),
                "serialization.field_count": len(data)
            })
            span.set_status(Status(StatusCode.OK))
            return result
    
    def to_api_response(self) -> dict[str, Any]:
        with tracer.start_as_current_span("schema_api_response") as span:
            span.set_attribute("schema.name", self.__class__.__name__)
            
            api_data = self.model_dump(by_alias=True, exclude_none=True)
            response = {
                "data": api_data,
                "schema": {
                    "name": self.__class__.__name__,
                    "version": getattr(self, "_schema_version", "1.0.0")
                }
            }
            
            span.set_status(Status(StatusCode.OK))
            return response
    
    def extract_summary(self, max_fields: int = 5) -> dict[str, Any]:
        with tracer.start_as_current_span("schema_extract_summary") as span:
            span.set_attributes({
                "schema.name": self.__class__.__name__,
                "summary.max_fields": max_fields
            })
            
            full_data = self.model_dump(exclude_none=True)
            summary_fields = dict(list(full_data.items())[:max_fields])
            
            if len(full_data) > max_fields:
                summary_fields["_truncated"] = f"{len(full_data) - max_fields} more fields"
            
            span.set_attributes({
                "summary.total_fields": len(full_data),
                "summary.included_fields": len(summary_fields)
            })
            span.set_status(Status(StatusCode.OK))
            return summary_fields