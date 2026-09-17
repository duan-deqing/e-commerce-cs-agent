from __future__ import annotations

from enum import Enum


class Intent(str, Enum):
    ORDER_QUERY = "order_query"
    LOGISTICS_QUERY = "logistics_query"
    PRODUCT_INQUIRY = "product_inquiry"
    AFTER_SALES_RETURN = "after_sales_return"
    AFTER_SALES_EXCHANGE = "after_sales_exchange"
    AFTER_SALES_PROGRESS = "after_sales_progress"
    REFUND_QUERY = "refund_query"
    PROMOTION_QUERY = "promotion_query"
    COMPLAINT = "complaint"
    HUMAN_HANDOFF = "human_handoff"
    GREETING = "greeting"
    FALLBACK = "fallback"


INTENT_META: dict[Intent, dict] = {
    Intent.ORDER_QUERY: {
        "name": "订单查询",
        "desc": "查询订单状态、明细、是否发货、能否取消",
        "handler": "tools",
        "tools": ["query_order"],
    },
    Intent.LOGISTICS_QUERY: {
        "name": "物流追踪",
        "desc": "查询快递轨迹、预计送达、异常件",
        "handler": "tools",
        "tools": ["query_logistics"],
    },
    Intent.PRODUCT_INQUIRY: {
        "name": "商品咨询",
        "desc": "商品参数、规格、使用说明、库存相关问答",
        "handler": "rag",
        "tools": [],
    },
    Intent.AFTER_SALES_RETURN: {
        "name": "申请退货",
        "desc": "用户希望退货退款",
        "handler": "after_sales",
        "tools": ["create_return", "query_after_sales"],
        "sm_event": "request_return",
    },
    Intent.AFTER_SALES_EXCHANGE: {
        "name": "申请换货",
        "desc": "用户希望换货/换规格",
        "handler": "after_sales",
        "tools": ["create_exchange", "query_after_sales"],
        "sm_event": "request_exchange",
    },
    Intent.AFTER_SALES_PROGRESS: {
        "name": "售后进度",
        "desc": "查询退换货工单处理进度",
        "handler": "after_sales",
        "tools": ["query_after_sales"],
    },
    Intent.REFUND_QUERY: {
        "name": "退款查询",
        "desc": "查询退款到账时间与状态",
        "handler": "tools",
        "tools": ["query_refund"],
    },
    Intent.PROMOTION_QUERY: {
        "name": "促销活动",
        "desc": "满减、折扣、券、活动规则",
        "handler": "hybrid",
        "tools": ["query_promotion"],
    },
    Intent.COMPLAINT: {
        "name": "投诉",
        "desc": "用户表达不满、差评、投诉倾向",
        "handler": "complaint",
        "tools": [],
    },
    Intent.HUMAN_HANDOFF: {
        "name": "转人工",
        "desc": "用户明确要求人工客服",
        "handler": "handoff",
        "tools": [],
    },
    Intent.GREETING: {
        "name": "寒暄",
        "desc": "打招呼、简单问候",
        "handler": "greeting",
        "tools": [],
    },
    Intent.FALLBACK: {
        "name": "兜底澄清",
        "desc": "意图不明或超出能力范围",
        "handler": "fallback",
        "tools": [],
    },
}


def intent_catalog() -> list[dict]:
    return [
        {
            "intent_id": k.value,
            "name": v["name"],
            "desc": v["desc"],
            "handler": v["handler"],
            "tools": v.get("tools", []),
        }
        for k, v in INTENT_META.items()
    ]
