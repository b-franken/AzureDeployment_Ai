from __future__ import annotations

import uvicorn

from app.core.config import API_HOST, API_PORT, settings


def main() -> None:
    uvicorn.run(
        "app.api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=bool(settings.debug),
    )


if __name__ == "__main__":
    main()
