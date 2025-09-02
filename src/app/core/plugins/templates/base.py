from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import Field

from app.core.schemas.base import BaseSchema

tracer = trace.get_tracer(__name__)


class TemplateFormat(str, Enum):
    BICEP = "bicep"
    TERRAFORM = "terraform"
    ARM = "arm"
    PULUMI = "pulumi"
    CDK = "cdk"


class TemplateCategory(str, Enum):
    COMPUTE = "compute"
    STORAGE = "storage"
    NETWORK = "network"
    DATABASE = "database"
    SECURITY = "security"
    MONITORING = "monitoring"
    INTEGRATION = "integration"
    CUSTOM = "custom"


class TemplateMetadata(BaseSchema):
    name: str
    version: str
    description: str
    author: str
    category: TemplateCategory
    format: TemplateFormat
    tags: list[str] = Field(default_factory=list)
    documentation_url: str | None = None
    repository_url: str | None = None


class TemplateParameter(BaseSchema):
    name: str
    type: str
    description: str
    required: bool = True
    default_value: Any = None
    allowed_values: list[Any] | None = None
    validation_pattern: str | None = None


class TemplateOutput(BaseSchema):
    name: str
    type: str
    description: str
    value_expression: str


class ResourceTemplate(BaseSchema):
    metadata: TemplateMetadata
    parameters: list[TemplateParameter] = Field(default_factory=list)
    outputs: list[TemplateOutput] = Field(default_factory=list)
    template_content: str
    dependencies: list[str] = Field(default_factory=list)
    parent_template: str | None = None


class TemplateContext(BaseSchema):
    parameter_values: dict[str, Any] = Field(default_factory=dict)
    environment: str = "dev"
    deployment_region: str = "westeurope"
    resource_group: str | None = None
    subscription_id: str | None = None
    custom_context: dict[str, Any] = Field(default_factory=dict)


class TemplateRenderResult(BaseSchema):
    success: bool
    rendered_template: str | None = None
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TemplateEngine(ABC):
    def __init__(self) -> None:
        self._templates: dict[str, ResourceTemplate] = {}
        self._template_cache: dict[str, str] = {}

    @abstractmethod
    async def render_template(
        self, template: ResourceTemplate, context: TemplateContext
    ) -> TemplateRenderResult:
        pass

    @abstractmethod
    async def validate_template(self, template: ResourceTemplate) -> list[str]:
        pass

    async def register_template(self, template: ResourceTemplate) -> bool:
        with tracer.start_as_current_span("template_registration") as span:
            template_name = template.metadata.name

            span.set_attributes(
                {
                    "template.name": template_name,
                    "template.version": template.metadata.version,
                    "template.format": template.metadata.format.value,
                    "template.category": template.metadata.category.value,
                    "template.parameters": len(template.parameters),
                    "template.outputs": len(template.outputs),
                }
            )

            try:
                validation_errors = await self.validate_template(template)
                if validation_errors:
                    error_msg = f"Template validation failed: {', '.join(validation_errors)}"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    return False

                self._templates[template_name] = template

                span.set_attributes(
                    {"registration.success": True, "registry.total_templates": len(self._templates)}
                )
                span.set_status(Status(StatusCode.OK))

                return True

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False

    def get_template(self, name: str) -> ResourceTemplate | None:
        with tracer.start_as_current_span("template_retrieval") as span:
            span.set_attributes(
                {"template.name": name, "available_templates": list(self._templates.keys())}
            )

            template = self._templates.get(name)

            span.set_attributes(
                {
                    "template.found": template is not None,
                    "template.format": template.metadata.format.value if template else "unknown",
                    "template.category": (
                        template.metadata.category.value if template else "unknown"
                    ),
                }
            )

            if template is None:
                span.set_status(Status(StatusCode.ERROR, f"Template {name} not found"))
            else:
                span.set_status(Status(StatusCode.OK))

            return template

    def list_templates(
        self, category: TemplateCategory | None = None, format: TemplateFormat | None = None
    ) -> dict[str, ResourceTemplate]:
        with tracer.start_as_current_span("template_listing") as span:
            span.set_attributes(
                {
                    "filter.category": category.value if category else "all",
                    "filter.format": format.value if format else "all",
                    "total_templates": len(self._templates),
                }
            )

            filtered_templates = {}

            for name, template in self._templates.items():
                category_match = category is None or template.metadata.category == category
                format_match = format is None or template.metadata.format == format

                if category_match and format_match:
                    filtered_templates[name] = template

            span.set_attributes(
                {
                    "filtered_templates": len(filtered_templates),
                    "available_categories": [
                        tc.value
                        for tc in set(t.metadata.category for t in self._templates.values())
                    ],
                    "available_formats": [
                        tf.value for tf in set(t.metadata.format for t in self._templates.values())
                    ],
                }
            )
            span.set_status(Status(StatusCode.OK))

            return filtered_templates

    async def render_with_inheritance(
        self, template: ResourceTemplate, context: TemplateContext
    ) -> TemplateRenderResult:
        with tracer.start_as_current_span("template_render_with_inheritance") as span:
            span.set_attributes(
                {
                    "template.name": template.metadata.name,
                    "template.has_parent": template.parent_template is not None,
                    "template.dependencies": len(template.dependencies),
                }
            )

            try:
                if template.parent_template:
                    parent_template = self.get_template(template.parent_template)
                    if not parent_template:
                        error_msg = f"Parent template {template.parent_template} not found"
                        span.set_status(Status(StatusCode.ERROR, error_msg))
                        return TemplateRenderResult(
                            correlation_id=context.correlation_id,
                            success=False,
                            error_message=error_msg,
                        )

                    parent_result = await self.render_template(parent_template, context)
                    if not parent_result.success:
                        span.set_status(
                            Status(StatusCode.ERROR, "Parent template rendering failed")
                        )
                        return parent_result

                    merged_content = self._merge_templates(
                        parent_result.rendered_template or "", template.template_content
                    )
                    merged_template = ResourceTemplate(
                        metadata=template.metadata,
                        parameters=template.parameters,
                        outputs=template.outputs,
                        template_content=merged_content,
                        dependencies=template.dependencies,
                    )

                    result = await self.render_template(merged_template, context)
                else:
                    result = await self.render_template(template, context)

                span.set_attributes(
                    {"render.success": result.success, "render.warnings": len(result.warnings)}
                )

                if result.success:
                    span.set_status(Status(StatusCode.OK))
                else:
                    span.set_status(
                        Status(
                            StatusCode.ERROR, result.error_message or "Template rendering failed"
                        )
                    )

                return result

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))

                return TemplateRenderResult(
                    correlation_id=context.correlation_id, success=False, error_message=str(e)
                )

    def _merge_templates(self, parent_content: str, child_content: str) -> str:
        return f"{parent_content}\n\n{child_content}"

    def validate_parameters(
        self, template: ResourceTemplate, parameter_values: dict[str, Any]
    ) -> list[str]:
        with tracer.start_as_current_span("template_parameter_validation") as span:
            span.set_attributes(
                {
                    "template.name": template.metadata.name,
                    "template.parameters": len(template.parameters),
                    "provided_values": len(parameter_values),
                }
            )

            errors = []

            for param in template.parameters:
                if param.required and param.name not in parameter_values:
                    errors.append(f"Required parameter '{param.name}' is missing")
                    continue

                if param.name not in parameter_values:
                    continue

                value = parameter_values[param.name]

                if param.allowed_values and value not in param.allowed_values:
                    errors.append(
                        f"Parameter '{param.name}' value '{value}' not in allowed values: "
                        f"{param.allowed_values}"
                    )

                if param.validation_pattern:
                    import re

                    if not re.match(param.validation_pattern, str(value)):
                        errors.append(
                            f"Parameter '{param.name}' value '{value}' does not match "
                            f"pattern: {param.validation_pattern}"
                        )

            span.set_attributes(
                {"validation.errors": len(errors), "validation.success": len(errors) == 0}
            )

            if errors:
                span.set_status(
                    Status(
                        StatusCode.ERROR, f"Parameter validation failed with {len(errors)} errors"
                    )
                )
            else:
                span.set_status(Status(StatusCode.OK))

            return errors

    def get_engine_stats(self) -> dict[str, Any]:
        return {
            "total_templates": len(self._templates),
            "cached_templates": len(self._template_cache),
            "templates_by_category": {
                category.value: len(
                    [t for t in self._templates.values() if t.metadata.category == category]
                )
                for category in TemplateCategory
            },
            "templates_by_format": {
                format.value: len(
                    [t for t in self._templates.values() if t.metadata.format == format]
                )
                for format in TemplateFormat
            },
        }
