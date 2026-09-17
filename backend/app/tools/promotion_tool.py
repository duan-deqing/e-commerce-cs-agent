from __future__ import annotations

from typing import Any

from app.services.order_service import PromotionService
from app.tools.base import BaseTool, ToolContext, registry


class QueryPromotionTool(BaseTool):
    name = "query_promotion"
    description = "查询促销活动与优惠规则"
    optional_entities = ["product_kw", "keyword"]

    def __init__(self, service: PromotionService | None = None) -> None:
        self.service = service or PromotionService()

    async def run(self, ctx: ToolContext) -> dict[str, Any]:
        keyword = (
            ctx.entities.get("keyword")
            or ctx.entities.get("product_kw")
            or (ctx.message[:12] if ctx.message else None)
        )
        return await self.service.query(keyword=keyword)


def register_promotion_tools(service: PromotionService | None = None) -> None:
    registry.register(QueryPromotionTool(service))
