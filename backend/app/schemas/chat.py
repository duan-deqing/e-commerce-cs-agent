from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    session_id: str | None = Field(default=None, description="会话 ID，空则新建")
    user_id: str = Field(default="u_anonymous", description="用户 ID")


class SourceModel(BaseModel):
    doc_id: str
    title: str
    score: float | None = None
    snippet: str


class DocDetailResponse(BaseModel):
    doc_id: str
    title: str
    content: str
    source: str = ""
    section: str = ""


class ToolResultModel(BaseModel):
    tool: str
    success: bool
    data: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    total_ms: float = 0.0
    retried: int = 0


class ChatResponse(BaseModel):
    session_id: str
    user_id: str
    intent: str
    intent_name: str | None = None
    confidence: float | None = None
    answer: str
    sources: list[SourceModel] = []
    tools: list[ToolResultModel] = []
    handoff: bool = False
    risk_flags: list[str] = []
    entities: dict[str, Any] = {}
    after_sales_state: str | None = None
    latency_ms: float | None = None
    masked_input: bool = False
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    env: str
    mock_llm: bool
    chroma_ready: bool
    tools_registered: int
    version: str = "0.1.0"


class SessionSummary(BaseModel):
    session_id: str
    user_id: str
    message_count: int
    last_intent: str | None = None
    entities: dict[str, Any] = {}
    handoff: bool = False
    after_sales: dict[str, Any] = {}
    created_at: float
    updated_at: float
