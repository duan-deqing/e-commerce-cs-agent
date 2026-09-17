from __future__ import annotations

from typing import Any

from app.agent.prompts import FALLBACK_ANSWER, GREETING_ANSWER, HANDOFF_ANSWER


def greeting_response() -> dict[str, Any]:
    return {
        "answer": GREETING_ANSWER,
        "intent": "greeting",
        "sources": [],
        "tools": [],
        "handoff": False,
        "risk_flags": [],
    }


def handoff_response() -> dict[str, Any]:
    return {
        "answer": HANDOFF_ANSWER,
        "intent": "human_handoff",
        "sources": [],
        "tools": [],
        "handoff": True,
        "risk_flags": [],
    }


def fallback_response(clarify: str | None = None) -> dict[str, Any]:
    return {
        "answer": clarify or FALLBACK_ANSWER,
        "intent": "fallback",
        "sources": [],
        "tools": [],
        "handoff": False,
        "risk_flags": [],
    }


def template_answer_from_tools(
    intent_name: str,
    tool_results: list[dict[str, Any]],
) -> str:
    """LLM 故障时的模板化降级回答。"""
    ok = [t for t in tool_results if t.get("success")]
    if not ok:
        return (
            "抱歉，业务系统暂时繁忙，我没能取到实时数据。"
            "您可以稍后重试，或转人工客服协助处理。"
        )
    parts = [f"【{intent_name}】查询结果："]
    for t in ok:
        data = t.get("data") or {}
        if data.get("found") is False:
            parts.append(str(data.get("message", "未查到相关记录")))
            continue
        if "order" in data:
            o = data["order"]
            parts.append(
                f"订单 {o.get('order_id')} 状态：{o.get('status')}，"
                f"金额 ¥{o.get('amount')}，下单时间 {o.get('created_at')}"
            )
        elif "orders" in data:
            parts.append(f"共 {len(data['orders'])} 笔订单，最近一笔：{data['orders'][0].get('order_id')}")
        elif "tracking" in data:
            tinfo = data["tracking"]
            latest = (tinfo.get("trace") or [{}])[-1]
            parts.append(
                f"运单 {tinfo.get('tracking_no')}：{latest.get('desc', tinfo.get('status'))}"
            )
        elif "ticket" in data:
            tk = data["ticket"]
            parts.append(
                f"工单 {tk.get('ticket_id')} 状态：{tk.get('status')}，类型：{tk.get('type')}"
            )
        elif "campaigns" in data:
            names = ", ".join(c.get("name", "") for c in data.get("campaigns", [])[:3])
            parts.append(f"相关活动：{names or '暂无'}")
        else:
            parts.append(str(data)[:300])
    return "\n".join(parts)
