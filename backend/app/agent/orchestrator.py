from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from app.agent.continuity import apply_session_continuity
from app.agent.pipeline import run_pipeline
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.intent.classifier import IntentClassifier
from app.intent.labels import INTENT_META, Intent
from app.risk.masker import mask_sensitive
from app.state.session import session_store

logger = get_logger(__name__)

_SYSTEM_ERROR = "系统开小差了，请稍后重试，或输入「转人工」获取帮助。"
_SENTINEL = object()


class Orchestrator:
    """对话编排入口：会话准备 + 意图分类 + 统一流水线（流式/非流式共用）。"""

    def __init__(self) -> None:
        self.intent = IntentClassifier()

    async def handle_message(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        metrics.record_request()
        session = session_store.get_or_create(session_id, user_id)
        raw_message = message
        safe_message = mask_sensitive(message)
        session.add_user(safe_message)

        try:
            intent_id, intent_result = await self._classify(session, safe_message)
            payload = await run_pipeline(
                session=session,
                message=safe_message,
                intent_id=intent_id,
                emit=None,
                stream=False,
            )
            answer = mask_sensitive(payload.get("answer", ""))
            session.add_assistant(answer)
            latency_ms = (time.perf_counter() - t0) * 1000
            metrics.record_latency(latency_ms)
            return {
                "session_id": session.session_id,
                "user_id": user_id,
                "intent": intent_id,
                "intent_name": INTENT_META.get(Intent(intent_id), {}).get("name", intent_id),
                "confidence": intent_result.get("confidence"),
                "answer": answer,
                "sources": payload.get("sources", []),
                "tools": payload.get("tools", []),
                "handoff": payload.get("handoff", session.handoff),
                "risk_flags": payload.get("risk_flags", []),
                "entities": session.entities,
                "after_sales_state": session.after_sales.state.value,
                "latency_ms": round(latency_ms, 2),
                "masked_input": safe_message != raw_message,
            }
        except Exception as e:  # noqa: BLE001
            metrics.record_error()
            logger.exception("handle_message failed")
            answer = _SYSTEM_ERROR
            session.add_assistant(answer)
            return {
                "session_id": session.session_id,
                "user_id": user_id,
                "intent": "fallback",
                "answer": answer,
                "error": str(e),
                "handoff": False,
                "sources": [],
                "tools": [],
                "risk_flags": ["system_error"],
            }

    async def handle_message_stream(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE 事件流：intent / tool_start / tool_result / sources / token / done / error"""
        t0 = time.perf_counter()
        metrics.record_request()
        session = session_store.get_or_create(session_id, user_id)
        safe_message = mask_sensitive(message)
        session.add_user(safe_message)

        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: str, data: dict[str, Any]) -> None:
            await queue.put({"event": event, "data": data})

        async def runner() -> None:
            try:
                intent_id, intent_result = await self._classify(session, safe_message)
                await emit(
                    "intent",
                    {
                        "intent": intent_id,
                        "intent_name": INTENT_META.get(Intent(intent_id), {}).get("name"),
                        "confidence": intent_result.get("confidence"),
                        "entities": session.entities,
                    },
                )
                payload = await run_pipeline(
                    session=session,
                    message=safe_message,
                    intent_id=intent_id,
                    emit=emit,
                    stream=True,
                )
                answer = mask_sensitive(payload.get("answer", ""))
                session.add_assistant(answer)
                latency_ms = (time.perf_counter() - t0) * 1000
                metrics.record_latency(latency_ms)
                await queue.put(
                    {
                        "event": "__final__",
                        "data": {
                            "session_id": session.session_id,
                            "intent": intent_id,
                            "answer": answer,
                            "sources": payload.get("sources", []),
                            "tools": payload.get("tools", []),
                            "handoff": payload.get("handoff", session.handoff),
                            "risk_flags": payload.get("risk_flags", []),
                            "latency_ms": round(latency_ms, 2),
                            "after_sales_state": session.after_sales.state.value,
                        },
                    }
                )
            except Exception as e:  # noqa: BLE001
                metrics.record_error()
                logger.exception("stream failed")
                await queue.put({"event": "error", "data": {"message": str(e)}})
            finally:
                await queue.put(_SENTINEL)

        task = asyncio.create_task(runner())
        final: dict[str, Any] | None = None
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                if item.get("event") == "__final__":
                    final = item["data"]
                    continue
                yield item
        finally:
            await task

        if final is not None:
            yield {"event": "done", "data": final}

    async def _classify(
        self,
        session: Any,
        safe_message: str,
    ) -> tuple[str, dict[str, Any]]:
        intent_result = await self.intent.classify(safe_message)
        intent_id = intent_result["intent"]
        intent_id, intent_result = apply_session_continuity(
            session, intent_id, intent_result, safe_message
        )
        session.last_intent = intent_id
        session.merge_entities(intent_result.get("entities") or {})
        metrics.record_intent(intent_id)
        return intent_id, intent_result


orchestrator = Orchestrator()
