from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.chat import HealthResponse
from app.tools.base import registry

router = APIRouter(tags=["health"])


@router.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    chroma_ready = settings.chroma_path.exists()
    return HealthResponse(
        status="ok",
        env=settings.app_env,
        mock_llm=settings.use_mock_llm,
        chroma_ready=chroma_ready,
        tools_registered=len(registry.all()),
    )


@router.get("/health")
async def health_alias() -> dict:
    return {"status": "ok"}
