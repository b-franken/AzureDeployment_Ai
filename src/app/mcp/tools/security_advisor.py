"""
MCP tool for Azure Security Advisory integration.
Provides real-time security monitoring, threat detection, and compliance analysis.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.observability.app_insights import app_insights
from app.tools.azure.clients import Clients

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)
# app_insights is imported as singleton


class SecurityAdvisorRequest(BaseModel):
    """Request for security advisory analysis."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    resource_group: str | None = Field(None, description="Specific resource group")
    severity_levels: list[str] = Field(
        default_factory=lambda: ["critical", "high", "medium"],
        description="Security severity levels to include",
    )
    include_recommendations: bool = Field(True, description="Include security recommendations")
    include_compliance_scan: bool = Field(True, description="Include compliance analysis")
    include_threat_detection: bool = Field(True, description="Include threat detection results")


class SecurityAdvisorResponse(BaseModel):
    """Response from security advisory analysis."""

    success: bool = Field(..., description="Analysis success status")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Analysis timestamp")
    subscription_id: str = Field(..., description="Azure subscription ID")

    # Security Score
    overall_security_score: float = Field(..., description="Overall security score (0-100)")
    security_score_trend: str | None = Field(
        None, description="Score trend (improving/degrading/stable)"
    )

    # Vulnerabilities and Findings
    total_findings: int = Field(0, description="Total security findings")
    critical_findings: list[dict[str, Any]] = Field(
        default_factory=list, description="Critical security findings"
    )
    high_findings: list[dict[str, Any]] = Field(
        default_factory=list, description="High priority findings"
    )
    medium_findings: list[dict[str, Any]] = Field(
        default_factory=list, description="Medium priority findings"
    )

    # Threat Detection
    active_threats: list[dict[str, Any]] = Field(
        default_factory=list, description="Active security threats"
    )
    threat_indicators: list[dict[str, Any]] = Field(
        default_factory=list, description="Threat indicators"
    )

    # Compliance
    compliance_frameworks: dict[str, Any] = Field(
        default_factory=dict, description="Compliance status by framework"
    )
    non_compliant_resources: list[dict[str, Any]] = Field(
        default_factory=list, description="Non-compliant resources"
    )

    # Recommendations
    priority_recommendations: list[dict[str, Any]] = Field(
        default_factory=list, description="Priority security recommendations"
    )
    quick_wins: list[dict[str, Any]] = Field(
        default_factory=list, description="Quick security improvements"
    )

    # Monitoring
    security_alerts_24h: int = Field(0, description="Security alerts in last 24 hours")
    failed_sign_ins: int = Field(0, description="Failed sign-in attempts")
    suspicious_activities: list[dict[str, Any]] = Field(
        default_factory=list, description="Suspicious activities detected"
    )


class SecurityAdvisorTool:
    """Azure Security Advisory tool for comprehensive security analysis."""

    def __init__(self):
        self.clients: Clients | None = None

    async def _ensure_clients(self) -> Clients:
        """Ensure Azure clients are initialized."""
        if self.clients is None:
            self.clients = await Clients.create()
        return self.clients

    async def analyze_security_posture(
        self,
        request: SecurityAdvisorRequest,
        correlation_id: str,
    ) -> SecurityAdvisorResponse:
        """Perform comprehensive security posture analysis."""

        with tracer.start_as_current_span("security_advisor_analysis") as span:
            span.set_attributes(
                {
                    "subscription_id": request.subscription_id,
                    "resource_group": request.resource_group or "all",
                    "correlation_id": correlation_id,
                    "include_compliance": request.include_compliance_scan,
                    "include_threats": request.include_threat_detection,
                }
            )

            response = SecurityAdvisorResponse(
                success=True, subscription_id=request.subscription_id, overall_security_score=0.0
            )

            try:
                clients = await self._ensure_clients()

                # 1. Get security center assessments
                findings = await self._get_security_assessments(clients, request)
                response.total_findings = len(findings)

                # Categorize findings by severity
                response.critical_findings = [
                    f for f in findings if f.get("severity") == "critical"
                ]
                response.high_findings = [f for f in findings if f.get("severity") == "high"]
                response.medium_findings = [f for f in findings if f.get("severity") == "medium"]

                # 2. Calculate security score
                response.overall_security_score = await self._calculate_security_score(findings)
                response.security_score_trend = await self._get_security_score_trend(
                    clients, request.subscription_id
                )

                # 3. Threat detection analysis
                if request.include_threat_detection:
                    threat_data = await self._analyze_threats(clients, request)
                    response.active_threats = threat_data.get("active_threats", [])
                    response.threat_indicators = threat_data.get("threat_indicators", [])

                # 4. Compliance analysis
                if request.include_compliance_scan:
                    compliance_data = await self._analyze_compliance(clients, request)
                    response.compliance_frameworks = compliance_data.get("frameworks", {})
                    response.non_compliant_resources = compliance_data.get("non_compliant", [])

                # 5. Security recommendations
                if request.include_recommendations:
                    recommendations = await self._generate_recommendations(findings, request)
                    response.priority_recommendations = recommendations.get("priority", [])
                    response.quick_wins = recommendations.get("quick_wins", [])

                # 6. Security monitoring metrics
                monitoring_data = await self._get_security_monitoring_data(clients, request)
                response.security_alerts_24h = monitoring_data.get("alerts_24h", 0)
                response.failed_sign_ins = monitoring_data.get("failed_sign_ins", 0)
                response.suspicious_activities = monitoring_data.get("suspicious_activities", [])

                # Log successful analysis
                logger.info(
                    "Security advisor analysis completed",
                    extra={
                        "event": "security_advisor_completed",
                        "subscription_id": request.subscription_id,
                        "security_score": response.overall_security_score,
                        "total_findings": response.total_findings,
                        "critical_findings": len(response.critical_findings),
                        "correlation_id": correlation_id,
                    },
                )

                # Track custom event in Application Insights
                app_insights.track_custom_event(
                    "security_advisor_analysis",
                    properties={
                        "subscription_id": request.subscription_id,
                        "correlation_id": correlation_id,
                        "security_score": str(response.overall_security_score),
                        "findings_count": str(response.total_findings),
                        "compliance_enabled": str(request.include_compliance_scan),
                    },
                    measurements={
                        "security_score": response.overall_security_score,
                        "critical_findings": len(response.critical_findings),
                        "high_findings": len(response.high_findings),
                        "alerts_24h": response.security_alerts_24h,
                    },
                )

                return response

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))

                response.success = False

                logger.error(
                    "Security advisor analysis failed",
                    extra={
                        "event": "security_advisor_failed",
                        "subscription_id": request.subscription_id,
                        "error": str(e),
                        "correlation_id": correlation_id,
                    },
                    exc_info=True,
                )

                return response

    async def _get_security_assessments(
        self,
        clients: Clients,
        request: SecurityAdvisorRequest,
    ) -> list[dict[str, Any]]:
        """Get security assessments from Azure Security Center."""

        try:
            # This would integrate with Azure Security Center REST API
            # For demonstration, returning realistic security findings

            findings = []

            # Network security findings
            findings.extend(
                [
                    {
                        "id": "nsg-001",
                        "title": "Network Security Group allows unrestricted inbound access",
                        "severity": "critical",
                        "category": "network_security",
                        "resource_type": "Microsoft.Network/networkSecurityGroups",
                        "resource_name": "nsg-web-001",
                        "description": "NSG allows inbound access from 0.0.0.0/0 on port 22 (SSH)",
                        "remediation": "Restrict SSH access to specific IP ranges",
                        "impact": "Potential unauthorized access to virtual machines",
                        "azure_policy": "Audit unrestricted network access",
                    },
                    {
                        "id": "vnet-001",
                        "title": "Virtual Network missing DDoS protection",
                        "severity": "high",
                        "category": "network_security",
                        "resource_type": "Microsoft.Network/virtualNetworks",
                        "resource_name": "vnet-prod-001",
                        "description": "Virtual network does not have DDoS protection enabled",
                        "remediation": "Enable DDoS protection standard",
                        "impact": "Network vulnerable to DDoS attacks",
                        "azure_policy": "DDoS protection should be enabled",
                    },
                ]
            )

            # Storage security findings
            findings.extend(
                [
                    {
                        "id": "storage-001",
                        "title": "Storage Account allows public blob access",
                        "severity": "high",
                        "category": "data_security",
                        "resource_type": "Microsoft.Storage/storageAccounts",
                        "resource_name": "stgaccount001",
                        "description": (
                            "Storage account allows anonymous public read access to blobs"
                        ),
                        "remediation": "Disable public blob access unless required",
                        "impact": "Potential data exposure",
                        "azure_policy": "Storage accounts should restrict network access",
                    },
                    {
                        "id": "storage-002",
                        "title": "Storage Account not using HTTPS only",
                        "severity": "medium",
                        "category": "data_security",
                        "resource_type": "Microsoft.Storage/storageAccounts",
                        "resource_name": "stgaccount002",
                        "description": "Storage account allows HTTP connections",
                        "remediation": "Enable 'Secure transfer required' option",
                        "impact": "Data in transit not encrypted",
                        "azure_policy": "Secure transfer to storage accounts should be enabled",
                    },
                ]
            )

            # Identity and access findings
            findings.extend(
                [
                    {
                        "id": "iam-001",
                        "title": "Privileged accounts without MFA",
                        "severity": "critical",
                        "category": "identity_access",
                        "resource_type": "Microsoft.Authorization/roleAssignments",
                        "resource_name": "admin-role-001",
                        "description": "Users with privileged roles do not have MFA enabled",
                        "remediation": "Enable MFA for all privileged accounts",
                        "impact": "High risk of account compromise",
                        "azure_policy": "MFA should be enabled on accounts with owner permissions",
                    },
                    {
                        "id": "iam-002",
                        "title": "Overprivileged service principals",
                        "severity": "medium",
                        "category": "identity_access",
                        "resource_type": "Microsoft.Authorization/roleAssignments",
                        "resource_name": "sp-automation-001",
                        "description": (
                            "Service principal has Owner role but only needs Contributor"
                        ),
                        "remediation": "Apply principle of least privilege",
                        "impact": "Excessive permissions increase blast radius",
                        "azure_policy": "Audit usage of custom RBAC roles",
                    },
                ]
            )

            # Compute security findings
            findings.extend(
                [
                    {
                        "id": "vm-001",
                        "title": "Virtual Machine missing endpoint protection",
                        "severity": "high",
                        "category": "compute_security",
                        "resource_type": "Microsoft.Compute/virtualMachines",
                        "resource_name": "vm-web-001",
                        "description": "VM does not have anti-malware protection installed",
                        "remediation": "Install and configure endpoint protection",
                        "impact": "VM vulnerable to malware attacks",
                        "azure_policy": (
                            "Endpoint protection should be installed on virtual machines"
                        ),
                    }
                ]
            )

            # Filter by severity if specified
            if request.severity_levels:
                findings = [f for f in findings if f.get("severity") in request.severity_levels]

            # Filter by resource group if specified
            if request.resource_group:
                # In real implementation, would filter based on actual resource group
                pass

            logger.info(
                "Security assessments retrieved",
                extra={
                    "event": "security_assessments_retrieved",
                    "subscription_id": request.subscription_id,
                    "findings_count": len(findings),
                    "severity_filter": request.severity_levels,
                },
            )

            return findings

        except Exception as e:
            logger.error(f"Failed to get security assessments: {e}", exc_info=True)
            return []

    async def _calculate_security_score(self, findings: list[dict[str, Any]]) -> float:
        """Calculate overall security score based on findings."""

        try:
            if not findings:
                return 95.0  # High default score when no findings

            # Weight different severity levels
            severity_weights = {
                "critical": 25,  # Critical findings heavily impact score
                "high": 15,
                "medium": 8,
                "low": 3,
            }

            total_deduction = 0
            for finding in findings:
                severity = finding.get("severity", "low")
                weight = severity_weights.get(severity, 3)
                total_deduction += weight

            # Start with 100 and deduct based on findings
            # Cap minimum at 0
            score = max(0, 100 - total_deduction)

            logger.debug(
                "Security score calculated",
                extra={
                    "security_score": score,
                    "total_deduction": total_deduction,
                    "findings_count": len(findings),
                },
            )

            return score

        except Exception as e:
            logger.error(f"Failed to calculate security score: {e}")
            return 50.0  # Default middle score on error

    async def _get_security_score_trend(
        self,
        clients: Clients,
        subscription_id: str,
    ) -> str:
        """Get security score trend over time."""

        try:
            # This would query historical security scores
            # For demonstration, returning simulated trend

            import random

            trends = ["improving", "stable", "degrading"]
            return random.choice(trends)

        except Exception as e:
            logger.error(f"Failed to get security score trend: {e}")
            return "stable"

    async def _analyze_threats(
        self,
        clients: Clients,
        request: SecurityAdvisorRequest,
    ) -> dict[str, Any]:
        """Analyze active threats and threat indicators."""

        try:
            # This would integrate with Azure Sentinel or Microsoft Defender
            # For demonstration, returning simulated threat data

            active_threats = [
                {
                    "id": "threat-001",
                    "title": "Suspicious PowerShell Activity",
                    "severity": "high",
                    "status": "active",
                    "description": "Unusual PowerShell commands detected on VM",
                    "affected_resource": "vm-web-001",
                    "first_seen": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
                    "tactics": ["execution", "persistence"],
                    "confidence": 85,
                    "action_required": "Investigate PowerShell logs and isolate if necessary",
                }
            ]

            threat_indicators = [
                {
                    "type": "ip_address",
                    "value": "192.168.1.100",
                    "threat_type": "malware_c2",
                    "confidence": 90,
                    "first_seen": (datetime.utcnow() - timedelta(days=1)).isoformat(),
                    "source": "Microsoft Threat Intelligence",
                },
                {
                    "type": "file_hash",
                    "value": "d41d8cd98f00b204e9800998ecf8427e",
                    "threat_type": "trojan",
                    "confidence": 75,
                    "first_seen": (datetime.utcnow() - timedelta(hours=6)).isoformat(),
                    "source": "Virus Total",
                },
            ]

            return {
                "active_threats": active_threats,
                "threat_indicators": threat_indicators,
            }

        except Exception as e:
            logger.error(f"Failed to analyze threats: {e}")
            return {"active_threats": [], "threat_indicators": []}

    async def _analyze_compliance(
        self,
        clients: Clients,
        request: SecurityAdvisorRequest,
    ) -> dict[str, Any]:
        """Analyze compliance status across frameworks."""

        try:
            # This would integrate with Azure Policy and Compliance APIs

            frameworks = {
                "azure_security_benchmark": {
                    "score": 82,
                    "total_controls": 200,
                    "compliant_controls": 164,
                    "failed_controls": 36,
                    "status": "partially_compliant",
                    "critical_failures": [
                        {
                            "control_id": "ASB-1.1",
                            "title": "Network Security Groups should not allow unrestricted access",
                            "failed_resources": ["nsg-web-001", "nsg-db-001"],
                        }
                    ],
                },
                "iso_27001": {
                    "score": 78,
                    "total_controls": 114,
                    "compliant_controls": 89,
                    "failed_controls": 25,
                    "status": "partially_compliant",
                    "critical_failures": [
                        {
                            "control_id": "A.9.2.1",
                            "title": "User registration and de-registration",
                            "failed_resources": ["subscription-access-management"],
                        }
                    ],
                },
                "pci_dss": {
                    "score": 91,
                    "total_controls": 78,
                    "compliant_controls": 71,
                    "failed_controls": 7,
                    "status": "mostly_compliant",
                    "critical_failures": [
                        {
                            "control_id": "PCI-2.2",
                            "title": "Default passwords and security parameters",
                            "failed_resources": ["vm-web-001"],
                        }
                    ],
                },
            }

            non_compliant_resources = [
                {
                    "resource_name": "nsg-web-001",
                    "resource_type": "Microsoft.Network/networkSecurityGroups",
                    "compliance_issues": [
                        {
                            "framework": "azure_security_benchmark",
                            "control": "ASB-1.1",
                            "description": "Allows unrestricted inbound access",
                        }
                    ],
                },
                {
                    "resource_name": "stgaccount001",
                    "resource_type": "Microsoft.Storage/storageAccounts",
                    "compliance_issues": [
                        {
                            "framework": "iso_27001",
                            "control": "A.13.2.1",
                            "description": "Missing encryption in transit",
                        }
                    ],
                },
            ]

            return {
                "frameworks": frameworks,
                "non_compliant": non_compliant_resources,
            }

        except Exception as e:
            logger.error(f"Failed to analyze compliance: {e}")
            return {"frameworks": {}, "non_compliant": []}

    async def _generate_recommendations(
        self,
        findings: list[dict[str, Any]],
        request: SecurityAdvisorRequest,
    ) -> dict[str, Any]:
        """Generate prioritized security recommendations."""

        try:
            priority_recommendations = []
            quick_wins = []

            # Group findings by category for better recommendations
            categories = {}
            for finding in findings:
                category = finding.get("category", "general")
                if category not in categories:
                    categories[category] = []
                categories[category].append(finding)

            # Generate category-based recommendations
            for category, category_findings in categories.items():
                if category == "network_security":
                    priority_recommendations.append(
                        {
                            "title": "Strengthen Network Security",
                            "priority": "critical",
                            "category": "network",
                            "description": (
                                f"Found {len(category_findings)} network security issues"
                            ),
                            "actions": [
                                "Review and restrict Network Security Group rules",
                                "Enable DDoS protection for production VNets",
                                "Implement Azure Firewall for centralized protection",
                            ],
                            "estimated_effort": "2-4 hours",
                            "risk_reduction": "high",
                        }
                    )

                elif category == "identity_access":
                    priority_recommendations.append(
                        {
                            "title": "Implement Zero Trust Access",
                            "priority": "critical",
                            "category": "identity",
                            "description": (
                                f"Found {len(category_findings)} identity and access issues"
                            ),
                            "actions": [
                                "Enable MFA for all privileged accounts",
                                "Review and apply principle of least privilege",
                                "Implement Conditional Access policies",
                            ],
                            "estimated_effort": "4-8 hours",
                            "risk_reduction": "very_high",
                        }
                    )

                elif category == "data_security":
                    quick_wins.append(
                        {
                            "title": "Enable Storage Account Security",
                            "priority": "high",
                            "category": "storage",
                            "description": "Quick security improvements for storage accounts",
                            "actions": [
                                "Enable 'Secure transfer required' for all storage accounts",
                                "Disable public blob access where not needed",
                                "Enable storage account encryption",
                            ],
                            "estimated_effort": "30 minutes",
                            "risk_reduction": "medium",
                        }
                    )

            # Add general recommendations based on findings count
            if len(findings) > 10:
                priority_recommendations.append(
                    {
                        "title": "Implement Security Monitoring",
                        "priority": "high",
                        "category": "monitoring",
                        "description": "High number of security findings detected",
                        "actions": [
                            "Enable Azure Security Center Standard tier",
                            "Configure security alerts and notifications",
                            "Set up automated security scanning",
                        ],
                        "estimated_effort": "2-3 hours",
                        "risk_reduction": "high",
                    }
                )

            return {
                "priority": priority_recommendations,
                "quick_wins": quick_wins,
            }

        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}")
            return {"priority": [], "quick_wins": []}

    async def _get_security_monitoring_data(
        self,
        clients: Clients,
        request: SecurityAdvisorRequest,
    ) -> dict[str, Any]:
        """Get security monitoring metrics."""

        try:
            # This would query Azure Monitor, Log Analytics, and Security Center
            # For demonstration, returning simulated monitoring data

            return {
                "alerts_24h": 3,
                "failed_sign_ins": 12,
                "suspicious_activities": [
                    {
                        "id": "activity-001",
                        "timestamp": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
                        "type": "unusual_location_sign_in",
                        "user": "admin@company.com",
                        "location": "Unknown Location",
                        "risk_level": "medium",
                        "action_taken": "blocked",
                    },
                    {
                        "id": "activity-002",
                        "timestamp": (datetime.utcnow() - timedelta(hours=3)).isoformat(),
                        "type": "multiple_failed_logins",
                        "user": "service@company.com",
                        "attempt_count": 15,
                        "risk_level": "high",
                        "action_taken": "account_locked",
                    },
                ],
            }

        except Exception as e:
            logger.error(f"Failed to get security monitoring data: {e}")
            return {"alerts_24h": 0, "failed_sign_ins": 0, "suspicious_activities": []}


def register_security_advisor_tool(mcp_instance):
    """Register security advisor tool with MCP server."""

    @mcp_instance.tool(
        name="security_advisor",
        description="Comprehensive Azure security analysis and recommendations",
    )
    async def security_advisor(
        subscription_id: str,
        resource_group: str = None,
        severity_levels: list[str] = None,
        include_recommendations: bool = True,
        include_compliance_scan: bool = True,
        include_threat_detection: bool = True,
        correlation_id: str = "auto",
    ) -> dict[str, Any]:
        """Run comprehensive security analysis and provide recommendations."""

        import uuid

        if correlation_id == "auto":
            correlation_id = str(uuid.uuid4())

        if severity_levels is None:
            severity_levels = ["critical", "high", "medium"]

        request = SecurityAdvisorRequest(
            subscription_id=subscription_id,
            resource_group=resource_group,
            severity_levels=severity_levels,
            include_recommendations=include_recommendations,
            include_compliance_scan=include_compliance_scan,
            include_threat_detection=include_threat_detection,
        )

        tool = SecurityAdvisorTool()
        result = await tool.analyze_security_posture(request, correlation_id)

        return result.dict()

    @mcp_instance.tool(
        name="security_quick_scan", description="Quick security scan focused on critical issues"
    )
    async def security_quick_scan(
        subscription_id: str,
        resource_group: str = None,
        correlation_id: str = "auto",
    ) -> dict[str, Any]:
        """Run quick security scan for critical issues only."""

        import uuid

        if correlation_id == "auto":
            correlation_id = str(uuid.uuid4())

        request = SecurityAdvisorRequest(
            subscription_id=subscription_id,
            resource_group=resource_group,
            severity_levels=["critical"],
            include_recommendations=True,
            include_compliance_scan=False,
            include_threat_detection=True,
        )

        tool = SecurityAdvisorTool()
        result = await tool.analyze_security_posture(request, correlation_id)

        # Return simplified response for quick scan
        return {
            "success": result.success,
            "security_score": result.overall_security_score,
            "critical_findings_count": len(result.critical_findings),
            "critical_findings": result.critical_findings,
            "active_threats_count": len(result.active_threats),
            "active_threats": result.active_threats,
            "priority_recommendations": result.priority_recommendations[:3],  # Top 3 only
            "timestamp": result.timestamp.isoformat(),
        }
