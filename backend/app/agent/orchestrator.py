"""对话编排入口。

职责：会话准备 → 脱敏 → 意图分类 → 调用 pipeline；
流式模式用 asyncio.Queue 把 pipeline 事件转成 SSE。
每个请求生成 trace_id，结束后落库 request_trace 并记录监控指标。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from app.agent.continuity import apply_session_continuity
from app.agent.pipeline import run_pipeline
from app.agent.summarizer import maybe_summarize
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.core.tracing import new_trace_id, save_trace
from app.intent.classifier import IntentClassifier
from app.intent.labels import INTENT_META, Intent
from app.risk.masker import mask_sensitive
from app.state.session import session_store

logger = get_logger(__name__)

_SYSTEM_ERROR = "系统开小差了，请稍后重试，或输入「转人工」获取帮助。"
_SENTINEL = object()

# 坏案例判定：置信度低于该阈值视为低置信请求
LOW_CONF_THRESHOLD = 0.55


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
        """非流式：一次返回完整 JSON 应答。"""
        t0 = time.perf_counter()
        metrics.record_request()
        trace_id = new_trace_id()
        session = session_store.get_or_create(session_id, user_id)
        raw_message = message
        safe_message = mask_sensitive(message)
        await maybe_summarize(session)
        session.add_user(safe_message)

        error: str | None = None
        intent_id = "fallback"
        intent_result: dict[str, Any] = {}
        payload: dict[str, Any] = {}
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
            try:
                intent_name = INTENT_META.get(Intent(intent_id), {}).get("name", intent_id)
            except ValueError:
                intent_name = intent_id
            result = {
                "session_id": session.session_id,
                "trace_id": trace_id,
                "user_id": user_id,
                "intent": intent_id,
                "intent_name": intent_name,
                "confidence": intent_result.get("confidence"),
                "answer": answer,
                "sources": payload.get("sources", []),
                "tools": payload.get("tools", []),
                "handoff": bool(payload.get("handoff") or session.handoff),
                "risk_flags": payload.get("risk_flags", []),
                "entities": session.entities,
                "after_sales_state": session.after_sales.state.value,
                "latency_ms": round(latency_ms, 2),
                "masked_input": safe_message != raw_message,
            }
            self._finalize(
                trace_id=trace_id,
                ts=t0,
                session=session,
                intent_id=intent_id,
                intent_result=intent_result,
                payload=payload,
                latency_ms=latency_ms,
                ttft_ms=None,
                error=error,
                answer=answer,
                masked=safe_message != raw_message,
            )
            return result
        except Exception as e:  # noqa: BLE001
            metrics.record_error()
            # 坏案例计数统一由 _finalize 按 error 判定，避免双倍计数
            error = str(e)
            logger.exception("handle_message failed")
            answer = _SYSTEM_ERROR
            session.add_assistant(answer)
            self._finalize(
                trace_id=trace_id,
                ts=t0,
                session=session,
                intent_id=intent_id,
                intent_result=intent_result,
                payload=payload,
                latency_ms=(time.perf_counter() - t0) * 1000,
                ttft_ms=None,
                error=error,
                answer=answer,
                masked=safe_message != raw_message,
            )
            return {
                "session_id": session.session_id,
                "trace_id": trace_id,
                "user_id": user_id,
                "intent": "fallback",
                "answer": answer,
                "error": error,
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
        """流式 SSE：intent / tool_* / sources / token / done / error。"""
        t0 = time.perf_counter()
        metrics.record_request()
        trace_id = new_trace_id()
        session = session_store.get_or_create(session_id, user_id)
        safe_message = mask_sensitive(message)
        await maybe_summarize(session)
        session.add_user(safe_message)

        queue: asyncio.Queue = asyncio.Queue()
        ttft_holder: dict[str, float | None] = {"ttft_ms": None}

        async def emit(event: str, data: dict[str, Any]) -> None:
            # 首个 token 事件即用户可感知首字（覆盖快捷回复早退路径）
            if event == "token" and ttft_holder["ttft_ms"] is None:
                ttft_holder["ttft_ms"] = (time.perf_counter() - t0) * 1000
                metrics.record_ttft(ttft_holder["ttft_ms"])
            await queue.put({"event": event, "data": data})

        async def runner() -> None:
            error: str | None = None
            intent_id = "fallback"
            intent_result: dict[str, Any] = {}
            payload: dict[str, Any] = {}
            try:
                intent_id, intent_result = await self._classify(session, safe_message)
                await emit(
                    "intent",
                    {
                        "trace_id": trace_id,
                        "intent": intent_id,
                        "intent_name": (
                            INTENT_META.get(Intent(intent_id), {}).get("name")
                            if intent_id in {i.value for i in Intent}
                            else intent_id
                        ),
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
                            "trace_id": trace_id,
                            "intent": intent_id,
                            "answer": answer,
                            "sources": payload.get("sources", []),
                            "tools": payload.get("tools", []),
                            "handoff": bool(payload.get("handoff") or session.handoff),
                            "risk_flags": payload.get("risk_flags", []),
                            "latency_ms": round(latency_ms, 2),
                            "after_sales_state": session.after_sales.state.value,
                        },
                    }
                )
                self._finalize(
                    trace_id=trace_id,
                    ts=t0,
                    session=session,
                    intent_id=intent_id,
                    intent_result=intent_result,
                    payload=payload,
                    latency_ms=latency_ms,
                    ttft_ms=ttft_holder["ttft_ms"],
                    error=None,
                    answer=answer,
                    masked=safe_message != message,
                )
            except Exception as e:  # noqa: BLE001
                metrics.record_error()
                # 坏案例计数统一由 _finalize 按 error 判定，避免双倍计数
                error = str(e)
                logger.exception("stream failed")
                await queue.put({"event": "error", "data": {"message": error, "trace_id": trace_id}})
                self._finalize(
                    trace_id=trace_id,
                    ts=t0,
                    session=session,
                    intent_id=intent_id,
                    intent_result=intent_result,
                    payload=payload,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    ttft_ms=ttft_holder["ttft_ms"],
                    error=error,
                    answer=_SYSTEM_ERROR,
                    masked=safe_message != message,
                )
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
        # 意图切换时裁剪无关实体，避免订单号/原因串味
        from app.intent.entities import prune_entities_for_intent

        session.entities = prune_entities_for_intent(
            session.entities, session.last_intent, intent_id
        )
        session.last_intent = intent_id
        session.merge_entities(intent_result.get("entities") or {})
        metrics.record_intent(intent_id)
        return intent_id, intent_result

    def _finalize(
        self,
        trace_id: str,
        ts: float,
        session: Any,
        intent_id: str,
        intent_result: dict[str, Any],
        payload: dict[str, Any],
        latency_ms: float,
        ttft_ms: float | None,
        error: str | None,
        answer: str,
        masked: bool,
    ) -> None:
        """统一收尾：记录 tokens/cost/handoff/badcase 指标并落库 trace（旁路，不抛错）。"""
        try:
            usage = payload.get("usage") or {}
            p_tokens = int(usage.get("prompt_tokens") or 0)
            c_tokens = int(usage.get("completion_tokens") or 0)
            estimated = bool(usage.get("estimated"))
            cost = (
                p_tokens * settings.llm_price_prompt_per_1k
                + c_tokens * settings.llm_price_completion_per_1k
            ) / 1000.0
            metrics.record_tokens(p_tokens, c_tokens, estimated, cost)

            tools = payload.get("tools", []) or []
            sources = payload.get("sources", []) or []
            handoff = bool(payload.get("handoff") or session.handoff)
            if handoff:
                metrics.record_handoff()

            confidence = float(intent_result.get("confidence") or 0.0)
            is_badcase = bool(error) or (
                confidence < LOW_CONF_THRESHOLD and intent_id == "fallback"
            ) or (
                bool(tools) and not any(t.get("success") for t in tools)
            )
            if is_badcase:
                metrics.record_badcase()

            save_trace(
                {
                    "trace_id": trace_id,
                    "ts": time.time() - (time.perf_counter() - ts),
                    "session_id": session.session_id,
                    "user_id": session.user_id,
                    "intent": intent_id,
                    "confidence": confidence,
                    "route": intent_id,
                    "model": settings.llm_model,
                    "prompt_version": usage.get("prompt_version") or settings.prompt_version,
                    "tools_json": tools,
                    "sources_json": sources,
                    "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
                    "total_ms": round(latency_ms, 2),
                    "prompt_tokens": p_tokens,
                    "completion_tokens": c_tokens,
                    "tokens_estimated": int(estimated),
                    "cost": round(cost, 8),
                    "handoff": int(handoff),
                    "error": error,
                    "answer_snippet": (answer or "")[:200],
                    "masked_input": int(masked),
                }
            )
        except Exception:  # noqa: BLE001
            logger.exception("finalize trace failed (non-fatal)")


orchestrator = Orchestrator()
