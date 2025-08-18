from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

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
    def __init__(self, db_path: str = "audit.db") -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_database()
        self._retention_days = 2555
        self._compliance_mode = True

    def _init_database(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA wal_autocheckpoint=512")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME NOT NULL,
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
                    details TEXT,
                    tags TEXT,
                    compliance_frameworks TEXT,
                    hash TEXT UNIQUE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_events(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON audit_events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON audit_events(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_resource_id ON audit_events(resource_id)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_correlation_id ON audit_events(correlation_id)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON audit_events(hash)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            conn.commit()
            conn.close()

    async def log_event(self, event: AuditEvent) -> bool:
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO audit_events (
                        id, timestamp, event_type, severity, user_id, user_email,
                        service_principal_id, subscription_id, resource_group,
                        resource_type, resource_name, resource_id, action, result,
                        ip_address, user_agent, correlation_id, details, tags,
                        compliance_frameworks, hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        event.id,
                        event.timestamp.isoformat(),
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
                        json.dumps(event.details),
                        json.dumps(event.tags),
                        json.dumps(event.compliance_frameworks),
                        event.hash,
                    ),
                )

                conn.commit()
                conn.close()

                if event.severity in [AuditSeverity.ERROR, AuditSeverity.CRITICAL]:
                    await self._trigger_alert(event)

                return True

        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.exception("Failed to log audit event: %s", e)
            return False

    async def query_events(self, query: AuditQuery) -> list[AuditEvent]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            sql = "SELECT * FROM audit_events WHERE 1=1"
            params: list[Any] = []

            if query.start_time:
                sql += " AND timestamp >= ?"
                params.append(query.start_time.isoformat())

            if query.end_time:
                sql += " AND timestamp <= ?"
                params.append(query.end_time.isoformat())

            if query.event_types:
                placeholders = ",".join("?" * len(query.event_types))
                sql += f" AND event_type IN ({placeholders})"
                params.extend([et.value for et in query.event_types])

            if query.severities:
                placeholders = ",".join("?" * len(query.severities))
                sql += f" AND severity IN ({placeholders})"
                params.extend([s.value for s in query.severities])

            if query.user_ids:
                placeholders = ",".join("?" * len(query.user_ids))
                sql += f" AND user_id IN ({placeholders})"
                params.extend(query.user_ids)

            if query.resource_groups:
                placeholders = ",".join("?" * len(query.resource_groups))
                sql += f" AND resource_group IN ({placeholders})"
                params.extend(query.resource_groups)

            if query.resource_types:
                placeholders = ",".join("?" * len(query.resource_types))
                sql += f" AND resource_type IN ({placeholders})"
                params.extend(query.resource_types)

            if query.subscription_ids:
                placeholders = ",".join("?" * len(query.subscription_ids))
                sql += f" AND subscription_id IN ({placeholders})"
                params.extend(query.subscription_ids)

            if query.correlation_ids:
                placeholders = ",".join("?" * len(query.correlation_ids))
                sql += f" AND correlation_id IN ({placeholders})"
                params.extend(query.correlation_ids)

            sql += " ORDER BY timestamp DESC"
            sql += f" LIMIT {query.limit} OFFSET {query.offset}"

            cursor.execute(sql, params)
            rows = cursor.fetchall()
            conn.close()

            events: list[AuditEvent] = []
            for row in rows:
                event = AuditEvent(
                    id=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
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
                    compliance_frameworks=json.loads(row[19]) if row[19] else [],
                    hash=row[20],
                )
                events.append(event)

            return events

    async def get_statistics(self, start_time: datetime, end_time: datetime) -> dict[str, Any]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT 
                    COUNT(*) as total_events,
                    COUNT(DISTINCT user_id) as unique_users,
                    COUNT(DISTINCT resource_id) as unique_resources,
                    COUNT(DISTINCT correlation_id) as unique_operations
                FROM audit_events
                WHERE timestamp BETWEEN ? AND ?
            """,
                (start_time.isoformat(), end_time.isoformat()),
            )

            stats = cursor.fetchone()

            cursor.execute(
                """
                SELECT event_type, COUNT(*) as count
                FROM audit_events
                WHERE timestamp BETWEEN ? AND ?
                GROUP BY event_type
            """,
                (start_time.isoformat(), end_time.isoformat()),
            )

            event_type_counts = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute(
                """
                SELECT severity, COUNT(*) as count
                FROM audit_events
                WHERE timestamp BETWEEN ? AND ?
                GROUP BY severity
            """,
                (start_time.isoformat(), end_time.isoformat()),
            )

            severity_counts = {row[0]: row[1] for row in cursor.fetchall()}

            conn.close()

            return {
                "total_events": stats[0],
                "unique_users": stats[1],
                "unique_resources": stats[2],
                "unique_operations": stats[3],
                "event_type_distribution": event_type_counts,
                "severity_distribution": severity_counts,
            }

    async def verify_integrity(self, event_id: str) -> bool:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM audit_events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return False

            event = AuditEvent(
                id=row[0],
                timestamp=datetime.fromisoformat(row[1]),
                event_type=AuditEventType(row[2]),
                severity=AuditSeverity(row[3]),
                user_id=row[4],
                resource_id=row[11],
                action=row[12],
            )

            calculated_hash = event._calculate_hash()
            stored_hash = row[20]

            return calculated_hash == stored_hash

    async def export_for_compliance(
        self, framework: str, start_time: datetime, end_time: datetime
    ) -> dict[str, Any]:
        query = AuditQuery(
            start_time=start_time,
            end_time=end_time,
        )

        events = await self.query_events(query)

        filtered_events = [e for e in events if framework in e.compliance_frameworks]

        if framework == "gdpr":
            return self._format_gdpr_report(filtered_events)
        elif framework == "hipaa":
            return self._format_hipaa_report(filtered_events)
        elif framework == "pci-dss":
            return self._format_pci_report(filtered_events)
        elif framework == "sox":
            return self._format_sox_report(filtered_events)
        else:
            return self._format_generic_report(filtered_events)

    def _format_gdpr_report(self, events: list[AuditEvent]) -> dict[str, Any]:
        return {
            "framework": "gdpr",
            "data_access_events": [
                asdict(e)
                for e in events
                if e.event_type in [AuditEventType.ACCESS_GRANTED, AuditEventType.ACCESS_DENIED]
            ],
            "data_modification_events": [
                asdict(e)
                for e in events
                if e.event_type
                in [AuditEventType.RESOURCE_UPDATED, AuditEventType.RESOURCE_DELETED]
            ],
            "consent_events": [],
            "data_breach_events": [
                asdict(e) for e in events if e.severity == AuditSeverity.CRITICAL
            ],
        }

    def _format_hipaa_report(self, events: list[AuditEvent]) -> dict[str, Any]:
        return {
            "framework": "hipaa",
            "phi_access_events": [
                asdict(e) for e in events if "phi" in e.tags or "healthcare" in e.tags
            ],
            "security_events": [
                asdict(e) for e in events if e.event_type == AuditEventType.SECURITY_ALERT
            ],
            "audit_control_events": [asdict(e) for e in events],
        }

    def _format_pci_report(self, events: list[AuditEvent]) -> dict[str, Any]:
        return {
            "framework": "pci-dss",
            "cardholder_data_events": [
                asdict(e) for e in events if "payment" in e.tags or "card" in e.tags
            ],
            "network_security_events": [
                asdict(e)
                for e in events
                if "network" in (e.resource_type or "") or "firewall" in (e.resource_type or "")
            ],
            "access_control_events": [
                asdict(e)
                for e in events
                if e.event_type in [AuditEventType.ACCESS_GRANTED, AuditEventType.ACCESS_DENIED]
            ],
        }

    def _format_sox_report(self, events: list[AuditEvent]) -> dict[str, Any]:
        return {
            "framework": "sox",
            "financial_system_events": [
                asdict(e) for e in events if "financial" in e.tags or "accounting" in e.tags
            ],
            "change_management_events": [
                asdict(e) for e in events if e.event_type == AuditEventType.CONFIGURATION_CHANGED
            ],
            "access_control_events": [
                asdict(e)
                for e in events
                if e.event_type in [AuditEventType.ACCESS_GRANTED, AuditEventType.ACCESS_DENIED]
            ],
        }

    def _format_generic_report(self, events: list[AuditEvent]) -> dict[str, Any]:
        return {
            "framework": "generic",
            "events": [asdict(e) for e in events],
            "summary": {
                "total_events": len(events),
                "event_types": list(set(e.event_type.value for e in events)),
                "severities": list(set(e.severity.value for e in events)),
            },
        }

    async def cleanup_old_events(self) -> None:
        cutoff_date = datetime.utcnow() - timedelta(days=self._retention_days)

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if self._compliance_mode:
                cursor.execute(
                    """
                    UPDATE audit_events 
                    SET details = '{"archived": true}', 
                        tags = '{"archived": true}'
                    WHERE timestamp < ?
                """,
                    (cutoff_date.isoformat(),),
                )
            else:
                cursor.execute(
                    """
                    DELETE FROM audit_events 
                    WHERE timestamp < ?
                """,
                    (cutoff_date.isoformat(),),
                )

            conn.commit()
            conn.close()

    async def _trigger_alert(self, event: AuditEvent) -> None:
        return None


class AuditMiddleware:
    def __init__(self, audit_logger: AuditLogger) -> None:
        self.audit_logger = audit_logger

    async def log_deployment(
        self,
        user_id: str,
        action: str,
        resource_type: str,
        resource_name: str,
        result: str,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=(
                AuditEventType.DEPLOYMENT_STARTED
                if result == "started"
                else AuditEventType.DEPLOYMENT_COMPLETED
            ),
            severity=AuditSeverity.INFO if result == "success" else AuditSeverity.ERROR,
            user_id=user_id,
            resource_type=resource_type,
            resource_name=resource_name,
            action=action,
            result=result,
            details=details or {},
            correlation_id=correlation_id,
        )

        await self.audit_logger.log_event(event)

    async def log_access(
        self,
        user_id: str,
        resource_id: str,
        action: str,
        granted: bool,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=(AuditEventType.ACCESS_GRANTED if granted else AuditEventType.ACCESS_DENIED),
            severity=AuditSeverity.INFO if granted else AuditSeverity.WARNING,
            user_id=user_id,
            resource_id=resource_id,
            action=action,
            result="granted" if granted else "denied",
            ip_address=ip_address,
            user_agent=user_agent,
        )

        await self.audit_logger.log_event(event)

    async def log_configuration_change(
        self,
        user_id: str,
        resource_id: str,
        changes: dict[str, Any],
        correlation_id: str | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=AuditEventType.CONFIGURATION_CHANGED,
            severity=AuditSeverity.INFO,
            user_id=user_id,
            resource_id=resource_id,
            action="configuration_change",
            details={"changes": changes},
            correlation_id=correlation_id,
        )

        await self.audit_logger.log_event(event)

    async def log_compliance_violation(
        self,
        framework: str,
        violation: str,
        resource_id: str | None = None,
        severity: AuditSeverity = AuditSeverity.WARNING,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=AuditEventType.COMPLIANCE_VIOLATION,
            severity=severity,
            resource_id=resource_id,
            action="compliance_check",
            result="violation",
            details={"framework": framework, "violation": violation, **(details or {})},
            compliance_frameworks=[framework],
        )

        await self.audit_logger.log_event(event)

    async def log_security_alert(
        self,
        alert_type: str,
        resource_id: str | None = None,
        severity: AuditSeverity = AuditSeverity.CRITICAL,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=AuditEventType.SECURITY_ALERT,
            severity=severity,
            resource_id=resource_id,
            action="security_alert",
            result=alert_type,
            details=details or {},
        )

        await self.audit_logger.log_event(event)
