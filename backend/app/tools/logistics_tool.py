from __future__ import annotations

from typing import Any

from app.services.order_service import LogisticsService
from app.tools.base import BaseTool, ToolContext, registry


class QueryLogisticsTool(BaseTool):
    name = "query_logistics"
    description = "查询物流轨迹与预计送达"
    optional_entities = ["tracking_no", "order_id"]

    def __init__(self, service: LogisticsService | None = None) -> None:
        self.service = service or LogisticsService()

    async def run(self, ctx: ToolContext) -> dict[str, Any]:
        return self.service.query(
            tracking_no=ctx.entities.get("tracking_no"),
            order_id=ctx.entities.get("order_id"),
        )


def register_logistics_tools(service: LogisticsService | None = None) -> None:
    registry.register(QueryLogisticsTool(service))
