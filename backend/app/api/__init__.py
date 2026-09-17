from __future__ import annotations

from app.api.routes_admin import router as admin_router
from app.api.routes_chat import router as chat_router
from app.api.routes_health import router as health_router

__all__ = ["admin_router", "chat_router", "health_router"]
