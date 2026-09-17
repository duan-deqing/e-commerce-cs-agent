from __future__ import annotations

from typing import Any

from app.services.order_service import OrderService
from app.tools.base import BaseTool, ToolContext, registry


class QueryOrderTool(BaseTool):
    name = "query_order"
    description = "查询用户订单状态与明细（按当前用户鉴权）"
    optional_entities = ["order_id"]

    def __init__(self, service: OrderService | None = None) -> None:
        self.service = service or OrderService()

    async def run(self, ctx: ToolContext) -> dict[str, Any]:
        return await self.service.query(
            order_id=ctx.entities.get("order_id"),
            user_id=ctx.user_id,
        )


def register_order_tools(service: OrderService | None = None) -> None:
    registry.register(QueryOrderTool(service))
