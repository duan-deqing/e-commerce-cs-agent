from __future__ import annotations

import re
import time
from typing import Any, AsyncIterator

from app.agent.fallback import (
    fallback_response,
    greeting_response,
    handoff_response,
    template_answer_from_tools,
)
from app.agent.prompts import (
    ANSWER_SYSTEM,
    COMPLAINT_ANSWER,
    LOW_CONF_RAG_ANSWER,
    format_sources_block,
    format_tool_block,
)
from app.core.config import settings
from app.core.llm import get_llm
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.intent.classifier import IntentClassifier
from app.intent.labels import INTENT_META, Intent
from app.rag.chain import answer_with_rag, retrieve
from app.risk.masker import mask_sensitive
from app.state.session import AfterSalesState, Session, session_store
from app.tools.base import ToolContext, registry, run_parallel

CONFIRM_RE = re.compile(r"确认|好的可以|同意|没问题|提交|可以的?|^ok$|^好的$|就这个", re.I)
CANCEL_RE = re.compile(r"取消|不要了|算了|先不用|不退了", re.I)

logger = get_logger(__name__)


class Orchestrator:
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
            intent_result = await self.intent.classify(safe_message)
            intent_id = intent_result["intent"]
            intent_id, intent_result = self._apply_session_continuity(session, intent_id, intent_result, safe_message)
            session.last_intent = intent_id
            session.merge_entities(intent_result.get("entities") or {})
            metrics.record_intent(intent_id)

            payload = await self._route(session, intent_id, intent_result, safe_message)
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
            answer = "系统开小差了，请稍后重试，或输入「转人工」获取帮助。"
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

        try:
            intent_result = await self.intent.classify(safe_message)
            intent_id = intent_result["intent"]
            intent_id, intent_result = self._apply_session_continuity(session, intent_id, intent_result, safe_message)
            session.last_intent = intent_id
            session.merge_entities(intent_result.get("entities") or {})
            metrics.record_intent(intent_id)

            yield {
                "event": "intent",
                "data": {
                    "intent": intent_id,
                    "intent_name": INTENT_META.get(Intent(intent_id), {}).get("name"),
                    "confidence": intent_result.get("confidence"),
                    "entities": session.entities,
                },
            }

            meta = INTENT_META.get(Intent(intent_id), {})
            handler = meta.get("handler", "fallback")

            # 快速路径：寒暄 / 转人工
            if handler == "greeting":
                async for ev in self._emit_answer_stream(session, greeting_response(), t0):
                    yield ev
                return
            if handler == "handoff":
                session.handoff = True
                async for ev in self._emit_answer_stream(session, handoff_response(), t0):
                    yield ev
                return
            if handler == "complaint":
                payload = {
                    "answer": COMPLAINT_ANSWER,
                    "handoff": False,
                    "risk_flags": ["complaint"],
                    "tools": [],
                    "sources": [],
                }
                async for ev in self._emit_answer_stream(session, payload, t0):
                    yield ev
                return

            # 售后状态机前置处理（缺参追问等）
            if handler == "after_sales":
                pre = self._after_sales_precheck(session, intent_id, safe_message)
                if pre.get("ask"):
                    payload = {"answer": pre["ask"], "tools": [], "sources": [], "handoff": False, "risk_flags": []}
                    async for ev in self._emit_answer_stream(session, payload, t0):
                        yield ev
                    return

            # 工具阶段
            tool_names = list(meta.get("tools") or [])
            # 后置售后若已确认创建
            if handler == "after_sales" and session.after_sales.state == AfterSalesState.CONFIRMING:
                if session.entities.get("confirm"):
                    tool_names = self._after_sales_submit_tools(intent_id)
                elif session.entities.get("cancel"):
                    session.after_sales.state = AfterSalesState.IDLE
                    payload = {
                        "answer": "已取消本次售后申请。如需再次办理，随时告诉我。",
                        "tools": [],
                        "sources": [],
                        "handoff": False,
                        "risk_flags": [],
                    }
                    async for ev in self._emit_answer_stream(session, payload, t0):
                        yield ev
                    return

            tool_results: list[dict[str, Any]] = []
            if tool_names:
                tools = registry.resolve(tool_names)
                ctx = ToolContext(
                    user_id=user_id,
                    session_id=session.session_id,
                    entities=session.entities,
                    message=safe_message,
                )
                for t in tools:
                    yield {"event": "tool_start", "data": {"tool": t.name}}
                results = await run_parallel(tools, ctx)
                for r in results:
                    d = r.to_dict()
                    tool_results.append(d)
                    yield {"event": "tool_result", "data": d}
                # 售后提交后更新状态
                if handler == "after_sales":
                    self._after_sales_apply_result(session, intent_id, tool_results)
                    # 高金额等风控直接短路输出
                    for r in tool_results:
                        risk = (r.get("data") or {}).get("risk") or {}
                        if risk.get("blocked") and risk.get("message"):
                            payload = {
                                "answer": risk["message"],
                                "tools": tool_results,
                                "sources": [],
                                "handoff": risk.get("require_human", False),
                                "risk_flags": risk.get("flags", []),
                            }
                            async for ev in self._emit_answer_stream(session, payload, t0):
                                yield ev
                            return
                    # 售后创建成功：给确定性话术，避免泛化回答
                    for r in tool_results:
                        data = r.get("data") or {}
                        if r.get("tool") in {"create_return", "create_exchange"} and data.get("success"):
                            ticket = data.get("ticket") or {}
                            kind_label = "退货" if ticket.get("type") == "return" else "换货"
                            answer = (
                                f"已为您提交{kind_label}工单 {ticket.get('ticket_id')}，"
                                f"关联订单 {ticket.get('order_id')}。"
                                f"当前状态：{ticket.get('status')}。"
                                f"退款到账后可在「售后进度」中查询，一般 1-3 个工作日。"
                            )
                            payload = {
                                "answer": answer,
                                "tools": tool_results,
                                "sources": [],
                                "handoff": False,
                                "risk_flags": [],
                            }
                            async for ev in self._emit_answer_stream(session, payload, t0):
                                yield ev
                            return

            # RAG / 混合
            knowledge_block = ""
            sources: list[dict] = []
            use_rag = handler in {"rag", "hybrid"} or (
                handler == "tools"
                and not any(t.get("success") for t in tool_results)
            )
            if handler == "fallback" and session.entities.get("product_kw"):
                use_rag = True

            if use_rag:
                retrieval = await retrieve(safe_message)
                sources = retrieval.get("sources", [])
                if sources:
                    yield {"event": "sources", "data": {"sources": sources}}
                knowledge_block = format_sources_block(sources)
                if retrieval.get("low_confidence") and not tool_results:
                    payload = {
                        "answer": LOW_CONF_RAG_ANSWER,
                        "sources": sources,
                        "tools": tool_results,
                        "handoff": False,
                        "risk_flags": ["low_confidence_rag"],
                    }
                    async for ev in self._emit_answer_stream(session, payload, t0):
                        yield ev
                    return

            # 生成回答
            if handler == "fallback" and not tool_results and not sources:
                payload = fallback_response()
                async for ev in self._emit_answer_stream(session, payload, t0):
                    yield ev
                return

            system = ANSWER_SYSTEM.format(
                intent_name=meta.get("name", intent_id),
                tool_block=format_tool_block(tool_results),
                knowledge_block=knowledge_block or "（无）",
            )
            history = session.as_history_messages()[:-1]
            messages = history + [{"role": "user", "content": safe_message}]
            llm = get_llm()

            answer_parts: list[str] = []
            try:
                async for token in llm.chat_stream(system=system, messages=messages, temperature=0.3):
                    answer_parts.append(token)
                    yield {"event": "token", "data": {"token": token}}
                answer = "".join(answer_parts).strip()
                if not answer:
                    answer = template_answer_from_tools(meta.get("name", ""), tool_results)
                    yield {"event": "token", "data": {"token": answer}}
            except Exception as e:  # noqa: BLE001
                logger.warning("stream gen failed: %s", e)
                answer = template_answer_from_tools(meta.get("name", ""), tool_results)
                yield {"event": "token", "data": {"token": answer}}

            answer = mask_sensitive(answer)
            session.add_assistant(answer)
            latency_ms = (time.perf_counter() - t0) * 1000
            metrics.record_latency(latency_ms)
            yield {
                "event": "done",
                "data": {
                    "session_id": session.session_id,
                    "intent": intent_id,
                    "answer": answer,
                    "sources": sources,
                    "tools": tool_results,
                    "handoff": session.handoff,
                    "latency_ms": round(latency_ms, 2),
                    "after_sales_state": session.after_sales.state.value,
                },
            }
        except Exception as e:  # noqa: BLE001
            metrics.record_error()
            logger.exception("stream failed")
            yield {"event": "error", "data": {"message": str(e)}}

    async def _emit_answer_stream(
        self,
        session: Session,
        payload: dict[str, Any],
        t0: float,
    ) -> AsyncIterator[dict[str, Any]]:
        answer = mask_sensitive(payload.get("answer", ""))
        session.add_assistant(answer)
        yield {"event": "token", "data": {"token": answer}}
        latency_ms = (time.perf_counter() - t0) * 1000
        metrics.record_latency(latency_ms)
        yield {
            "event": "done",
            "data": {
                "session_id": session.session_id,
                "intent": session.last_intent,
                "answer": answer,
                "sources": payload.get("sources", []),
                "tools": payload.get("tools", []),
                "handoff": payload.get("handoff", session.handoff),
                "risk_flags": payload.get("risk_flags", []),
                "latency_ms": round(latency_ms, 2),
                "after_sales_state": session.after_sales.state.value,
            },
        }

    def _apply_session_continuity(
        self,
        session: Session,
        intent_id: str,
        intent_result: dict[str, Any],
        message: str,
    ) -> tuple[str, dict[str, Any]]:
        """售后确认态 / 短确认词：继承上一轮意图，避免确认消息被误判为 fallback。"""
        result = dict(intent_result)
        entities = dict(result.get("entities") or {})

        if CONFIRM_RE.search(message.strip()):
            entities["confirm"] = True
        if CANCEL_RE.search(message.strip()):
            entities["cancel"] = True
            entities.pop("confirm", None)

        as_ctx = session.after_sales
        if as_ctx.state == AfterSalesState.CONFIRMING and as_ctx.kind:
            if entities.get("confirm") or entities.get("cancel"):
                carried = (
                    Intent.AFTER_SALES_RETURN.value
                    if as_ctx.kind == "return"
                    else Intent.AFTER_SALES_EXCHANGE.value
                )
                if intent_id in {Intent.FALLBACK.value, Intent.AFTER_SALES_PROGRESS.value}:
                    intent_id = carried
                    result["confidence"] = max(float(result.get("confidence") or 0.5), 0.9)
                    result["reason"] = "session-continuity"
                    result["source"] = "session"
        # 新发起售后时，避免沿用会话中旧的退货原因
        if (
            intent_id in {Intent.AFTER_SALES_RETURN.value, Intent.AFTER_SALES_EXCHANGE.value}
            and not entities.get("confirm")
            and not entities.get("reason")
            and entities.get("order_id")
            and as_ctx.state != AfterSalesState.CONFIRMING
        ):
            session.entities.pop("reason", None)

        result["entities"] = entities
        return intent_id, result

    def _after_sales_precheck(self, session: Session, intent_id: str, message: str) -> dict[str, Any]:
        as_ctx = session.after_sales
        ent = session.entities

        if intent_id in {Intent.AFTER_SALES_PROGRESS.value, Intent.REFUND_QUERY.value}:
            if not ent.get("ticket_id") and not ent.get("order_id"):
                return {"ask": "请提供售后工单号（TK 开头）或关联订单号，我帮您查询进度。"}
            return {}

        if intent_id in {Intent.AFTER_SALES_RETURN.value, Intent.AFTER_SALES_EXCHANGE.value}:
            kind = "return" if intent_id == Intent.AFTER_SALES_RETURN.value else "exchange"
            # 用户已确认/取消：放行到工具阶段，不再追问
            if ent.get("confirm") or ent.get("cancel"):
                as_ctx.kind = as_ctx.kind or kind
                as_ctx.order_id = as_ctx.order_id or ent.get("order_id")
                as_ctx.reason = ent.get("reason") or as_ctx.reason
                return {}

            if not ent.get("order_id"):
                as_ctx.state = AfterSalesState.COLLECTING_INFO
                as_ctx.kind = kind
                return {"ask": "好的，请提供需要售后的订单号（ORD 开头）。"}
            if not ent.get("reason") and kind == "return":
                as_ctx.state = AfterSalesState.COLLECTING_INFO
                as_ctx.kind = kind
                as_ctx.order_id = ent.get("order_id")
                return {"ask": "收到订单号。请简要说明退货原因（如：尺码不合适 / 质量问题）。"}

            as_ctx.kind = kind
            as_ctx.order_id = ent.get("order_id") or as_ctx.order_id
            as_ctx.reason = ent.get("reason") or as_ctx.reason
            as_ctx.variant = ent.get("variant") or (ent.get("product_kw") if kind == "exchange" else None)
            as_ctx.state = AfterSalesState.CONFIRMING
            label = "退货" if kind == "return" else "换货"
            extra = f"，期望规格：{as_ctx.variant}" if (kind == "exchange" and as_ctx.variant) else ""
            return {
                "ask": (
                    f"即将为您提交{label}：订单 {as_ctx.order_id}，原因：{as_ctx.reason or '未说明'}{extra}。"
                    f"请回复「确认」提交，或「取消」放弃。"
                )
            }
        return {}

    def _after_sales_submit_tools(self, intent_id: str) -> list[str]:
        if intent_id == Intent.AFTER_SALES_RETURN.value:
            return ["create_return"]
        if intent_id == Intent.AFTER_SALES_EXCHANGE.value:
            return ["create_exchange"]
        return ["query_after_sales"]

    def _after_sales_apply_result(
        self,
        session: Session,
        intent_id: str,
        tool_results: list[dict[str, Any]],
    ) -> None:
        as_ctx = session.after_sales
        for r in tool_results:
            if not r.get("success"):
                continue
            data = r.get("data") or {}
            if r.get("tool") in {"create_return", "create_exchange"} and data.get("success"):
                ticket = data.get("ticket") or {}
                as_ctx.ticket_id = ticket.get("ticket_id")
                as_ctx.risk_hold = bool(ticket.get("risk_hold"))
                as_ctx.state = (
                    AfterSalesState.ESCALATED
                    if as_ctx.risk_hold
                    else AfterSalesState.SUBMITTED
                )
                session.entities.pop("confirm", None)
                session.entities.pop("cancel", None)
            if r.get("tool") == "query_after_sales" and data.get("found"):
                as_ctx.state = AfterSalesState.PROCESSING

    async def _route(
        self,
        session: Session,
        intent_id: str,
        intent_result: dict[str, Any],
        message: str,
    ) -> dict[str, Any]:
        """非流式完整处理（内部复用核心逻辑）。"""
        meta = INTENT_META.get(Intent(intent_id), {})
        handler = meta.get("handler", "fallback")

        if handler == "greeting":
            return greeting_response()
        if handler == "handoff":
            session.handoff = True
            return handoff_response()
        if handler == "complaint":
            return {
                "answer": COMPLAINT_ANSWER,
                "handoff": False,
                "risk_flags": ["complaint"],
                "tools": [],
                "sources": [],
            }

        if handler == "after_sales":
            pre = self._after_sales_precheck(session, intent_id, message)
            if pre.get("ask"):
                return {"answer": pre["ask"], "tools": [], "sources": [], "handoff": False, "risk_flags": []}

        tool_names = list(meta.get("tools") or [])
        if handler == "after_sales" and session.after_sales.state == AfterSalesState.CONFIRMING:
            if session.entities.get("confirm"):
                tool_names = self._after_sales_submit_tools(intent_id)
            elif session.entities.get("cancel"):
                session.after_sales.state = AfterSalesState.IDLE
                return {
                    "answer": "已取消本次售后申请。如需再次办理，随时告诉我。",
                    "tools": [],
                    "sources": [],
                    "handoff": False,
                    "risk_flags": [],
                }

        tool_results: list[dict[str, Any]] = []
        if tool_names:
            tools = registry.resolve(tool_names)
            ctx = ToolContext(
                user_id=session.user_id,
                session_id=session.session_id,
                entities=session.entities,
                message=message,
            )
            results = await run_parallel(tools, ctx)
            tool_results = [r.to_dict() for r in results]
            if handler == "after_sales":
                self._after_sales_apply_result(session, intent_id, tool_results)

        sources: list[dict] = []
        knowledge_block = ""
        use_rag = handler in {"rag", "hybrid"} or (
            handler == "tools" and not any(t.get("success") for t in tool_results)
        )
        if handler == "fallback" and session.entities.get("product_kw"):
            use_rag = True

        if use_rag:
            retrieval = await retrieve(message)
            sources = retrieval.get("sources", [])
            knowledge_block = format_sources_block(sources)
            if retrieval.get("low_confidence") and not tool_results:
                return {
                    "answer": LOW_CONF_RAG_ANSWER,
                    "sources": sources,
                    "tools": tool_results,
                    "handoff": False,
                    "risk_flags": ["low_confidence_rag"],
                }

        if handler == "fallback" and not tool_results and not sources:
            return fallback_response()

        # 售后创建成功且带风控，直接返回风控话术（更清晰）
        for r in tool_results:
            data = r.get("data") or {}
            risk = data.get("risk") or {}
            if risk.get("blocked") and risk.get("message"):
                return {
                    "answer": risk["message"],
                    "tools": tool_results,
                    "sources": sources,
                    "handoff": risk.get("require_human", False),
                    "risk_flags": risk.get("flags", []),
                }
            if r.get("tool") in {"create_return", "create_exchange"} and data.get("success"):
                ticket = data.get("ticket") or {}
                kind_label = "退货" if ticket.get("type") == "return" else "换货"
                return {
                    "answer": (
                        f"已为您提交{kind_label}工单 {ticket.get('ticket_id')}，"
                        f"关联订单 {ticket.get('order_id')}。"
                        f"当前状态：{ticket.get('status')}。"
                        f"退款到账后可在「售后进度」中查询，一般 1-3 个工作日。"
                    ),
                    "tools": tool_results,
                    "sources": sources,
                    "handoff": False,
                    "risk_flags": [],
                }

        system = ANSWER_SYSTEM.format(
            intent_name=meta.get("name", intent_id),
            tool_block=format_tool_block(tool_results),
            knowledge_block=knowledge_block or "（无）",
        )
        history = session.as_history_messages()[:-1]
        messages = history + [{"role": "user", "content": message}]
        llm = get_llm()
        try:
            answer = await llm.chat(system=system, messages=messages, temperature=0.3)
            if not answer or not answer.strip():
                answer = template_answer_from_tools(meta.get("name", ""), tool_results)
        except Exception as e:  # noqa: BLE001
            logger.warning("non-stream gen failed: %s", e)
            answer = template_answer_from_tools(meta.get("name", ""), tool_results)

        risk_flags = []
        for r in tool_results:
            data = r.get("data") or {}
            risk_flags.extend((data.get("risk") or {}).get("flags", []))

        return {
            "answer": answer,
            "tools": tool_results,
            "sources": sources,
            "handoff": session.handoff,
            "risk_flags": risk_flags,
        }


orchestrator = Orchestrator()
