"""
MCP tool for integrated Azure analytics combining audit, security, cost and change analysis.
Provides unified access to all analytics capabilities through MCP protocol.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.observability.app_insights import app_insights
from app.platform.audit.logger import AuditLogger, AuditQuery
from app.tools.azure.clients import Clients
from app.tools.finops.analyzer import CostManagementSystem, CostOptimizationStrategy

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)
# app_insights is imported as singleton


class SecurityAnalysisRequest(BaseModel):
    """Request for security analysis."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str | None = Field(None, description="Specific resource group to analyze")
    start_date: datetime | None = Field(None, description="Start date for analysis")
    end_date: datetime | None = Field(None, description="End date for analysis")
    severity_filter: Literal["critical", "high", "medium", "low", "all"] = Field(
        "all", description="Security severity filter"
    )


class ChangeAnalysisRequest(BaseModel):
    """Request for change analysis."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str | None = Field(None, description="Specific resource group to analyze")
    time_range: Literal["1h", "6h", "12h", "24h", "7d", "30d"] = Field(
        "24h", description="Time range for change analysis"
    )
    change_types: list[str] = Field(
        default_factory=lambda: ["create", "update", "delete"],
        description="Types of changes to include",
    )


class AuditAnalysisRequest(BaseModel):
    """Request for audit log analysis."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    user_id: str | None = Field(None, description="Filter by specific user")
    start_date: datetime | None = Field(None, description="Start date for audit logs")
    end_date: datetime | None = Field(None, description="End date for audit logs")
    operation_filter: str | None = Field(None, description="Filter by operation type")
    resource_filter: str | None = Field(None, description="Filter by resource type")


class IntegratedAnalyticsResponse(BaseModel):
    """Unified response for integrated analytics."""

    success: bool = Field(..., description="Whether the analysis succeeded")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Analysis timestamp")
    correlation_id: str = Field(..., description="Request correlation ID")
    subscription_id: str = Field(..., description="Azure subscription ID")

    # Security Analysis
    security_score: float | None = Field(None, description="Overall security score (0-100)")
    security_findings: list[dict[str, Any]] = Field(
        default_factory=list, description="Security findings and recommendations"
    )
    compliance_status: dict[str, Any] = Field(
        default_factory=dict, description="Compliance status by framework"
    )

    # Cost Analysis
    current_month_spend: float | None = Field(None, description="Current month spend in USD")
    cost_trend: str | None = Field(None, description="Cost trend (increasing/decreasing/stable)")
    cost_savings_potential: float | None = Field(
        None, description="Estimated monthly savings potential"
    )
    top_cost_resources: list[dict[str, Any]] = Field(
        default_factory=list, description="Top cost-consuming resources"
    )

    # Change Analysis
    recent_changes_count: int = Field(0, description="Number of recent changes")
    high_risk_changes: list[dict[str, Any]] = Field(
        default_factory=list, description="High-risk changes requiring attention"
    )
    change_velocity: float | None = Field(None, description="Changes per day")

    # Audit Analysis
    audit_events_count: int = Field(0, description="Number of audit events in period")
    failed_operations_count: int = Field(0, description="Number of failed operations")
    suspicious_activities: list[dict[str, Any]] = Field(
        default_factory=list, description="Suspicious activities detected"
    )
    top_users: list[dict[str, Any]] = Field(default_factory=list, description="Most active users")

    # Integrated Insights
    risk_score: float | None = Field(None, description="Overall risk score (0-100)")
    recommendations: list[dict[str, Any]] = Field(
        default_factory=list, description="Integrated recommendations"
    )
    alerts: list[dict[str, Any]] = Field(
        default_factory=list, description="Critical alerts requiring immediate attention"
    )


class IntegratedAnalyticsTool:
    """Integrated analytics tool combining security, cost, change, and audit analysis."""

    def __init__(self) -> None:
        self.audit_logger = AuditLogger()
        self.cost_system = CostManagementSystem()
        self.clients: Clients | None = None

    async def _ensure_clients(self) -> Clients:
        """Ensure Azure clients are initialized."""
        if self.clients is None:
            from app.tools.azure.clients import get_clients

            self.clients = await get_clients(None)
        return self.clients

    async def analyze_security_posture(
        self,
        request: SecurityAnalysisRequest,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Analyze security posture using Azure Security Center and custom rules."""

        with tracer.start_as_current_span("security_analysis") as span:
            span.set_attributes(
                {
                    "subscription_id": request.subscription_id,
                    "correlation_id": correlation_id,
                    "severity_filter": request.severity_filter,
                }
            )

            try:
                clients = await self._ensure_clients()

                # Get security assessments from Security Center
                security_findings = []
                compliance_status = {}
                security_score = 0.0

                # Simulate security analysis (replace with actual Azure Security Center API calls)
                findings = await self._get_security_findings(clients, request)
                security_findings.extend(findings)

                # Calculate security score based on findings
                if findings:
                    critical_count = sum(1 for f in findings if f.get("severity") == "critical")
                    high_count = sum(1 for f in findings if f.get("severity") == "high")
                    security_score = max(0, 100 - (critical_count * 20) - (high_count * 10))
                else:
                    security_score = 95.0  # Default good score

                # Get compliance status
                compliance_status = await self._get_compliance_status(request.subscription_id)

                logger.info(
                    "Security analysis completed",
                    extra={
                        "event": "security_analysis_completed",
                        "subscription_id": request.subscription_id,
                        "findings_count": len(security_findings),
                        "security_score": security_score,
                        "correlation_id": correlation_id,
                    },
                )

                return {
                    "security_score": security_score,
                    "security_findings": security_findings,
                    "compliance_status": compliance_status,
                }

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(
                    "Security analysis failed",
                    extra={
                        "event": "security_analysis_failed",
                        "subscription_id": request.subscription_id,
                        "error": str(e),
                        "correlation_id": correlation_id,
                    },
                    exc_info=True,
                )
                raise

    async def analyze_cost_optimization(
        self,
        subscription_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Analyze cost optimization opportunities."""

        with tracer.start_as_current_span("cost_analysis") as span:
            span.set_attributes(
                {
                    "subscription_id": subscription_id,
                    "correlation_id": correlation_id,
                }
            )

            try:
                # Get current cost insights
                cost_data = await self.cost_system.get_cost_insights(subscription_id)

                # Get optimization recommendations
                recommendations = await self.cost_system.get_optimization_recommendations(
                    subscription_id,
                    strategy=CostOptimizationStrategy.BALANCED,
                    min_savings_threshold=10.0,
                )

                # Calculate cost trend
                current_spend = (
                    cost_data.get("current_month_spend", 0) if isinstance(cost_data, dict) else 0
                )
                last_spend = (
                    cost_data.get("last_month_spend", 0) if isinstance(cost_data, dict) else 0
                )

                if last_spend > 0:
                    change_pct = ((current_spend - last_spend) / last_spend) * 100
                    if change_pct > 10:
                        trend = "increasing"
                    elif change_pct < -10:
                        trend = "decreasing"
                    else:
                        trend = "stable"
                else:
                    trend = "stable"

                # Calculate savings potential
                savings_potential = sum(
                    getattr(r, "estimated_monthly_savings", 0) for r in (recommendations or [])
                )

                # Get top cost resources
                top_resources = (
                    cost_data.get("cost_saving_opportunities", [])[:5]
                    if isinstance(cost_data, dict)
                    else []
                )

                logger.info(
                    "Cost analysis completed",
                    extra={
                        "event": "cost_analysis_completed",
                        "subscription_id": subscription_id,
                        "current_spend": current_spend,
                        "savings_potential": savings_potential,
                        "correlation_id": correlation_id,
                    },
                )

                return {
                    "current_month_spend": current_spend,
                    "cost_trend": trend,
                    "cost_savings_potential": savings_potential,
                    "top_cost_resources": top_resources,
                }

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(
                    "Cost analysis failed",
                    extra={
                        "event": "cost_analysis_failed",
                        "subscription_id": subscription_id,
                        "error": str(e),
                        "correlation_id": correlation_id,
                    },
                    exc_info=True,
                )
                raise

    async def analyze_recent_changes(
        self,
        request: ChangeAnalysisRequest,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Analyze recent infrastructure changes."""

        with tracer.start_as_current_span("change_analysis") as span:
            span.set_attributes(
                {
                    "subscription_id": request.subscription_id,
                    "time_range": request.time_range,
                    "correlation_id": correlation_id,
                }
            )

            try:
                clients = await self._ensure_clients()

                # Calculate time range
                time_ranges = {
                    "1h": timedelta(hours=1),
                    "6h": timedelta(hours=6),
                    "12h": timedelta(hours=12),
                    "24h": timedelta(days=1),
                    "7d": timedelta(days=7),
                    "30d": timedelta(days=30),
                }

                end_time = datetime.utcnow()
                start_time = end_time - time_ranges.get(request.time_range, timedelta(days=1))

                # Get activity log entries for changes
                changes = await self._get_activity_log_changes(
                    clients, request.subscription_id, start_time, end_time, request.change_types
                )

                # Identify high-risk changes
                high_risk_changes = [
                    change
                    for change in changes
                    if change.get("risk_level") == "high"
                    or change.get("operation_type") in ["delete", "security_update"]
                ]

                # Calculate change velocity (changes per day)
                days_in_range = (end_time - start_time).days or 1
                change_velocity = len(changes) / days_in_range

                logger.info(
                    "Change analysis completed",
                    extra={
                        "event": "change_analysis_completed",
                        "subscription_id": request.subscription_id,
                        "changes_count": len(changes),
                        "high_risk_count": len(high_risk_changes),
                        "correlation_id": correlation_id,
                    },
                )

                return {
                    "recent_changes_count": len(changes),
                    "high_risk_changes": high_risk_changes,
                    "change_velocity": change_velocity,
                }

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(
                    "Change analysis failed",
                    extra={
                        "event": "change_analysis_failed",
                        "subscription_id": request.subscription_id,
                        "error": str(e),
                        "correlation_id": correlation_id,
                    },
                    exc_info=True,
                )
                raise

    async def analyze_audit_logs(
        self,
        request: AuditAnalysisRequest,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Analyze audit logs for security and compliance insights."""

        with tracer.start_as_current_span("audit_analysis") as span:
            span.set_attributes(
                {
                    "subscription_id": request.subscription_id,
                    "correlation_id": correlation_id,
                    "user_id": request.user_id or "all",
                }
            )

            try:
                # Set default time range if not provided
                end_date = request.end_date or datetime.utcnow()
                start_date = request.start_date or (end_date - timedelta(days=7))

                # Query audit logs
                audit_query = AuditQuery(
                    start_time=start_date,
                    end_time=end_date,
                    user_ids=[request.user_id] if request.user_id else None,
                    limit=1000,
                )

                events = await self.audit_logger.query_events(audit_query)

                # Analyze events
                failed_operations = [
                    event
                    for event in events
                    if getattr(event, "status", "").lower() in ["failed", "error"]
                ]

                # Detect suspicious activities
                suspicious_activities = await self._detect_suspicious_activities(events)

                # Get top users by activity
                user_activity: dict[str, int] = {}
                for event in events:
                    user_id = getattr(event, "user_id", "unknown")
                    user_activity[user_id] = user_activity.get(user_id, 0) + 1

                top_users = [
                    {"user_id": user_id, "activity_count": count}
                    for user_id, count in sorted(
                        user_activity.items(), key=lambda x: x[1], reverse=True
                    )[:10]
                ]

                logger.info(
                    "Audit analysis completed",
                    extra={
                        "event": "audit_analysis_completed",
                        "subscription_id": request.subscription_id,
                        "events_count": len(events),
                        "failed_operations": len(failed_operations),
                        "suspicious_count": len(suspicious_activities),
                        "correlation_id": correlation_id,
                    },
                )

                return {
                    "audit_events_count": len(events),
                    "failed_operations_count": len(failed_operations),
                    "suspicious_activities": suspicious_activities,
                    "top_users": top_users,
                }

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(
                    "Audit analysis failed",
                    extra={
                        "event": "audit_analysis_failed",
                        "subscription_id": request.subscription_id,
                        "error": str(e),
                        "correlation_id": correlation_id,
                    },
                    exc_info=True,
                )
                raise

    async def generate_integrated_insights(
        self,
        subscription_id: str,
        security_data: dict[str, Any],
        cost_data: dict[str, Any],
        change_data: dict[str, Any],
        audit_data: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        """Generate integrated insights and recommendations."""

        try:
            # Calculate overall risk score
            security_score = security_data.get("security_score", 95)
            failed_ops_ratio = audit_data.get("failed_operations_count", 0) / max(
                audit_data.get("audit_events_count", 1), 1
            )
            high_risk_changes = len(change_data.get("high_risk_changes", []))

            # Risk score calculation (0-100, lower is riskier)
            risk_score = (
                (security_score * 0.4)  # 40% security weight
                + ((1 - failed_ops_ratio) * 100 * 0.3)  # 30% audit weight
                # 30% change weight
                + (max(0, 100 - high_risk_changes * 10) * 0.3)
            )

            # Generate recommendations
            recommendations = []
            alerts = []

            # Security recommendations
            if security_score < 70:
                recommendations.append(
                    {
                        "type": "security",
                        "priority": "high",
                        "title": "Improve Security Posture",
                        "description": (
                            "Multiple security findings detected. "
                            "Review and remediate critical vulnerabilities."
                        ),
                        "action": "Review security findings and implement recommended fixes",
                    }
                )

            # Cost recommendations
            cost_savings = cost_data.get("cost_savings_potential", 0)
            if cost_savings > 100:  # $100+ monthly savings potential
                recommendations.append(
                    {
                        "type": "cost",
                        "priority": "medium",
                        "title": "Cost Optimization Opportunity",
                        "description": (
                            f"Potential monthly savings of ${cost_savings:.2f} identified"
                        ),
                        "action": "Review and implement cost optimization recommendations",
                    }
                )

            # Change management recommendations
            if change_data.get("change_velocity", 0) > 10:  # More than 10 changes per day
                recommendations.append(
                    {
                        "type": "change_management",
                        "priority": "medium",
                        "title": "High Change Velocity Detected",
                        "description": "Unusually high rate of infrastructure changes detected",
                        "action": "Review change management processes and approval workflows",
                    }
                )

            # Generate alerts for critical issues
            if len(audit_data.get("suspicious_activities", [])) > 0:
                alerts.append(
                    {
                        "type": "security",
                        "severity": "critical",
                        "title": "Suspicious Activities Detected",
                        "description": "Potentially malicious activities found in audit logs",
                        "action": "Investigate suspicious activities immediately",
                    }
                )

            if failed_ops_ratio > 0.1:  # More than 10% failed operations
                alerts.append(
                    {
                        "type": "operational",
                        "severity": "high",
                        "title": "High Failure Rate",
                        "description": (
                            f"High failure rate detected: {failed_ops_ratio:.1%} "
                            "of operations failed"
                        ),
                        "action": "Investigate root cause of operation failures",
                    }
                )

            logger.info(
                "Integrated insights generated",
                extra={
                    "event": "integrated_insights_generated",
                    "subscription_id": subscription_id,
                    "risk_score": risk_score,
                    "recommendations_count": len(recommendations),
                    "alerts_count": len(alerts),
                    "correlation_id": correlation_id,
                },
            )

            return {
                "risk_score": risk_score,
                "recommendations": recommendations,
                "alerts": alerts,
            }

        except Exception as e:
            logger.error(
                "Failed to generate integrated insights",
                extra={
                    "event": "integrated_insights_failed",
                    "subscription_id": subscription_id,
                    "error": str(e),
                    "correlation_id": correlation_id,
                },
                exc_info=True,
            )
            return {
                "risk_score": 50.0,
                "recommendations": [],
                "alerts": [
                    {
                        "type": "system",
                        "severity": "medium",
                        "title": "Analysis Incomplete",
                        "description": "Some analysis components failed to complete",
                        "action": "Retry analysis or contact support",
                    }
                ],
            }

    async def _get_security_findings(
        self, clients: Clients, request: SecurityAnalysisRequest
    ) -> list[dict[str, Any]]:
        """Get security findings from Azure Security Center."""
        try:
            # This would integrate with Azure Security Center API
            # For now, return simulated findings
            return [
                {
                    "id": "sec-001",
                    "title": "Storage Account Public Access Enabled",
                    "severity": "high",
                    "resource_type": "Microsoft.Storage/storageAccounts",
                    "description": "Storage account allows public blob access",
                    "remediation": "Disable public blob access unless required",
                },
                {
                    "id": "sec-002",
                    "title": "VM Missing Security Updates",
                    "severity": "medium",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "description": "Virtual machine has pending security updates",
                    "remediation": "Install latest security updates",
                },
            ]
        except Exception as e:
            logger.error(f"Failed to get security findings: {e}")
            return []

    async def _get_compliance_status(self, subscription_id: str) -> dict[str, Any]:
        """Get compliance status for various frameworks."""
        try:
            # This would integrate with Azure Policy and Compliance API
            return {
                "azure_security_benchmark": {
                    "score": 85,
                    "compliant_controls": 42,
                    "total_controls": 50,
                },
                "iso_27001": {"score": 78, "compliant_controls": 156, "total_controls": 200},
                "pci_dss": {"score": 92, "compliant_controls": 110, "total_controls": 120},
            }
        except Exception as e:
            logger.error(f"Failed to get compliance status: {e}")
            return {}

    async def _get_activity_log_changes(
        self,
        clients: Clients,
        subscription_id: str,
        start_time: datetime,
        end_time: datetime,
        change_types: list[str],
    ) -> list[dict[str, Any]]:
        """Get activity log changes from Azure Monitor."""
        try:
            # This would integrate with Azure Activity Log API
            # For now, return simulated changes
            return [
                {
                    "id": "change-001",
                    "timestamp": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
                    "operation_type": "create",
                    "resource_type": "Microsoft.Storage/storageAccounts",
                    "resource_name": "mystorage001",
                    "user": "admin@company.com",
                    "status": "succeeded",
                    "risk_level": "low",
                },
                {
                    "id": "change-002",
                    "timestamp": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
                    "operation_type": "delete",
                    "resource_type": "Microsoft.Network/networkSecurityGroups",
                    "resource_name": "nsg-prod-001",
                    "user": "admin@company.com",
                    "status": "succeeded",
                    "risk_level": "high",
                },
            ]
        except Exception as e:
            logger.error(f"Failed to get activity log changes: {e}")
            return []

    async def _detect_suspicious_activities(self, events: list[Any]) -> list[dict[str, Any]]:
        """Detect suspicious activities in audit events."""
        try:
            suspicious = []

            # Group events by user
            user_events: dict[str, list[Any]] = {}
            for event in events:
                user_id = getattr(event, "user_id", "unknown")
                if user_id not in user_events:
                    user_events[user_id] = []
                user_events[user_id].append(event)

            # Detect unusual patterns
            for user_id, user_event_list in user_events.items():
                # Check for high frequency of failed operations
                failed_count = sum(
                    1
                    for e in user_event_list
                    if getattr(e, "status", "").lower() in ["failed", "error"]
                )

                if failed_count > 10:  # More than 10 failed operations
                    suspicious.append(
                        {
                            "type": "high_failure_rate",
                            "user_id": user_id,
                            "description": f"User has {failed_count} failed operations",
                            "severity": "medium",
                            "recommendation": "Investigate user account for potential compromise",
                        }
                    )

                # Check for operations outside business hours
                business_hour_violations = 0
                for event in user_event_list:
                    timestamp = getattr(event, "timestamp", datetime.utcnow())
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

                    # Business hours: 8 AM - 6 PM weekdays
                    if (
                        timestamp.weekday() >= 5  # Weekend
                        or timestamp.hour < 8
                        or timestamp.hour >= 18
                    ):  # Outside business hours
                        business_hour_violations += 1

                if business_hour_violations > 5:  # More than 5 operations outside business hours
                    suspicious.append(
                        {
                            "type": "off_hours_activity",
                            "user_id": user_id,
                            "description": (
                                f"User has {business_hour_violations} operations "
                                "outside business hours"
                            ),
                            "severity": "low",
                            "recommendation": "Verify if off-hours activity is expected",
                        }
                    )

            return suspicious

        except Exception as e:
            logger.error(f"Failed to detect suspicious activities: {e}")
            return []


async def run_integrated_analysis(
    subscription_id: str,
    correlation_id: str,
    security_request: SecurityAnalysisRequest | None = None,
    change_request: ChangeAnalysisRequest | None = None,
    audit_request: AuditAnalysisRequest | None = None,
    include_cost_analysis: bool = True,
) -> IntegratedAnalyticsResponse:
    """Run comprehensive integrated analytics analysis."""

    with tracer.start_as_current_span("integrated_analysis") as span:
        span.set_attributes(
            {
                "subscription_id": subscription_id,
                "correlation_id": correlation_id,
                "include_cost": include_cost_analysis,
            }
        )

        tool = IntegratedAnalyticsTool()
        response = IntegratedAnalyticsResponse.model_validate(
            {"success": True, "correlation_id": correlation_id, "subscription_id": subscription_id}
        )

        try:
            # Run security analysis
            if security_request:
                security_data = await tool.analyze_security_posture(
                    security_request, correlation_id
                )
                response.security_score = security_data.get("security_score")
                response.security_findings = security_data.get("security_findings", [])
                response.compliance_status = security_data.get("compliance_status", {})
            else:
                security_data = {}

            # Run cost analysis
            if include_cost_analysis:
                cost_data = await tool.analyze_cost_optimization(subscription_id, correlation_id)
                response.current_month_spend = cost_data.get("current_month_spend")
                response.cost_trend = cost_data.get("cost_trend")
                response.cost_savings_potential = cost_data.get("cost_savings_potential")
                response.top_cost_resources = cost_data.get("top_cost_resources", [])
            else:
                cost_data = {}

            # Run change analysis
            if change_request:
                change_data = await tool.analyze_recent_changes(change_request, correlation_id)
                response.recent_changes_count = change_data.get("recent_changes_count", 0)
                response.high_risk_changes = change_data.get("high_risk_changes", [])
                response.change_velocity = change_data.get("change_velocity")
            else:
                change_data = {}

            # Run audit analysis
            if audit_request:
                audit_data = await tool.analyze_audit_logs(audit_request, correlation_id)
                response.audit_events_count = audit_data.get("audit_events_count", 0)
                response.failed_operations_count = audit_data.get("failed_operations_count", 0)
                response.suspicious_activities = audit_data.get("suspicious_activities", [])
                response.top_users = audit_data.get("top_users", [])
            else:
                audit_data = {}

            # Generate integrated insights
            insights = await tool.generate_integrated_insights(
                subscription_id,
                security_data,
                cost_data,
                change_data,
                audit_data,
                correlation_id,
            )

            response.risk_score = insights.get("risk_score")
            response.recommendations = insights.get("recommendations", [])
            response.alerts = insights.get("alerts", [])

            # Log comprehensive analysis results
            app_insights.track_custom_event(
                "integrated_analysis_completed",
                properties={
                    "subscription_id": subscription_id,
                    "correlation_id": correlation_id,
                    "security_score": response.security_score,
                    "risk_score": response.risk_score,
                    "cost_savings_potential": response.cost_savings_potential,
                    "alerts_count": len(response.alerts),
                    "recommendations_count": len(response.recommendations),
                },
                measurements={
                    # This would be actual duration
                    "analysis_duration": span.get_span_context().span_id,
                    "events_analyzed": response.audit_events_count,
                    "changes_analyzed": response.recent_changes_count,
                },
            )

            logger.info(
                "Integrated analysis completed successfully",
                extra={
                    "event": "integrated_analysis_completed",
                    "subscription_id": subscription_id,
                    "correlation_id": correlation_id,
                    "security_score": response.security_score,
                    "risk_score": response.risk_score,
                    "alerts_count": len(response.alerts),
                },
            )

            return response

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            response.success = False
            response.alerts = [
                {
                    "type": "system",
                    "severity": "critical",
                    "title": "Analysis Failed",
                    "description": f"Integrated analysis failed: {e!s}",
                    "action": "Retry analysis or contact support",
                }
            ]

            logger.error(
                "Integrated analysis failed",
                extra={
                    "event": "integrated_analysis_failed",
                    "subscription_id": subscription_id,
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            return response


def register_integrated_analytics_tool(mcp_instance: Any) -> None:
    """Register integrated analytics tool with MCP server."""

    @mcp_instance.tool(  # type: ignore[misc]
        name="integrated_analytics",
        description=(
            "Comprehensive Azure analytics combining security, cost, change, and audit analysis"
        ),
    )
    async def integrated_analytics(
        subscription_id: str,
        correlation_id: str = "auto",
        include_security: bool = True,
        include_cost: bool = True,
        include_changes: bool = True,
        include_audit: bool = True,
        time_range: str = "24h",
        security_severity_filter: str = "all",
    ) -> dict[str, Any]:
        """Run integrated analytics analysis across all Azure services."""

        import uuid
        from typing import cast

        if correlation_id == "auto":
            correlation_id = str(uuid.uuid4())

        # Build analysis requests based on parameters
        security_request = None
        if include_security:
            from typing import Literal, cast

            severity_filter = cast(
                Literal["critical", "high", "medium", "low", "all"], security_severity_filter
            )
            security_request = SecurityAnalysisRequest.model_validate(
                {"subscription_id": subscription_id, "severity_filter": severity_filter}
            )

        change_request = None
        if include_changes:
            time_range_literal = cast(Literal["1h", "6h", "12h", "24h", "7d", "30d"], time_range)
            change_request = ChangeAnalysisRequest.model_validate(
                {"subscription_id": subscription_id, "time_range": time_range_literal}
            )

        audit_request = None
        if include_audit:
            audit_request = AuditAnalysisRequest.model_validate(
                {"subscription_id": subscription_id}
            )

        result = await run_integrated_analysis(
            subscription_id=subscription_id,
            correlation_id=correlation_id,
            security_request=security_request,
            change_request=change_request,
            audit_request=audit_request,
            include_cost_analysis=include_cost,
        )

        return result.dict()
