"""售后工单服务：创建退换货、查询进度，写库经 SQL Agent 模板。"""

from __future__ import annotations

import time
import uuid
from typing import Any

from app.risk.refund_guard import evaluate_refund_risk
from app.services.order_service import OrderService
from app.agent.sql_agent.agent import dumps_list, loads_list, sql_agent


def _map_ticket(row: dict[str, Any], timeline: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = dict(row)
    data["risk_hold"] = bool(data.get("risk_hold"))
    data["risk_flags"] = loads_list(data.pop("risk_flags_json", None))
    if timeline is not None:
        data["timeline"] = timeline
    return data


class AfterSalesService:
    """售后工单服务：SQL 模板落库 + 业务规则。"""

    def __init__(self, order_service: OrderService | None = None) -> None:
        self.orders = order_service or OrderService()

    async def get(self, ticket_id: str) -> dict[str, Any] | None:
        row = await sql_agent.query_one("get_ticket_by_id", {"ticket_id": ticket_id})
        if not row:
            return None
        timeline = await sql_agent.query_all("list_ticket_timeline", {"ticket_id": ticket_id})
        return _map_ticket(row, [dict(t) for t in timeline])

    async def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = await sql_agent.query_all("list_tickets_by_user", {"user_id": user_id, "limit": 20})
        return [_map_ticket(r) for r in rows]

    async def list_by_order(self, order_id: str) -> list[dict[str, Any]]:
        rows = await sql_agent.query_all("list_tickets_by_order", {"order_id": order_id})
        return [_map_ticket(r) for r in rows]

    async def query_ticket(
        self, ticket_id: str | None, order_id: str | None = None
    ) -> dict[str, Any]:
        if ticket_id:
            t = await self.get(ticket_id)
            if not t:
                return {"found": False, "message": f"未找到工单 {ticket_id}"}
            return {"found": True, "ticket": t}
        if order_id:
            items = await self.list_by_order(order_id)
            if not items:
                return {"found": False, "message": f"订单 {order_id} 暂无售后工单"}
            return {"found": True, "tickets": items}
        return {"found": False, "message": "缺少工单号或订单号"}

    async def query_refund(
        self, ticket_id: str | None = None, order_id: str | None = None
    ) -> dict[str, Any]:
        result = await self.query_ticket(ticket_id, order_id)
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
        return {
            "found": True,
            "refunds": [
                {
                    "ticket_id": t["ticket_id"],
                    "refund_status": t.get("refund_status"),
                    "amount": t.get("amount"),
                }
                for t in tickets
            ],
        }

    async def create_return(
        self,
        order_id: str,
        user_id: str,
        reason: str | None = None,
        amount_hint: float | None = None,
    ) -> dict[str, Any]:
        order = await self.orders.get_by_id(order_id, user_id=user_id)
        if not order:
            return {"success": False, "message": f"订单 {order_id} 不存在或无权操作，无法创建退货"}
        amount = float(order.get("amount", amount_hint or 0))
        risk = evaluate_refund_risk(amount=amount, user_id=user_id)
        ticket_id = f"TK{uuid.uuid4().hex[:6].upper()}"
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        status = "risk_hold" if risk.blocked else "submitted"
        refund_status = "manual_review" if risk.blocked else "pending"

        await sql_agent.write(
            "insert_ticket",
            {
                "ticket_id": ticket_id,
                "type": "return",
                "order_id": order_id,
                "user_id": user_id,
                "status": status,
                "reason": reason or order.get("return_reason") or "未说明",
                "variant": None,
                "amount": amount,
                "refund_status": refund_status,
                "risk_hold": 1 if risk.blocked else 0,
                "risk_flags_json": dumps_list(risk.flags),
                "created_at": now,
            },
        )
        await sql_agent.write(
            "insert_ticket_timeline",
            {"ticket_id": ticket_id, "time": now, "step": "退货工单创建"},
        )
        if risk.blocked:
            await sql_agent.write(
                "insert_ticket_timeline",
                {"ticket_id": ticket_id, "time": now, "step": "进入人工风控审核"},
            )

        ticket = await self.get(ticket_id)
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

    async def create_exchange(
        self,
        order_id: str,
        user_id: str,
        variant: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        order = await self.orders.get_by_id(order_id, user_id=user_id)
        if not order:
            return {"success": False, "message": f"订单 {order_id} 不存在或无权操作，无法创建换货"}
        ticket_id = f"TK{uuid.uuid4().hex[:6].upper()}"
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        await sql_agent.write(
            "insert_ticket",
            {
                "ticket_id": ticket_id,
                "type": "exchange",
                "order_id": order_id,
                "user_id": user_id,
                "status": "submitted",
                "reason": reason or "用户申请换货",
                "variant": variant or "待确认",
                "amount": order.get("amount"),
                "refund_status": None,
                "risk_hold": 0,
                "risk_flags_json": "[]",
                "created_at": now,
            },
        )
        await sql_agent.write(
            "insert_ticket_timeline",
            {"ticket_id": ticket_id, "time": now, "step": "换货工单创建"},
        )
        ticket = await self.get(ticket_id)
        return {"success": True, "ticket": ticket, "risk": {"blocked": False}}

    async def advance(self, ticket_id: str, step: str) -> dict[str, Any] | None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        await sql_agent.write(
            "insert_ticket_timeline",
            {"ticket_id": ticket_id, "time": now, "step": step},
        )
        return await self.get(ticket_id)
