from __future__ import annotations
import os
import asyncio
import hashlib
import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


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
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()


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
        self.dsn = dsn or os.getenv("AUDIT_DB_URL") or os.getenv(
            "DATABASE_URL") or "postgresql://dev:dev@localhost:5432/devops_ai"
        self._lock = threading.RLock()
        self._pool = ConnectionPool(
            self.dsn, min_size=1, max_size=5, kwargs={"autocommit": True})
        self._retention_days = 2555
        self._compliance_mode = True
        self._init_database()

    def _init_database(self) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )

    async def close(self) -> None:
        self._pool.close()

    async def log_event(self, event: AuditEvent) -> bool:
        try:
            await asyncio.to_thread(self._write_event, event)
            if event.severity in [AuditSeverity.ERROR, AuditSeverity.CRITICAL]:
                await self._trigger_alert(event)
            return True
        except Exception:
            logger.exception("Failed to log audit event")
            return False

    def _write_event(self, event: AuditEvent) -> None:
        with self._lock, self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_events (
                    id, timestamp, event_type, severity, user_id, user_email,
                    service_principal_id, subscription_id, resource_group,
                    resource_type, resource_name, resource_id, action, result,
                    ip_address, user_agent, correlation_id, details, tags,
                    compliance_frameworks, hash
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                ) ON CONFLICT (id) DO NOTHING
                """,
                (
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
                    json.dumps(event.compliance_frameworks,
                               ensure_ascii=False),
                    event.hash,
                ),
            )

    def _build_query(self, query: AuditQuery) -> tuple[str, list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if query.start_time:
            conditions.append("timestamp >= %s")
            params.append(query.start_time)
        if query.end_time:
            conditions.append("timestamp <= %s")
            params.append(query.end_time)
        if query.event_types and len(query.event_types) > 0:
            placeholders = ",".join(["%s"] * len(query.event_types))
            conditions.append(f"event_type IN ({placeholders})")
            params.extend([et.value for et in query.event_types])
        if query.severities and len(query.severities) > 0:
            placeholders = ",".join(["%s"] * len(query.severities))
            conditions.append(f"severity IN ({placeholders})")
            params.extend([s.value for s in query.severities])
        if query.user_ids and len(query.user_ids) > 0:
            placeholders = ",".join(["%s"] * len(query.user_ids))
            conditions.append(f"user_id IN ({placeholders})")
            params.extend(query.user_ids)
        if query.resource_groups and len(query.resource_groups) > 0:
            placeholders = ",".join(["%s"] * len(query.resource_groups))
            conditions.append(f"resource_group IN ({placeholders})")
            params.extend(query.resource_groups)
        if query.resource_types and len(query.resource_types) > 0:
            placeholders = ",".join(["%s"] * len(query.resource_types))
            conditions.append(f"resource_type IN ({placeholders})")
            params.extend(query.resource_types)
        if query.subscription_ids and len(query.subscription_ids) > 0:
            placeholders = ",".join(["%s"] * len(query.subscription_ids))
            conditions.append(f"subscription_id IN ({placeholders})")
            params.extend(query.subscription_ids)
        if query.correlation_ids and len(query.correlation_ids) > 0:
            placeholders = ",".join(["%s"] * len(query.correlation_ids))
            conditions.append(f"correlation_id IN ({placeholders})")
            params.extend(query.correlation_ids)
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM audit_events WHERE {where_clause} ORDER BY timestamp DESC LIMIT %s OFFSET %s"
        params.extend([int(query.limit), int(query.offset)])
        return sql, params

    async def query_events(self, query: AuditQuery) -> list[AuditEvent]:
        with self._lock, self._pool.connection() as conn, conn.cursor() as cur:
            sql, params = self._build_query(query)
            cur.execute(sql, params)
            rows = cur.fetchall()
        events: list[AuditEvent] = []
        for row in rows:
            events.append(
                AuditEvent(
                    id=row[0],
                    timestamp=row[1],
                    event_type=AuditEventType(row[2]),
                    severity=AuditSeverity(row[3]),
                    user_id=row[4],
                    user_email=row[5],
                    service_principal_id=row[6],
                    subscription_id=row[7],
                    resource_group=row[8],
                    resource_type=row[9],
                    resource_name=row[10],
                    resource_id=row[11],
                    action=row[12],
                    result=row[13],
                    ip_address=row[14],
                    user_agent=row[15],
                    correlation_id=row[16],
                    details=json.loads(row[17]) if row[17] else {},
                    tags=json.loads(row[18]) if row[18] else {},
                    compliance_frameworks=json.loads(
                        row[19]) if row[19] else [],
                    hash=row[20],
                )
            )
        return events

    async def get_statistics(self, start_time: datetime, end_time: datetime) -> dict[str, Any]:
        with self._lock, self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    COUNT(*),
                    COUNT(DISTINCT user_id),
                    COUNT(DISTINCT resource_id),
                    COUNT(DISTINCT correlation_id)
                FROM audit_events
                WHERE timestamp BETWEEN %s AND %s
                """,
                (start_time, end_time),
            )
            stats = cur.fetchone()
            cur.execute(
                """
                SELECT event_type, COUNT(*) FROM audit_events
                WHERE timestamp BETWEEN %s AND %s
                GROUP BY event_type
                """,
                (start_time, end_time),
            )
            event_type_counts = {row[0]: row[1] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT severity, COUNT(*) FROM audit_events
                WHERE timestamp BETWEEN %s AND %s
                GROUP BY severity
                """,
                (start_time, end_time),
            )
            severity_counts = {row[0]: row[1] for row in cur.fetchall()}
        return {
            "total_events": stats[0] if stats else 0,
            "unique_users": stats[1] if stats else 0,
            "unique_resources": stats[2] if stats else 0,
            "unique_operations": stats[3] if stats else 0,
            "event_type_distribution": event_type_counts,
            "severity_distribution": severity_counts,
        }

    async def verify_integrity(self, event_id: str) -> bool:
        with self._lock, self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, timestamp, event_type, severity, user_id, resource_id, action, hash FROM audit_events WHERE id = %s", (event_id,))
            row = cur.fetchone()
        if not row:
            return False
        event = AuditEvent(
            id=row[0],
            timestamp=row[1],
            event_type=AuditEventType(row[2]),
            severity=AuditSeverity(row[3]),
            user_id=row[4],
            resource_id=row[5],
            action=row[6],
        )
        calculated_hash = event._calculate_hash()
        stored_hash = row[7]
        return calculated_hash == stored_hash

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
        phi_access_events = [
            asdict(e) for e in events if "phi" in e.tags or "healthcare" in e.tags]
        security_events = [
            asdict(e) for e in events if e.event_type == AuditEventType.SECURITY_ALERT]
        audit_control_events = [asdict(e) for e in events]
        return {"framework": "hipaa", "phi_access_events": phi_access_events, "security_events": security_events, "audit_control_events": audit_control_events}

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
        cutoff = datetime.utcnow() - timedelta(days=self._retention_days)
        with self._lock, self._pool.connection() as conn, conn.cursor() as cur:
            if self._compliance_mode:
                cur.execute(
                    """
                    UPDATE audit_events 
                    SET details = '{"archived": true}', tags = '{"archived": true}'
                    WHERE timestamp < %s
                    """,
                    (cutoff,),
                )
            else:
                cur.execute(
                    "DELETE FROM audit_events WHERE timestamp < %s", (cutoff,))

    async def _trigger_alert(self, event: AuditEvent) -> None:
        return None
