from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass
class RiskDecision:
    blocked: bool
    risk_level: str  # low | medium | high
    reason: str
    flags: list[str]
    require_human: bool
    message: str | None = None


def evaluate_refund_risk(
    amount: float | None,
    user_id: str | None = None,
    recent_refund_count: int = 0,
    complaint_streak: int = 0,
) -> RiskDecision:
    flags: list[str] = []
    risk_level = "low"
    require_human = False
    message = None
    blocked = False

    threshold = settings.refund_risk_threshold

    if amount is not None and amount >= threshold:
        flags.append("high_amount_refund")
        risk_level = "high"
        require_human = True
        blocked = True
        message = (
            f"该笔退款金额 ¥{amount:.2f} 达到风控阈值（¥{threshold:.2f}），"
            "需人工审核后处理。我已为您标记加急工单，请保持电话畅通。"
        )

    if recent_refund_count >= 3:
        flags.append("frequent_refunds")
        if risk_level == "low":
            risk_level = "medium"
        require_human = True

    if complaint_streak >= 2:
        flags.append("complaint_streak")
        if risk_level == "low":
            risk_level = "medium"
        require_human = True

    if user_id and amount is not None and amount >= threshold * 2:
        flags.append("extreme_amount")
        risk_level = "high"

    return RiskDecision(
        blocked=blocked,
        risk_level=risk_level,
        reason=",".join(flags) if flags else "ok",
        flags=flags,
        require_human=require_human,
        message=message,
    )
