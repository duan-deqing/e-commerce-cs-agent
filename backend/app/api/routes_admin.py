from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import verify_api_key
from app.core.config import settings
from app.core.metrics import metrics
from app.intent.labels import intent_catalog
from app.state.session import session_store
from app.tools.base import registry

router = APIRouter(
    prefix="/api/v1",
    tags=["admin"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/intents")
async def list_intents() -> dict:
    return {"intents": intent_catalog()}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    summary = session_store.summary(session_id)
    if not summary:
        raise HTTPException(status_code=404, detail="session not found")
    return summary


@router.post("/knowledge/reindex")
async def reindex() -> dict:
    from app.rag.vectorstore import ingest_knowledge_dir

    n = await ingest_knowledge_dir()
    return {"ok": True, "chunks": n, "knowledge_dir": str(settings.knowledge_path)}


@router.get("/tools")
async def list_tools() -> dict:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "required_entities": t.required_entities,
                "optional_entities": t.optional_entities,
            }
            for t in registry.all()
        ]
    }


@router.get("/sql-templates")
async def list_sql_templates() -> dict:
    """SQL Agent 模板目录：只允许执行这些参数化语句。"""
    from app.agent.sql_agent.agent import sql_agent

    return {"templates": sql_agent.catalog()}


@router.get("/metrics")
async def get_metrics() -> dict:
    return {**metrics.snapshot(), "sessions": session_store.stats()}
