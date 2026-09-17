"""启动入口：python run.py"""
from __future__ import annotations

import uvicorn

from app.core.config import settings


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "dev",
    )


if __name__ == "__main__":
    main()
