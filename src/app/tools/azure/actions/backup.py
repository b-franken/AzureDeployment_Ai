from __future__ import annotations

import logging
from datetime import UTC

from azure.core.exceptions import HttpResponseError

from ..clients import Clients
from ..utils.credentials import ensure_sync_credential
from ..validators import validate_name

logger = logging.getLogger(__name__)


async def create_recovery_services_vault(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    sku: str = "Standard",
    storage_type: str = "GeoRedundant",
    cross_region_restore: bool = True,
    soft_delete: bool = True,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid recovery services vault name"}

    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
            "sku": sku,
            "storage_type": storage_type,
            "cross_region_restore": cross_region_restore,
            "soft_delete": soft_delete,
            "tags": tags or {},
        }

    from azure.mgmt.recoveryservices import RecoveryServicesClient
    from azure.mgmt.recoveryservices.models import Sku as VaultSku
    from azure.mgmt.recoveryservices.models import Vault
    from azure.mgmt.recoveryservicesbackup import (
        BackupStorageConfig,
        RecoveryServicesBackupClient,
    )

    sync_cred = ensure_sync_credential(clients.cred)
    rs_client = RecoveryServicesClient(sync_cred, clients.subscription_id)
    backup_client = RecoveryServicesBackupClient(sync_cred, clients.subscription_id)

    try:
        existing = await clients.run(rs_client.vaults.get, resource_group, name)
        if existing and not force:
            return "exists", existing.as_dict()
    except HttpResponseError as exc:
        if exc.status_code != 404:
            logger.error("Vault retrieval failed: %s", exc.message)
            return "error", {"code": exc.status_code, "message": exc.message}

    vault = Vault(
        location=location,
        sku=VaultSku(name=sku),
        tags=tags or {},
    )

    poller = await clients.run(
        rs_client.vaults.begin_create_or_update,
        resource_group,
        name,
        vault,
    )
    result = await clients.run(poller.result)

    storage_config = BackupStorageConfig(
        storage_model_type=storage_type,
        cross_region_restore_flag=cross_region_restore,
    )

    await clients.run(
        backup_client.backup_resource_storage_configs_non_crr.update,
        name,
        resource_group,
        storage_config,
    )

    return "created", result.as_dict()


async def create_backup_policy(
    *,
    clients: Clients,
    resource_group: str,
    vault_name: str,
    policy_name: str,
    policy_type: str = "AzureIaasVM",
    schedule_run_times: list[str] | None = None,
    retention_daily: int = 30,
    retention_weekly: int | None = None,
    retention_monthly: int | None = None,
    retention_yearly: int | None = None,
    instant_restore_retention: int = 2,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", policy_name):
        return "error", {"message": "invalid backup policy name"}

    if dry_run:
        return "plan", {
            "policy_name": policy_name,
            "vault_name": vault_name,
            "resource_group": resource_group,
            "policy_type": policy_type,
            "retention_daily": retention_daily,
            "tags": tags or {},
        }

    from datetime import datetime

    from azure.mgmt.recoveryservicesbackup import (
        AzureIaaSVMProtectionPolicy,
        DailyRetentionSchedule,
        Day,
        DayOfWeek,
        LongTermRetentionPolicy,
        MonthlyRetentionSchedule,
        RecoveryServicesBackupClient,
        RetentionDuration,
        SimpleSchedulePolicy,
        WeeklyRetentionSchedule,
        YearlyRetentionSchedule,
    )

    sync_cred = ensure_sync_credential(clients.cred)
    backup_client = RecoveryServicesBackupClient(sync_cred, clients.subscription_id)

    try:
        existing = await clients.run(
            backup_client.protection_policies.get,
            vault_name,
            resource_group,
            policy_name,
        )
        if existing and not force:
            return "exists", existing.as_dict()
    except HttpResponseError as exc:
        if exc.status_code != 404:
            logger.error("Backup policy retrieval failed: %s", exc.message)
            return "error", {"code": exc.status_code, "message": exc.message}

    if not schedule_run_times:
        schedule_run_times = [
            datetime.now(UTC).replace(hour=2, minute=0, second=0, microsecond=0).isoformat()
        ]

    schedule_policy = SimpleSchedulePolicy(
        schedule_run_frequency="Daily",
        schedule_run_times=schedule_run_times,
    )

    daily_retention = DailyRetentionSchedule(
        retention_times=schedule_run_times,
        retention_duration=RetentionDuration(
            count=retention_daily,
            duration_type="Days",
        ),
    )

    retention_policy = LongTermRetentionPolicy(
        daily_schedule=daily_retention,
    )

    if retention_weekly:
        retention_policy.weekly_schedule = WeeklyRetentionSchedule(
            days_of_the_week=[DayOfWeek.SUNDAY],
            retention_times=schedule_run_times,
            retention_duration=RetentionDuration(
                count=retention_weekly,
                duration_type="Weeks",
            ),
        )

    if retention_monthly:
        retention_policy.monthly_schedule = MonthlyRetentionSchedule(
            retention_schedule_format_type="Daily",
            retention_schedule_daily=Day(date=1),
            retention_times=schedule_run_times,
            retention_duration=RetentionDuration(
                count=retention_monthly,
                duration_type="Months",
            ),
        )

    if retention_yearly:
        retention_policy.yearly_schedule = YearlyRetentionSchedule(
            retention_schedule_format_type="Daily",
            months_of_year=["January"],
            retention_schedule_daily=Day(date=1),
            retention_times=schedule_run_times,
            retention_duration=RetentionDuration(
                count=retention_yearly,
                duration_type="Years",
            ),
        )

    policy = AzureIaaSVMProtectionPolicy(
        schedule_policy=schedule_policy,
        retention_policy=retention_policy,
        instant_rp_retention_range_in_days=instant_restore_retention,
        time_zone="UTC",
    )

    result = await clients.run(
        backup_client.protection_policies.create_or_update,
        vault_name,
        resource_group,
        policy_name,
        policy,
    )

    return "created", result.as_dict()
