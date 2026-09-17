from __future__ import annotations

import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.agent.orchestrator import orchestrator
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1", tags=["chat"])


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
