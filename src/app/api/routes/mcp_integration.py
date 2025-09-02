"""
API routes for MCP integration with Azure deployment system.
Provides unified access to MCP tools through REST API.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.api.routes.auth import TokenData, require_role
from app.core.logging import get_logger
from app.mcp.mcp_integration import MCPToolProvider
from app.observability.app_insights import app_insights

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)
# app_insights is imported as singleton

router = APIRouter()
mcp_dependency = require_role("mcp_user")


class MCPToolRequest(BaseModel):
    """Request to execute MCP tool."""

    tool_name: str = Field(..., description="Name of the MCP tool to execute")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Tool parameters")
    correlation_id: str | None = Field(None, description="Optional correlation ID for tracking")
    timeout_seconds: int = Field(30, description="Tool execution timeout in seconds", ge=1, le=300)


class MCPToolResponse(BaseModel):
    """Response from MCP tool execution."""

    success: bool = Field(..., description="Execution success status")
    tool_name: str = Field(..., description="Name of the executed tool")
    correlation_id: str = Field(..., description="Request correlation ID")
    execution_time_ms: float = Field(..., description="Execution time in milliseconds")
    result: dict[str, Any] | None = Field(None, description="Tool execution result")
    error: str | None = Field(None, description="Error message if execution failed")


class IntegratedAnalyticsRequest(BaseModel):
    """Request for integrated analytics analysis."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    include_security: bool = Field(True, description="Include security analysis")
    include_cost: bool = Field(True, description="Include cost analysis")
    include_changes: bool = Field(True, description="Include change analysis")
    include_audit: bool = Field(True, description="Include audit analysis")
    time_range: str = Field("24h", description="Time range for analysis")
    security_severity_filter: str = Field("all", description="Security severity filter")


class SecurityAdvisorRequest(BaseModel):
    """Request for security advisor analysis."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str | None = Field(None, description="Specific resource group")
    severity_levels: list[str] = Field(
        default_factory=lambda: ["critical", "high", "medium"],
        description="Security severity levels",
    )
    include_recommendations: bool = Field(True, description="Include recommendations")
    include_compliance_scan: bool = Field(True, description="Include compliance scan")
    include_threat_detection: bool = Field(True, description="Include threat detection")


class CostIntelligenceRequest(BaseModel):
    """Request for cost intelligence analysis."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str | None = Field(None, description="Specific resource group")
    time_range: str = Field("30d", description="Analysis time range")
    include_forecast: bool = Field(True, description="Include cost forecasting")
    include_optimization: bool = Field(True, description="Include optimization recommendations")
    include_anomaly_detection: bool = Field(True, description="Include anomaly detection")
    include_carbon_analysis: bool = Field(False, description="Include carbon footprint")
    cost_threshold_usd: float | None = Field(None, description="Cost threshold in USD")


@router.get("/tools", response_model=list[dict[str, Any]])
async def list_available_tools(
    td: Annotated[TokenData, Depends(mcp_dependency)],
) -> list[dict[str, Any]]:
    """List all available MCP tools."""

    with tracer.start_as_current_span("list_mcp_tools") as span:
        span.set_attribute("user.id", td.user_id)
        span.set_attribute("subscription.id", td.subscription_id or "")

        try:
            provider = MCPToolProvider()
            tools = await provider.list_available_tools()

            logger.info(
                "MCP tools listed",
                extra={
                    "event": "mcp_tools_listed",
                    "user_id": td.user_id,
                    "tools_count": len(tools),
                },
            )

            return tools

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            logger.error(
                "Failed to list MCP tools",
                extra={
                    "event": "mcp_tools_list_failed",
                    "user_id": td.user_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list MCP tools"
            ) from e

        finally:
            provider = MCPToolProvider()
            await provider.disconnect()


@router.post("/execute", response_model=MCPToolResponse)
async def execute_tool(
    request: MCPToolRequest, td: Annotated[TokenData, Depends(mcp_dependency)]
) -> MCPToolResponse:
    """Execute an MCP tool with the provided parameters."""

    correlation_id = request.correlation_id or str(uuid4())

    with tracer.start_as_current_span("execute_mcp_tool") as span:
        span.set_attributes(
            {
                "user.id": td.user_id,
                "subscription.id": td.subscription_id or "",
                "tool.name": request.tool_name,
                "correlation.id": correlation_id,
            }
        )

        import time

        start_time = time.time()

        try:
            provider = MCPToolProvider()

            # Execute tool with timeout
            result = await asyncio.wait_for(
                provider.execute(request.tool_name, request.parameters),
                timeout=request.timeout_seconds,
            )

            execution_time = (time.time() - start_time) * 1000

            response = MCPToolResponse(
                success=True,
                tool_name=request.tool_name,
                correlation_id=correlation_id,
                execution_time_ms=execution_time,
                result=result,
                error=None,
            )

            logger.info(
                "MCP tool executed successfully",
                extra={
                    "event": "mcp_tool_executed",
                    "user_id": td.user_id,
                    "tool_name": request.tool_name,
                    "correlation_id": correlation_id,
                    "execution_time_ms": execution_time,
                },
            )

            # Track in Application Insights
            app_insights.track_custom_event(
                "mcp_tool_execution",
                properties={
                    "tool_name": request.tool_name,
                    "user_id": td.user_id,
                    "correlation_id": correlation_id,
                    "success": "true",
                },
                measurements={
                    "execution_time_ms": execution_time,
                },
            )

            return response

        except TimeoutError:
            execution_time = (time.time() - start_time) * 1000
            span.set_status(Status(StatusCode.ERROR, "Tool execution timeout"))

            logger.warning(
                "MCP tool execution timeout",
                extra={
                    "event": "mcp_tool_timeout",
                    "user_id": td.user_id,
                    "tool_name": request.tool_name,
                    "correlation_id": correlation_id,
                    "timeout_seconds": request.timeout_seconds,
                },
            )

            return MCPToolResponse(
                success=False,
                tool_name=request.tool_name,
                correlation_id=correlation_id,
                execution_time_ms=execution_time,
                result=None,
                error=f"Tool execution timeout after {request.timeout_seconds} seconds",
            )

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            logger.error(
                "MCP tool execution failed",
                extra={
                    "event": "mcp_tool_execution_failed",
                    "user_id": td.user_id,
                    "tool_name": request.tool_name,
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            # Track failure in Application Insights
            app_insights.track_custom_event(
                "mcp_tool_execution",
                properties={
                    "tool_name": request.tool_name,
                    "user_id": td.user_id,
                    "correlation_id": correlation_id,
                    "success": "false",
                    "error": str(e),
                },
                measurements={
                    "execution_time_ms": execution_time,
                },
            )

            return MCPToolResponse(
                success=False,
                tool_name=request.tool_name,
                correlation_id=correlation_id,
                execution_time_ms=execution_time,
                result=None,
                error=str(e),
            )

        finally:
            provider = MCPToolProvider()
            await provider.disconnect()


@router.post("/analytics/integrated", response_model=dict[str, Any])
async def run_integrated_analytics(
    request: IntegratedAnalyticsRequest, td: Annotated[TokenData, Depends(mcp_dependency)]
) -> dict[str, Any]:
    """Run integrated analytics combining security, cost, change, and audit analysis."""

    correlation_id = str(uuid4())

    with tracer.start_as_current_span("integrated_analytics") as span:
        span.set_attributes(
            {
                "user.id": td.user_id,
                "subscription.id": request.subscription_id,
                "correlation.id": correlation_id,
                "include.security": request.include_security,
                "include.cost": request.include_cost,
            }
        )

        try:
            provider = MCPToolProvider()

            parameters = {
                "subscription_id": request.subscription_id,
                "correlation_id": correlation_id,
                "include_security": request.include_security,
                "include_cost": request.include_cost,
                "include_changes": request.include_changes,
                "include_audit": request.include_audit,
                "time_range": request.time_range,
                "security_severity_filter": request.security_severity_filter,
            }

            result = await provider.execute("integrated_analytics", parameters)

            logger.info(
                "Integrated analytics completed",
                extra={
                    "event": "integrated_analytics_completed",
                    "user_id": td.user_id,
                    "subscription_id": request.subscription_id,
                    "correlation_id": correlation_id,
                },
            )

            return result if isinstance(result, dict) else {"result": result}

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            logger.error(
                "Integrated analytics failed",
                extra={
                    "event": "integrated_analytics_failed",
                    "user_id": td.user_id,
                    "subscription_id": request.subscription_id,
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Integrated analytics failed: {e!s}",
            ) from e

        finally:
            provider = MCPToolProvider()
            await provider.disconnect()


@router.post("/security/advisor", response_model=dict[str, Any])
async def run_security_advisor(
    request: SecurityAdvisorRequest, td: Annotated[TokenData, Depends(mcp_dependency)]
) -> dict[str, Any]:
    """Run comprehensive security analysis and advisory."""

    correlation_id = str(uuid4())

    with tracer.start_as_current_span("security_advisor") as span:
        span.set_attributes(
            {
                "user.id": td.user_id,
                "subscription.id": request.subscription_id,
                "correlation.id": correlation_id,
                "resource.group": request.resource_group or "all",
            }
        )

        try:
            provider = MCPToolProvider()

            parameters = {
                "subscription_id": request.subscription_id,
                "resource_group": request.resource_group,
                "severity_levels": request.severity_levels,
                "include_recommendations": request.include_recommendations,
                "include_compliance_scan": request.include_compliance_scan,
                "include_threat_detection": request.include_threat_detection,
                "correlation_id": correlation_id,
            }

            result = await provider.execute("security_advisor", parameters)

            logger.info(
                "Security advisor analysis completed",
                extra={
                    "event": "security_advisor_completed",
                    "user_id": td.user_id,
                    "subscription_id": request.subscription_id,
                    "correlation_id": correlation_id,
                },
            )

            return result if isinstance(result, dict) else {"result": result}

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            logger.error(
                "Security advisor failed",
                extra={
                    "event": "security_advisor_failed",
                    "user_id": td.user_id,
                    "subscription_id": request.subscription_id,
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Security advisor failed: {e!s}",
            ) from e

        finally:
            provider = MCPToolProvider()
            await provider.disconnect()


@router.post("/cost/intelligence", response_model=dict[str, Any])
async def run_cost_intelligence(
    request: CostIntelligenceRequest, td: Annotated[TokenData, Depends(mcp_dependency)]
) -> dict[str, Any]:
    """Run comprehensive cost intelligence analysis."""

    correlation_id = str(uuid4())

    with tracer.start_as_current_span("cost_intelligence") as span:
        span.set_attributes(
            {
                "user.id": td.user_id,
                "subscription.id": request.subscription_id,
                "correlation.id": correlation_id,
                "time.range": request.time_range,
            }
        )

        try:
            provider = MCPToolProvider()

            parameters = {
                "subscription_id": request.subscription_id,
                "resource_group": request.resource_group,
                "time_range": request.time_range,
                "include_forecast": request.include_forecast,
                "include_optimization": request.include_optimization,
                "include_anomaly_detection": request.include_anomaly_detection,
                "include_carbon_analysis": request.include_carbon_analysis,
                "cost_threshold_usd": request.cost_threshold_usd,
                "correlation_id": correlation_id,
            }

            result = await provider.execute("cost_intelligence", parameters)

            logger.info(
                "Cost intelligence analysis completed",
                extra={
                    "event": "cost_intelligence_completed",
                    "user_id": td.user_id,
                    "subscription_id": request.subscription_id,
                    "correlation_id": correlation_id,
                },
            )

            return result if isinstance(result, dict) else {"result": result}

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            logger.error(
                "Cost intelligence failed",
                extra={
                    "event": "cost_intelligence_failed",
                    "user_id": td.user_id,
                    "subscription_id": request.subscription_id,
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Cost intelligence failed: {e!s}",
            ) from e

        finally:
            provider = MCPToolProvider()
            await provider.disconnect()


@router.get("/security/quick-scan")
async def security_quick_scan(
    subscription_id: Annotated[str, Query(description="Azure subscription ID")],
    td: Annotated[TokenData, Depends(mcp_dependency)],
    resource_group: Annotated[str | None, Query(description="Optional resource group")] = None,
) -> dict[str, Any]:
    """Run quick security scan for critical issues only."""

    correlation_id = str(uuid4())

    with tracer.start_as_current_span("security_quick_scan") as span:
        span.set_attributes(
            {
                "user.id": td.user_id,
                "subscription.id": subscription_id,
                "correlation.id": correlation_id,
            }
        )

        try:
            provider = MCPToolProvider()

            parameters = {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "correlation_id": correlation_id,
            }

            result = await provider.execute("security_quick_scan", parameters)

            logger.info(
                "Security quick scan completed",
                extra={
                    "event": "security_quick_scan_completed",
                    "user_id": td.user_id,
                    "subscription_id": subscription_id,
                    "correlation_id": correlation_id,
                },
            )

            return result if isinstance(result, dict) else {"result": result}

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            logger.error(
                "Security quick scan failed",
                extra={
                    "event": "security_quick_scan_failed",
                    "user_id": td.user_id,
                    "subscription_id": subscription_id,
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Security quick scan failed: {e!s}",
            ) from e

        finally:
            provider = MCPToolProvider()
            await provider.disconnect()


@router.get("/cost/quick-insights")
async def cost_quick_insights(
    subscription_id: Annotated[str, Query(description="Azure subscription ID")],
    td: Annotated[TokenData, Depends(mcp_dependency)],
) -> dict[str, Any]:
    """Get quick cost insights and key metrics."""

    correlation_id = str(uuid4())

    with tracer.start_as_current_span("cost_quick_insights") as span:
        span.set_attributes(
            {
                "user.id": td.user_id,
                "subscription.id": subscription_id,
                "correlation.id": correlation_id,
            }
        )

        try:
            provider = MCPToolProvider()

            parameters = {
                "subscription_id": subscription_id,
                "correlation_id": correlation_id,
            }

            result = await provider.execute("cost_quick_insights", parameters)

            logger.info(
                "Cost quick insights completed",
                extra={
                    "event": "cost_quick_insights_completed",
                    "user_id": td.user_id,
                    "subscription_id": subscription_id,
                    "correlation_id": correlation_id,
                },
            )

            return result if isinstance(result, dict) else {"result": result}

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            logger.error(
                "Cost quick insights failed",
                extra={
                    "event": "cost_quick_insights_failed",
                    "user_id": td.user_id,
                    "subscription_id": subscription_id,
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Cost quick insights failed: {e!s}",
            ) from e

        finally:
            provider = MCPToolProvider()
            await provider.disconnect()


@router.get("/health")
async def mcp_health_check(td: Annotated[TokenData, Depends(mcp_dependency)]) -> dict[str, Any]:
    """Check MCP system health and connectivity."""

    with tracer.start_as_current_span("mcp_health_check") as span:
        span.set_attribute("user.id", td.user_id)

        try:
            provider = MCPToolProvider()

            # Test connectivity by listing tools
            tools = await provider.list_available_tools()

            health_status = {
                "status": "healthy",
                "mcp_server": "connected",
                "available_tools": len(tools),
                "tools": [tool.get("name") for tool in tools],
                "timestamp": datetime.utcnow().isoformat(),
            }

            logger.info(
                "MCP health check completed",
                extra={
                    "event": "mcp_health_check",
                    "user_id": td.user_id,
                    "status": "healthy",
                    "tools_count": len(tools),
                },
            )

            return health_status

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            health_status = {
                "status": "unhealthy",
                "mcp_server": "disconnected",
                "error": "An internal error has occurred.",
                "timestamp": datetime.utcnow().isoformat(),
            }

            logger.error(
                "MCP health check failed",
                extra={
                    "event": "mcp_health_check_failed",
                    "user_id": td.user_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            return health_status

        finally:
            provider = MCPToolProvider()
            await provider.disconnect()
