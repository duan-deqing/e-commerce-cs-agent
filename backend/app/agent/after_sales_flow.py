from __future__ import annotations

from typing import Any

from app.intent.labels import Intent
from app.state.session import AfterSalesState, Session

CANCEL_ANSWER = "已取消本次售后申请。如需再次办理，随时告诉我。"


def precheck(session: Session, intent_id: str) -> dict[str, Any]:
    """缺参追问 / 进入确认态。返回 {"ask": str} 或 {}。"""
    as_ctx = session.after_sales
    ent = session.entities

    if intent_id in {Intent.AFTER_SALES_PROGRESS.value, Intent.REFUND_QUERY.value}:
        if not ent.get("ticket_id") and not ent.get("order_id"):
            return {"ask": "请提供售后工单号（TK 开头）或关联订单号，我帮您查询进度。"}
        return {}

    if intent_id not in {Intent.AFTER_SALES_RETURN.value, Intent.AFTER_SALES_EXCHANGE.value}:
        return {}

    kind = "return" if intent_id == Intent.AFTER_SALES_RETURN.value else "exchange"

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


def resolve_tools(session: Session, intent_id: str, default_tools: list[str]) -> tuple[list[str], dict[str, Any] | None]:
    """确认态下决定实际调用的工具；取消则返回终止 payload。"""
    if session.after_sales.state != AfterSalesState.CONFIRMING:
        return list(default_tools), None

    if session.entities.get("confirm"):
        return submit_tools(intent_id), None

    if session.entities.get("cancel"):
        session.after_sales.state = AfterSalesState.IDLE
        return [], {
            "answer": CANCEL_ANSWER,
            "tools": [],
            "sources": [],
            "handoff": False,
            "risk_flags": [],
        }

    return list(default_tools), None


def submit_tools(intent_id: str) -> list[str]:
    if intent_id == Intent.AFTER_SALES_RETURN.value:
        return ["create_return"]
    if intent_id == Intent.AFTER_SALES_EXCHANGE.value:
        return ["create_exchange"]
    return ["query_after_sales"]


def apply_result(session: Session, tool_results: list[dict[str, Any]]) -> None:
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


def short_circuit_payload(
    tool_results: list[dict[str, Any]],
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """风控拦截 / 建单成功：确定性话术，跳过通用 LLM 生成。"""
    sources = sources or []
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
    return None


def collect_risk_flags(tool_results: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    for r in tool_results:
        data = r.get("data") or {}
        flags.extend((data.get("risk") or {}).get("flags", []))
    return flags
