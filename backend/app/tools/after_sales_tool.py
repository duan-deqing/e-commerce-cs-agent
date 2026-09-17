from __future__ import annotations

from typing import Any

from app.services.after_sales_service import AfterSalesService
from app.tools.base import BaseTool, ToolContext, registry


class CreateReturnTool(BaseTool):
    name = "create_return"
    description = "创建退货售后工单"
    required_entities = ["order_id"]

    def __init__(self, service: AfterSalesService | None = None) -> None:
        self.service = service or AfterSalesService()

    async def run(self, ctx: ToolContext) -> dict[str, Any]:
        return self.service.create_return(
            order_id=str(ctx.entities.get("order_id")),
            user_id=ctx.user_id,
            reason=ctx.entities.get("reason"),
            amount_hint=ctx.entities.get("amount"),
        )


class CreateExchangeTool(BaseTool):
    name = "create_exchange"
    description = "创建换货售后工单"
    required_entities = ["order_id"]

    def __init__(self, service: AfterSalesService | None = None) -> None:
        self.service = service or AfterSalesService()

    async def run(self, ctx: ToolContext) -> dict[str, Any]:
        return self.service.create_exchange(
            order_id=str(ctx.entities.get("order_id")),
            user_id=ctx.user_id,
            variant=ctx.entities.get("variant") or ctx.entities.get("product_kw"),
            reason=ctx.entities.get("reason"),
        )


class QueryAfterSalesTool(BaseTool):
    name = "query_after_sales"
    description = "查询售后工单进度"
    optional_entities = ["ticket_id", "order_id"]

    def __init__(self, service: AfterSalesService | None = None) -> None:
        self.service = service or AfterSalesService()

    async def run(self, ctx: ToolContext) -> dict[str, Any]:
        return self.service.query_ticket(
            ticket_id=ctx.entities.get("ticket_id"),
            order_id=ctx.entities.get("order_id"),
        )


class QueryRefundTool(BaseTool):
    name = "query_refund"
    description = "查询退款进度"
    optional_entities = ["ticket_id", "order_id"]

    def __init__(self, service: AfterSalesService | None = None) -> None:
        self.service = service or AfterSalesService()

    async def run(self, ctx: ToolContext) -> dict[str, Any]:
        return self.service.query_refund(
            ticket_id=ctx.entities.get("ticket_id"),
            order_id=ctx.entities.get("order_id"),
        )


def register_after_sales_tools(service: AfterSalesService | None = None) -> None:
    svc = service or AfterSalesService()
    registry.register(CreateReturnTool(svc))
    registry.register(CreateExchangeTool(svc))
    registry.register(QueryAfterSalesTool(svc))
    registry.register(QueryRefundTool(svc))
