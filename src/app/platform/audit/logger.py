from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from app.core.database import get_db
from app.core.logging import get_logger

logger = get_logger(__name__)


class AuditEventType(Enum):
    RESOURCE_CREATED = "resource_created"
    RESOURCE_UPDATED = "resource_updated"
    RESOURCE_DELETED = "resource_deleted"
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    CONFIGURATION_CHANGED = "configuration_changed"
    DEPLOYMENT_STARTED = "deployment_started"
    DEPLOYMENT_COMPLETED = "deployment_completed"
    DEPLOYMENT_FAILED = "deployment_failed"
    ROLLBACK_INITIATED = "rollback_initiated"
    COST_THRESHOLD_EXCEEDED = "cost_threshold_exceeded"
    COMPLIANCE_VIOLATION = "compliance_violation"
    SECURITY_ALERT = "security_alert"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"


class AuditSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_type: AuditEventType = AuditEventType.RESOURCE_CREATED
    severity: AuditSeverity = AuditSeverity.INFO
    user_id: str | None = None
    user_email: str | None = None
    service_principal_id: str | None = None
    subscription_id: str | None = None
    resource_group: str | None = None
    resource_type: str | None = None
    resource_name: str | None = None
    resource_id: str | None = None
    action: str | None = None
    result: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    correlation_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    compliance_frameworks: list[str] = field(default_factory=list)
    hash: str | None = None

    def __post_init__(self) -> None:
        if not self.hash:
            self.hash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        data = {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "user_id": self.user_id,
            "resource_id": self.resource_id,
            "action": self.action,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@dataclass
class AuditQuery:
    start_time: datetime | None = None
    end_time: datetime | None = None
    event_types: list[AuditEventType] | None = None
    severities: list[AuditSeverity] | None = None
    user_ids: list[str] | None = None
    resource_groups: list[str] | None = None
    resource_types: list[str] | None = None
    subscription_ids: list[str] | None = None
    correlation_ids: list[str] | None = None
    limit: int = 1000
    offset: int = 0


class AuditLogger:
    def __init__(self, dsn: str | None = None) -> None:
        self.db = get_db()
        self.dsn = dsn or os.getenv(
            "AUDIT_DB_URL") or os.getenv("DATABASE_URL")
        self._ready = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            await self.db.initialize()
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    user_id TEXT,
                    user_email TEXT,
                    service_principal_id TEXT,
                    subscription_id TEXT,
                    resource_group TEXT,
                    resource_type TEXT,
                    resource_name TEXT,
                    resource_id TEXT,
                    action TEXT,
                    result TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    correlation_id TEXT,
                    details JSONB,
                    tags JSONB,
                    compliance_frameworks JSONB,
                    hash TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_event_type ON audit_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_user_id ON audit_events(user_id);
                CREATE INDEX IF NOT EXISTS idx_resource_id ON audit_events(resource_id);
                CREATE INDEX IF NOT EXISTS idx_correlation_id ON audit_events(correlation_id);
                CREATE INDEX IF NOT EXISTS idx_hash ON audit_events(hash);
                """
            )
            self._ready = True

    async def close(self) -> None:
        return None

    async def log_event(self, event: AuditEvent) -> bool:
        
        try:
            await self.db.execute(
                """
                INSERT INTO audit_events (
                    id, timestamp, event_type, severity, user_id, user_email,
                    service_principal_id, subscription_id, resource_group,
                    resource_type, resource_name, resource_id, action, result,
                    ip_address, user_agent, correlation_id, details, tags,
                    compliance_frameworks, hash
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21
                ) ON CONFLICT (id) DO NOTHING
                """,
                event.id,
                event.timestamp,
                event.event_type.value,
                event.severity.value,
                event.user_id,
                event.user_email,
                event.service_principal_id,
                event.subscription_id,
                event.resource_group,
                event.resource_type,
                event.resource_name,
                event.resource_id,
                event.action,
                event.result,
                event.ip_address,
                event.user_agent,
                event.correlation_id,
                json.dumps(event.details, ensure_ascii=False),
                json.dumps(event.tags, ensure_ascii=False),
                json.dumps(event.compliance_frameworks, ensure_ascii=False),
                event.hash,
            )
            if event.severity in {AuditSeverity.ERROR, AuditSeverity.CRITICAL}:
                await self._trigger_alert(event)
            return True
        except Exception:
            logger.error(
                "audit_event_log_failed",
                exc_info=True,
                event_type=event.event_type.value,
                severity=event.severity.value,
                correlation_id=event.correlation_id,
                resource_id=event.resource_id,
                action=event.action,
            )
            return False

    def _build_query(self, query: AuditQuery) -> tuple[str, list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if query.start_time:
            conditions.append("timestamp >= $1")
            params.append(query.start_time)
        if query.end_time:
            conditions.append("timestamp <= $" + str(len(params) + 1))
            params.append(query.end_time)
        if query.event_types:
            placeholders = ",".join(
                f"${len(params) + i + 1}" for i in range(len(query.event_types)))
            conditions.append(f"event_type IN ({placeholders})")
            params.extend([et.value for et in query.event_types])
        if query.severities:
            placeholders = ",".join(
                f"${len(params) + i + 1}" for i in range(len(query.severities)))
            conditions.append(f"severity IN ({placeholders})")
            params.extend([s.value for s in query.severities])
        if query.user_ids:
            placeholders = ",".join(
                f"${len(params) + i + 1}" for i in range(len(query.user_ids)))
            conditions.append(f"user_id IN ({placeholders})")
            params.extend(query.user_ids)
        if query.resource_groups:
            placeholders = ",".join(
                f"${len(params) + i + 1}" for i in range(len(query.resource_groups)))
            conditions.append(f"resource_group IN ({placeholders})")
            params.extend(query.resource_groups)
        if query.resource_types:
            placeholders = ",".join(
                f"${len(params) + i + 1}" for i in range(len(query.resource_types)))
            conditions.append(f"resource_type IN ({placeholders})")
            params.extend(query.resource_types)
        if query.subscription_ids:
            placeholders = ",".join(
                f"${len(params) + i + 1}" for i in range(len(query.subscription_ids)))
            conditions.append(f"subscription_id IN ({placeholders})")
            params.extend(query.subscription_ids)
        if query.correlation_ids:
            placeholders = ",".join(
                f"${len(params) + i + 1}" for i in range(len(query.correlation_ids)))
            conditions.append(f"correlation_id IN ({placeholders})")
            params.extend(query.correlation_ids)
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(int(query.limit))
        params.append(int(query.offset))
        sql = f"SELECT * FROM audit_events WHERE {where_clause} ORDER BY timestamp DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}"
        return sql, params

    async def query_events(self, query: AuditQuery) -> list[AuditEvent]:
        
        sql, params = self._build_query(query)
        rows = await self.db.fetch(sql, *params)
        events: list[AuditEvent] = []
        for r in rows:
            events.append(
                AuditEvent(
                    id=r["id"],
                    timestamp=r["timestamp"],
                    event_type=AuditEventType(r["event_type"]),
                    severity=AuditSeverity(r["severity"]),
                    user_id=r["user_id"],
                    user_email=r["user_email"],
                    service_principal_id=r["service_principal_id"],
                    subscription_id=r["subscription_id"],
                    resource_group=r["resource_group"],
                    resource_type=r["resource_type"],
                    resource_name=r["resource_name"],
                    resource_id=r["resource_id"],
                    action=r["action"],
                    result=r["result"],
                    ip_address=r["ip_address"],
                    user_agent=r["user_agent"],
                    correlation_id=r["correlation_id"],
                    details=r["details"] or {},
                    tags=r["tags"] or {},
                    compliance_frameworks=r["compliance_frameworks"] or [],
                    hash=r["hash"],
                )
            )
        return events

    async def get_statistics(self, start_time: datetime, end_time: datetime) -> dict[str, Any]:
        
        total = await self.db.fetchrow(
            """
            SELECT 
                COUNT(*) AS total,
                COUNT(DISTINCT user_id) AS users,
                COUNT(DISTINCT resource_id) AS resources,
                COUNT(DISTINCT correlation_id) AS ops
            FROM audit_events
            WHERE timestamp BETWEEN $1 AND $2
            """,
            start_time,
            end_time,
        )
        types = await self.db.fetch(
            """
            SELECT event_type, COUNT(*) AS c
            FROM audit_events
            WHERE timestamp BETWEEN $1 AND $2
            GROUP BY event_type
            """,
            start_time,
            end_time,
        )
        severities = await self.db.fetch(
            """
            SELECT severity, COUNT(*) AS c
            FROM audit_events
            WHERE timestamp BETWEEN $1 AND $2
            GROUP BY severity
            """,
            start_time,
            end_time,
        )
        return {
            "total_events": int(total["total"] if total else 0),
            "unique_users": int(total["users"] if total else 0),
            "unique_resources": int(total["resources"] if total else 0),
            "unique_operations": int(total["ops"] if total else 0),
            "event_type_distribution": {r["event_type"]: r["c"] for r in types},
            "severity_distribution": {r["severity"]: r["c"] for r in severities},
        }

    async def verify_integrity(self, event_id: str) -> bool:
        
        row = await self.db.fetchrow(
            "SELECT id, timestamp, event_type, severity, user_id, resource_id, action, hash FROM audit_events WHERE id = $1",
            event_id,
        )
        if not row:
            return False
        event = AuditEvent(
            id=row["id"],
            timestamp=row["timestamp"],
            event_type=AuditEventType(row["event_type"]),
            severity=AuditSeverity(row["severity"]),
            user_id=row["user_id"],
            resource_id=row["resource_id"],
            action=row["action"],
        )
        return event._calculate_hash() == row["hash"]

    async def export_for_compliance(self, framework: str, start_time: datetime, end_time: datetime) -> dict[str, Any]:
        query = AuditQuery(start_time=start_time, end_time=end_time)
        events = await self.query_events(query)
        filtered = [e for e in events if framework in e.compliance_frameworks]
        if framework == "gdpr":
            return self._format_gdpr_report(filtered)
        if framework == "hipaa":
            return self._format_hipaa_report(filtered)
        if framework == "pci-dss":
            return self._format_pci_report(filtered)
        if framework == "sox":
            return self._format_sox_report(filtered)
        return self._format_generic_report(filtered)

    def _format_gdpr_report(self, events: list[AuditEvent]) -> dict[str, Any]:
        return {
            "framework": "gdpr",
            "data_access_events": [asdict(e) for e in events if e.event_type in [AuditEventType.ACCESS_GRANTED, AuditEventType.ACCESS_DENIED]],
            "data_modification_events": [asdict(e) for e in events if e.event_type in [AuditEventType.RESOURCE_UPDATED, AuditEventType.RESOURCE_DELETED]],
            "consent_events": [],
            "data_breach_events": [asdict(e) for e in events if e.severity == AuditSeverity.CRITICAL],
        }

    def _format_hipaa_report(self, events: list[AuditEvent]) -> dict[str, Any]:
        phi = [asdict(e)
               for e in events if "phi" in e.tags or "healthcare" in e.tags]
        sec = [asdict(e) for e in events if e.event_type ==
               AuditEventType.SECURITY_ALERT]
        aud = [asdict(e) for e in events]
        return {"framework": "hipaa", "phi_access_events": phi, "security_events": sec, "audit_control_events": aud}

    def _format_pci_report(self, events: list[AuditEvent]) -> dict[str, Any]:
        card = [asdict(e)
                for e in events if "payment" in e.tags or "card" in e.tags]
        net = [asdict(e) for e in events if "network" in (
            e.resource_type or "") or "firewall" in (e.resource_type or "")]
        acc = [asdict(e) for e in events if e.event_type in [
            AuditEventType.ACCESS_GRANTED, AuditEventType.ACCESS_DENIED]]
        return {"framework": "pci-dss", "cardholder_data_events": card, "network_security_events": net, "access_control_events": acc}

    def _format_sox_report(self, events: list[AuditEvent]) -> dict[str, Any]:
        fin = [
            asdict(e) for e in events if "financial" in e.tags or "accounting" in e.tags]
        chg = [asdict(e) for e in events if e.event_type ==
               AuditEventType.CONFIGURATION_CHANGED]
        acc = [asdict(e) for e in events if e.event_type in [
            AuditEventType.ACCESS_GRANTED, AuditEventType.ACCESS_DENIED]]
        return {"framework": "sox", "financial_system_events": fin, "change_management_events": chg, "access_control_events": acc}

    async def cleanup_old_events(self) -> None:
        
        cutoff = datetime.utcnow() - timedelta(days=2555)
        await self.db.execute(
            """
            UPDATE audit_events 
            SET details = COALESCE(details,'{}'::jsonb) || '{"archived": true}'::jsonb,
                tags = COALESCE(tags,'{}'::jsonb) || '{"archived": true}'::jsonb
            WHERE timestamp < $1
            """,
            cutoff,
        )

    async def _trigger_alert(self, event: AuditEvent) -> None:
        return None
