"""会话连续性：售后确认态下的「确认/取消」继承上一轮意图。"""

from __future__ import annotations

import re
from typing import Any

from app.intent.labels import Intent
from app.state.session import AfterSalesState, Session

CONFIRM_RE = re.compile(r"确认|好的可以|同意|没问题|提交|可以的?|^ok$|^好的$|就这个", re.I)
CANCEL_RE = re.compile(r"取消|不要了|算了|先不用|不退了", re.I)


def apply_session_continuity(
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
