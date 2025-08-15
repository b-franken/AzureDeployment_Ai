from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(
        "app.api.main:app",
        host=host,
        port=port,
        reload=os.getenv("API_RELOAD", "0") == "1",
    )


if __name__ == "__main__":
    main()
