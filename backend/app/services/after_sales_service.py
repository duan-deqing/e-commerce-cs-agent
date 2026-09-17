from __future__ import annotations

import time
import uuid
from typing import Any

from app.risk.refund_guard import evaluate_refund_risk
from app.services.order_service import OrderService


class AfterSalesService:
    """售后工单服务：创建退货/换货、查询进度、退款状态。"""

    def __init__(self, order_service: OrderService | None = None) -> None:
        self.orders = order_service or OrderService()
        self._tickets: dict[str, dict[str, Any]] = {}
        self._seed()

    def _seed(self) -> None:
        self._tickets["TK100001"] = {
            "ticket_id": "TK100001",
            "type": "return",
            "order_id": "ORD20260301001",
            "user_id": "u_1001",
            "status": "processing",
            "reason": "尺码不合适",
            "amount": 299.0,
            "refund_status": "pending",
            "risk_hold": False,
            "created_at": "2026-03-02T10:00:00",
            "timeline": [
                {"time": "2026-03-02T10:00:00", "step": "工单创建"},
                {"time": "2026-03-02T12:30:00", "step": "仓库已签收退货包裹"},
            ],
        }

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        return self._tickets.get(ticket_id)

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        return [t for t in self._tickets.values() if t.get("user_id") == user_id]

    def list_by_order(self, order_id: str) -> list[dict[str, Any]]:
        return [t for t in self._tickets.values() if t.get("order_id") == order_id]

    def query_ticket(self, ticket_id: str | None, order_id: str | None = None) -> dict[str, Any]:
        if ticket_id:
            t = self.get(ticket_id)
            if not t:
                return {"found": False, "message": f"未找到工单 {ticket_id}"}
            return {"found": True, "ticket": t}
        if order_id:
            items = self.list_by_order(order_id)
            if not items:
                return {"found": False, "message": f"订单 {order_id} 暂无售后工单"}
            return {"found": True, "tickets": items}
        return {"found": False, "message": "缺少工单号或订单号"}

    def query_refund(self, ticket_id: str | None = None, order_id: str | None = None) -> dict[str, Any]:
        result = self.query_ticket(ticket_id, order_id)
        if not result.get("found"):
            return result
        if "ticket" in result:
            t = result["ticket"]
            return {
                "found": True,
                "ticket_id": t["ticket_id"],
                "refund_status": t.get("refund_status"),
                "amount": t.get("amount"),
                "estimated_days": 1 if t.get("refund_status") == "processing" else 3,
                "message": "退款处理中，预计 1-3 个工作日原路退回",
            }
        tickets = result.get("tickets", [])
        return {"found": True, "refunds": [
            {
                "ticket_id": t["ticket_id"],
                "refund_status": t.get("refund_status"),
                "amount": t.get("amount"),
            }
            for t in tickets
        ]}

    def create_return(
        self,
        order_id: str,
        user_id: str,
        reason: str | None = None,
        amount_hint: float | None = None,
    ) -> dict[str, Any]:
        order = self.orders.get_by_id(order_id)
        if not order:
            return {"success": False, "message": f"订单 {order_id} 不存在，无法创建退货"}
        amount = float(order.get("amount", amount_hint or 0))
        risk = evaluate_refund_risk(amount=amount, user_id=user_id)
        ticket_id = f"TK{uuid.uuid4().hex[:6].upper()}"
        ticket = {
            "ticket_id": ticket_id,
            "type": "return",
            "order_id": order_id,
            "user_id": user_id,
            "status": "risk_hold" if risk.blocked else "submitted",
            "reason": reason or order.get("return_reason") or "未说明",
            "amount": amount,
            "refund_status": "manual_review" if risk.blocked else "pending",
            "risk_hold": risk.blocked,
            "risk_flags": risk.flags,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeline": [
                {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": "退货工单创建"}
            ],
        }
        if risk.blocked:
            ticket["timeline"].append(
                {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": "进入人工风控审核"}
            )
        self._tickets[ticket_id] = ticket
        return {
            "success": True,
            "ticket": ticket,
            "risk": {
                "blocked": risk.blocked,
                "level": risk.risk_level,
                "flags": risk.flags,
                "require_human": risk.require_human,
                "message": risk.message,
            },
        }

    def create_exchange(
        self,
        order_id: str,
        user_id: str,
        variant: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        order = self.orders.get_by_id(order_id)
        if not order:
            return {"success": False, "message": f"订单 {order_id} 不存在，无法创建换货"}
        ticket_id = f"TK{uuid.uuid4().hex[:6].upper()}"
        ticket = {
            "ticket_id": ticket_id,
            "type": "exchange",
            "order_id": order_id,
            "user_id": user_id,
            "status": "submitted",
            "variant": variant or "待确认",
            "reason": reason or "用户申请换货",
            "amount": order.get("amount"),
            "refund_status": None,
            "risk_hold": False,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeline": [
                {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": "换货工单创建"}
            ],
        }
        self._tickets[ticket_id] = ticket
        return {"success": True, "ticket": ticket, "risk": {"blocked": False}}

    def advance(self, ticket_id: str, step: str) -> dict[str, Any] | None:
        t = self._tickets.get(ticket_id)
        if not t:
            return None
        t["timeline"].append({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": step})
        return t
