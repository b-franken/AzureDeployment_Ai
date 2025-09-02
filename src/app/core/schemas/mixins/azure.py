from __future__ import annotations

from typing import Any, Literal

import structlog
from pydantic import Field, field_validator

logger = structlog.get_logger(__name__)

Environment = Literal["dev", "test", "staging", "prod"]
AzureRegion = Literal["westeurope", "northeurope", "eastus", "westus2", "centralus"]


class AzureMixin:
    subscription_id: str | None = Field(
        default=None, pattern=r"^[a-f0-9-]{36}$", description="Azure subscription identifier"
    )
    resource_group: str | None = Field(
        default=None, min_length=1, max_length=90, description="Azure resource group name"
    )
    location: AzureRegion = Field(default="westeurope", description="Azure deployment region")
    environment: Environment = Field(default="dev", description="Deployment environment")
    tags: dict[str, str] = Field(default_factory=dict, description="Azure resource tags")

    @field_validator("resource_group")
    @classmethod
    def validate_resource_group(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.replace("-", "").replace("_", "").isalnum():
            logger.warning(
                "invalid_resource_group_format",
                resource_group=v,
                message="Resource group should be alphanumeric with hyphens/underscores",
            )
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 50:
            logger.warning(
                "excessive_tags",
                tag_count=len(v),
                message="Azure resources support maximum 50 tags",
            )
            return dict(list(v.items())[:50])

        for key, value in v.items():
            if len(key) > 512 or len(value) > 256:
                logger.warning(
                    "tag_length_exceeded",
                    key=key,
                    value=value,
                    message="Tag key/value exceeds Azure limits",
                )
        return v

    def get_azure_resource_id(self, resource_type: str, resource_name: str) -> str | None:
        if not all([self.subscription_id, self.resource_group]):
            return None
        return (
            f"/subscriptions/{self.subscription_id}"
            f"/resourceGroups/{self.resource_group}"
            f"/providers/{resource_type}/{resource_name}"
        )

    def get_deployment_context(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "resource_group": self.resource_group,
            "location": self.location,
            "environment": self.environment,
            "tags": self.tags,
        }
