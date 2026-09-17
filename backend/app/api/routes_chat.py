"""聊天 API：非流式 JSON 与 SSE 流式。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.agent.orchestrator import orchestrator
from app.core.auth import verify_api_key
from app.schemas.chat import ChatRequest, ChatResponse, DocDetailResponse

router = APIRouter(prefix="/api/v1", tags=["chat"], dependencies=[Depends(verify_api_key)])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    result = await orchestrator.handle_message(
        user_id=req.user_id,
        message=req.message,
        session_id=req.session_id,
    )
    return ChatResponse(**result)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> EventSourceResponse:
    async def event_gen():
        async for item in orchestrator.handle_message_stream(
            user_id=req.user_id,
            message=req.message,
            session_id=req.session_id,
        ):
            yield {
                "event": item.get("event", "message"),
                "data": json.dumps(item.get("data", {}), ensure_ascii=False),
            }

    return EventSourceResponse(event_gen(), media_type="text/event-stream")


@router.get("/kb/doc", response_model=DocDetailResponse)
async def kb_doc(doc_id: str) -> DocDetailResponse:
    """引用溯源：按 chunk id 返回知识库文档块全文与来源。"""
    from app.rag.vectorstore import get_chunk_by_id

    detail = await get_chunk_by_id(doc_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"doc not found: {doc_id}")
    return DocDetailResponse(**detail)
