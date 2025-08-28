from .key_vault import KeyVaultEmitter
from .logging import AppInsightsEmitter, DiagnosticSettingsEmitter, LogAnalyticsEmitter
from .networking import PrivateDnsLinkEmitter, PrivateDnsZoneEmitter, PrivateEndpointEmitter
from .redis import RedisEmitter
from .resource_group import ResourceGroupEmitter
from .service_bus import ServiceBusEmitter
from .sql import SqlDatabaseEmitter, SqlServerEmitter
from .storage_account import StorageAccountEmitter
from .vnet import VnetEmitter
from .web_app import WebAppEmitter

EMITTERS = [
    ResourceGroupEmitter(),
    VnetEmitter(),
    KeyVaultEmitter(),
    StorageAccountEmitter(),
    WebAppEmitter(),
    LogAnalyticsEmitter(),
    AppInsightsEmitter(),
    DiagnosticSettingsEmitter(),
    PrivateDnsZoneEmitter(),
    PrivateDnsLinkEmitter(),
    PrivateEndpointEmitter(),
    ServiceBusEmitter(),
    RedisEmitter(),
    SqlServerEmitter(),
    SqlDatabaseEmitter(),
]
