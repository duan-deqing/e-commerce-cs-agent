from __future__ import annotations

from app.services.after_sales_service import AfterSalesService
from app.services.order_service import LogisticsService, OrderService, PromotionService
from app.tools.after_sales_tool import register_after_sales_tools
from app.tools.base import registry
from app.tools.logistics_tool import register_logistics_tools
from app.tools.order_tool import register_order_tools
from app.tools.promotion_tool import register_promotion_tools
from app.tools.search_tool import register_search_tools


def bootstrap_tools() -> None:
    """注册全部业务工具（幂等）。"""
    order_svc = OrderService()
    logistics_svc = LogisticsService()
    promo_svc = PromotionService()
    after_svc = AfterSalesService(order_svc)

    registry.clear()
    register_order_tools(order_svc)
    register_logistics_tools(logistics_svc)
    register_after_sales_tools(after_svc)
    register_promotion_tools(promo_svc)
    register_search_tools()


__all__ = ["bootstrap_tools", "registry"]
