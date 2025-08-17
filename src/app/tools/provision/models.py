from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Env = Literal["dev", "tst", "acc", "prod"]
Backend = Literal["auto", "terraform", "bicep", "sdk"]


class WebAppPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    sku: str = "P1v3"
    linux: bool = True


class WebAppParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_group: str
    location: str
    name: str
    runtime: str | None = None
    plan: WebAppPlanModel
    tags: dict[str, str] = Field(default_factory=dict)


class StorageParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_group: str
    location: str
    name: str
    sku: str | None = None
    access_tier: Literal["Hot", "Cool"] = "Hot"
    tags: dict[str, str] = Field(default_factory=dict)


class AksParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_group: str
    location: str
    name: str
    dns_prefix: str
    node_count: int = 2
    tags: dict[str, str] = Field(default_factory=dict)


class AcrParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_group: str
    location: str
    name: str
    sku: str = "Basic"
    admin_user_enabled: bool = True
    tags: dict[str, str] = Field(default_factory=dict)


class ApimParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_group: str
    location: str
    name: str
    sku_name: str = "Developer"
    capacity: int = 1
    publisher_email: str = "admin@contoso.com"
    publisher_name: str = "Contoso"
    tags: dict[str, str] = Field(default_factory=dict)


class EventHubParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_group: str
    location: str
    name: str
    tier: Literal["Basic", "Standard", "Premium"] = "Standard"
    capacity: int = 1
    auto_inflate: bool = True
    max_throughput: int = 10
    tags: dict[str, str] = Field(default_factory=dict)


class ProvisionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product: Literal[
        "web_app",
        "storage_account",
        "aks_cluster",
        "container_registry",
        "api_management",
        "event_hub",
    ]
    env: Env = "dev"
    backend: Backend = "auto"
    plan_only: bool = True
    parameters: dict[str, Any]

    @model_validator(mode="after")
    def _validate_parameters(self) -> "ProvisionSpec":
        if self.product == "web_app":
            self.parameters = WebAppParameters(**self.parameters).model_dump(mode="python")
        elif self.product == "storage_account":
            self.parameters = StorageParameters(**self.parameters).model_dump(mode="python")
        elif self.product == "aks_cluster":
            self.parameters = AksParameters(**self.parameters).model_dump(mode="python")
        elif self.product == "container_registry":
            self.parameters = AcrParameters(**self.parameters).model_dump(mode="python")
        elif self.product == "api_management":
            self.parameters = ApimParameters(**self.parameters).model_dump(mode="python")
        elif self.product == "event_hub":
            self.parameters = EventHubParameters(**self.parameters).model_dump(mode="python")
        else:
            raise ValueError(f"Unknown product: {self.product!r}")
        return self
