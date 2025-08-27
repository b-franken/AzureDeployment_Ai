from __future__ import annotations

import uvicorn

from app.core.config import API_HOST, API_PORT, settings
from app.core.logging import configure_logging


def main() -> None:
    # Configure logging based on settings before starting the application
    configure_logging(
        level=settings.log_level,
        fmt=settings.observability.log_format,
        log_file=settings.observability.log_file,
        max_bytes=settings.observability.log_rotation_size_mb * 1024 * 1024 if settings.observability.log_rotation_size_mb else None,
        retention=settings.observability.log_retention_days,
        enable_console=True,
        context={
            "service": settings.observability.otel_service_name,
            "version": settings.app_version,
            "environment": settings.environment,
        }
    )
    
    uvicorn.run(
        "app.api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=bool(settings.debug),
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
