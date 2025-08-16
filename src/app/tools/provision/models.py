from typing import Any, Literal

from pydantic import BaseModel, Field, validator

Env = Literal["dev", "tst", "acc", "prod"]
Backend = Literal["auto", "terraform", "bicep", "sdk"]


class WebAppPlanModel(BaseModel):
    name: str
    sku: str = "P1v3"
    linux: bool = True


class WebAppParameters(BaseModel):
    resource_group: str
    location: str
    name: str
    runtime: str | None = None
    plan: WebAppPlanModel
    tags: dict[str, str] = Field(default_factory=dict)


class StorageParameters(BaseModel):
    resource_group: str
    location: str
    name: str
    sku: str | None = None
    access_tier: str = "Hot"
    tags: dict[str, str] = Field(default_factory=dict)


class ProvisionSpec(BaseModel):
    product: Literal["web_app", "storage_account"]
    env: Env = "dev"
    backend: Backend = "auto"
    plan_only: bool = True
    parameters: dict[str, Any]

    @validator("parameters", pre=True)
    def validate_parameters(cls: Any, v: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        product = values.get("product")
        if product == "web_app":
            WebAppParameters(**v)
        elif product == "storage_account":
            StorageParameters(**v)
        return v
