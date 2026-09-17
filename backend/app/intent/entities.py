"""从用户消息抽取业务实体（订单号、运单号、金额、原因等）。"""

from __future__ import annotations

import re
from typing import Any

PATTERNS = {
    "order_id": re.compile(
        r"(?:订单号?[:：]?\s*)?((?:ORD|ord)\d{6,}|\d{12,})", re.I
    ),
    "tracking_no": re.compile(
        r"(?:运单号?|快递单号?|物流单号?)[:：]?\s*([A-Z]{0,2}\d{8,})", re.I
    ),
    "ticket_id": re.compile(r"(?:工单号?)[:：]?\s*(TK\d{6,})", re.I),
    "phone": re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)"),
    "amount": re.compile(r"(\d+(?:\.\d{1,2})?)\s*(?:元|块|¥)"),
    "product_kw": re.compile(
        r"(手机|耳机|笔记本|电脑|鞋|衣服|裙子|键盘|手表|充电宝|面膜|水杯)"
    ),
}


def extract_entities(text: str) -> dict[str, Any]:
    entities: dict[str, Any] = {}

    m = PATTERNS["order_id"].search(text)
    if m:
        raw = m.group(1).upper()
        entities["order_id"] = raw if raw.startswith("ORD") else f"ORD{raw}" if raw.isdigit() and len(raw) >= 10 else raw

    m = PATTERNS["tracking_no"].search(text)
    if m:
        entities["tracking_no"] = m.group(1).upper()

    m = PATTERNS["ticket_id"].search(text)
    if m:
        entities["ticket_id"] = m.group(1).upper()

    m = PATTERNS["phone"].search(text)
    if m:
        entities["phone"] = m.group(1)

    m = PATTERNS["amount"].search(text)
    if m:
        entities["amount"] = float(m.group(1))

    m = PATTERNS["product_kw"].search(text)
    if m:
        entities["product_kw"] = m.group(1)

    reason_m = re.search(
        r"(因为|原因(?:是)?|由于)(.{2,40})", text
    )
    if reason_m:
        entities["reason"] = reason_m.group(2).strip("。 ，,!")

    if re.search(r"确认|好的可以|同意|没问题", text):
        entities["confirm"] = True
    if re.search(r"取消|不要了|算了", text):
        entities["cancel"] = True

    return entities


def merge_entities(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for k, v in (new or {}).items():
        if v is None:
            continue
        if k == "confirm" and v:
            merged["confirm"] = True
        elif k == "cancel" and v:
            merged["cancel"] = True
            merged.pop("confirm", None)
        else:
            merged[k] = v
    return merged


# 按意图域保留的实体，切换意图时清理其它域，避免串味
INTENT_ENTITY_SCOPES: dict[str, set[str]] = {
    "order_query": {"order_id"},
    "logistics_query": {"order_id", "tracking_no"},
    "product_inquiry": {"product_kw"},
    "promotion_query": {"product_kw", "keyword"},
    "after_sales_return": {
        "order_id",
        "reason",
        "amount",
        "confirm",
        "cancel",
        "ticket_id",
    },
    "after_sales_exchange": {
        "order_id",
        "reason",
        "variant",
        "product_kw",
        "confirm",
        "cancel",
        "ticket_id",
    },
    "after_sales_progress": {"order_id", "ticket_id"},
    "refund_query": {"order_id", "ticket_id"},
}


def prune_entities_for_intent(
    entities: dict[str, Any],
    prev_intent: str | None,
    intent_id: str,
) -> dict[str, Any]:
    """意图切换时裁剪无关实体；同域或未知意图则原样保留。"""
    if not entities or prev_intent == intent_id:
        return entities
    keep = INTENT_ENTITY_SCOPES.get(intent_id)
    if not keep:
        return entities
    # 售后确认态相关短词始终保留
    preserve = {"confirm", "cancel"}
    return {k: v for k, v in entities.items() if k in keep or k in preserve}

