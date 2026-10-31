"""Backend entry point: ``python -m nexapilot`` or ``uvicorn nexapilot.main:app``."""

from __future__ import annotations

import sys

import uvicorn

from nexapilot.api.app import create_app
from nexapilot.core.config import get_settings

app = create_app()


def main() -> None:
    settings = get_settings()
    frozen = bool(getattr(sys, "frozen", False))
    reload = settings.environment == "development" and not frozen
    uvicorn.run(
        "nexapilot.main:app" if reload else app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=reload,
    )


if __name__ == "__main__":
    main()
