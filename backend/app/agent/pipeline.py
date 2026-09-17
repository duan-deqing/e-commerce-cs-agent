"""统一对话流水线（流式 / 非流式共用）。

顺序：快捷回复 → 售后预检 → 工具并行 → RAG → LLM 生成。
emit 非空时会向外推送 tool/token/sources 等事件（供 SSE）。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.agent import after_sales_flow as asf
from app.agent.fallback import (
    fallback_response,
    greeting_response,
    handoff_response,
    template_answer_from_tools,
)
from app.agent.prompts import (
    COMPLAINT_ANSWER,
    LOW_CONF_RAG_ANSWER,
    PROMPT_VERSIONS,
    build_answer_system,
    format_sources_block,
    format_tool_block,
    resolve_prompt_version,
)
from app.core.config import settings
from app.core.llm import get_llm
from app.core.logging import get_logger
from app.intent.labels import INTENT_META, Intent
from app.rag.chain import retrieve
from app.risk.masker import mask_sensitive
from app.state.session import Session
from app.tools.base import ToolContext, registry, run_parallel

logger = get_logger(__name__)

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]

# 最大工具调用数护栏：单请求工具数上限，防止意图误路由触发工具风暴
MAX_TOOL_CALLS_PER_REQUEST = 4


async def _emit(emit: EmitFn | None, event: str, data: dict[str, Any]) -> None:
    if emit is not None:
        await emit(event, data)


def _payload(answer: str, **kwargs: Any) -> dict[str, Any]:
    base = {
        "answer": answer,
        "tools": [],
        "sources": [],
        "handoff": False,
        "risk_flags": [],
    }
    base.update(kwargs)
    return base


async def _early(
    payload: dict[str, Any],
    emit: EmitFn | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """快捷/短路回复：流式时补发完整 answer 作为 token。"""
    answer = payload.get("answer", "")
    if emit is not None and answer:
        await _emit(emit, "token", {"token": answer})
    if session is not None:
        payload["answer"] = mask_sensitive(answer)
    return payload


def _should_use_rag(
    handler: str,
    session: Session,
    tool_results: list[dict[str, Any]],
) -> bool:
    if handler in {"rag", "hybrid"}:
        return True
    if handler == "tools" and not any(t.get("success") for t in tool_results):
        return True
    if handler == "fallback" and session.entities.get("product_kw"):
        return True
    return False


async def run_tools(
    session: Session,
    tool_names: list[str],
    message: str,
    emit: EmitFn | None = None,
) -> list[dict[str, Any]]:
    if not tool_names:
        return []
    if len(tool_names) > MAX_TOOL_CALLS_PER_REQUEST:
        logger.warning(
            "tool calls capped: %d -> %d", len(tool_names), MAX_TOOL_CALLS_PER_REQUEST
        )
        tool_names = tool_names[:MAX_TOOL_CALLS_PER_REQUEST]
    tools = registry.resolve(tool_names)
    ctx = ToolContext(
        user_id=session.user_id,
        session_id=session.session_id,
        entities=session.entities,
        message=message,
    )
    for t in tools:
        await _emit(emit, "tool_start", {"tool": t.name})
    results = await run_parallel(tools, ctx)
    tool_results: list[dict[str, Any]] = []
    for r in results:
        d = r.to_dict()
        tool_results.append(d)
        await _emit(emit, "tool_result", d)
    return tool_results


async def run_rag(
    message: str,
    tool_results: list[dict[str, Any]],
    emit: EmitFn | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """返回 (knowledge_block, sources, early_payload|None)。"""
    retrieval = await retrieve(message)
    sources = retrieval.get("sources", [])
    if sources:
        await _emit(emit, "sources", {"sources": sources})
    knowledge_block = format_sources_block(sources)
    if retrieval.get("low_confidence") and not tool_results:
        return knowledge_block, sources, _payload(
            LOW_CONF_RAG_ANSWER,
            sources=sources,
            tools=tool_results,
            risk_flags=["low_confidence_rag"],
        )
    return knowledge_block, sources, None


async def generate_answer(
    session: Session,
    intent_id: str,
    meta: dict[str, Any],
    message: str,
    tool_results: list[dict[str, Any]],
    knowledge_block: str,
    stream: bool = False,
    emit: EmitFn | None = None,
    usage_out: dict[str, Any] | None = None,
) -> str:
    # 灰度路由：按 session 稳定哈希选 prompt 版本，版本随 usage 透传到 trace
    version = resolve_prompt_version(session.session_id)
    system = build_answer_system(
        intent_name=meta.get("name", intent_id),
        tool_block=format_tool_block(tool_results),
        knowledge_block=knowledge_block,
        rules=PROMPT_VERSIONS.get(version),
    )
    if usage_out is not None:
        usage_out["prompt_version"] = version
    history = session.as_history_messages()[:-1]
    messages = history + [{"role": "user", "content": message}]
    llm = get_llm()
    max_tokens = settings.max_output_tokens

    if stream:
        parts: list[str] = []
        try:
            async for chunk in llm.chat_stream(
                system=system,
                messages=messages,
                temperature=0.3,
                max_tokens=max_tokens,
                usage_out=usage_out,
            ):
                if chunk.kind == "reasoning":
                    # 思考增量透出到执行过程面板，不进入回答正文与历史
                    await _emit(emit, "reasoning", {"text": chunk.text})
                    continue
                parts.append(chunk.text)
                await _emit(emit, "token", {"token": chunk.text})
            answer = "".join(parts).strip()
            if not answer:
                answer = template_answer_from_tools(meta.get("name", ""), tool_results)
                await _emit(emit, "token", {"token": answer})
        except Exception as e:  # noqa: BLE001
            logger.warning("stream gen failed: %s", e)
            answer = template_answer_from_tools(meta.get("name", ""), tool_results)
            await _emit(emit, "token", {"token": answer})
        return answer

    try:
        answer = await llm.chat(
            system=system,
            messages=messages,
            temperature=0.3,
            max_tokens=max_tokens,
            usage_out=usage_out,
        )
        if not answer or not answer.strip():
            answer = template_answer_from_tools(meta.get("name", ""), tool_results)
    except Exception as e:  # noqa: BLE001
        logger.warning("non-stream gen failed: %s", e)
        answer = template_answer_from_tools(meta.get("name", ""), tool_results)
    return answer


async def run_pipeline(
    session: Session,
    message: str,
    intent_id: str,
    emit: EmitFn | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """意图之后的主流程；返回 payload，含 answer/tools/sources/handoff/usage。"""
    usage_out: dict[str, Any] = {}
    try:
        intent_enum = Intent(intent_id)
        meta = INTENT_META.get(intent_enum, {})
    except ValueError:
        logger.warning("unknown intent_id in pipeline: %s", intent_id)
        meta = {}
    handler = meta.get("handler", "fallback")

    if handler == "greeting":
        return await _early(greeting_response(), emit, session)
    if handler == "handoff":
        session.handoff = True
        return await _early(handoff_response(), emit, session)
    if handler == "complaint":
        return await _early(_payload(COMPLAINT_ANSWER, risk_flags=["complaint"]), emit, session)

    if handler == "after_sales":
        pre = asf.precheck(session, intent_id)
        if pre.get("ask"):
            return await _early(_payload(pre["ask"]), emit, session)

    default_tools = list(meta.get("tools") or [])
    tool_names = default_tools
    if handler == "after_sales":
        tool_names, cancel_payload = asf.resolve_tools(session, intent_id, default_tools)
        if cancel_payload is not None:
            return await _early(cancel_payload, emit, session)

    tool_results: list[dict[str, Any]] = []
    if tool_names:
        tool_results = await run_tools(session, tool_names, message, emit=emit)
        if handler == "after_sales":
            asf.apply_result(session, tool_results)
            short = asf.short_circuit_payload(tool_results)
            if short is not None:
                return await _early(short, emit, session)

    sources: list[dict[str, Any]] = []
    knowledge_block = ""
    if _should_use_rag(handler, session, tool_results):
        knowledge_block, sources, early = await run_rag(message, tool_results, emit=emit)
        if early is not None:
            return await _early(early, emit, session)

    if handler == "fallback" and not tool_results and not sources:
        return await _early(fallback_response(), emit, session)

    answer = await generate_answer(
        session=session,
        intent_id=intent_id,
        meta=meta,
        message=message,
        tool_results=tool_results,
        knowledge_block=knowledge_block,
        stream=stream,
        emit=emit,
        usage_out=usage_out,
    )
    answer = mask_sensitive(answer)

    return {
        "answer": answer,
        "tools": tool_results,
        "sources": sources,
        "handoff": session.handoff,
        "risk_flags": asf.collect_risk_flags(tool_results),
        "usage": usage_out,
    }
