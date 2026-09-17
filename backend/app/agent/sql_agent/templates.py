"""参数化 SQL 模板目录。

所有业务 SQL 必须先在此登记，运行时仅允许 :param 绑定，禁止拼接用户输入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class SqlTemplate:
    name: str
    description: str
    sql: str
    required: tuple[str, ...] = ()
    optional: dict[str, Any] = field(default_factory=dict)
    mode: Literal["select", "write"] = "select"
    # 写操作是否需要返回 lastrowid / 生成主键
    returns: Literal["rows", "none", "ticket_id"] = "rows"


# ---------------------------------------------------------------------------
# 全部 SQL 均为参数化模板（:param），禁止字符串拼接用户输入
# ---------------------------------------------------------------------------
SQL_TEMPLATES: dict[str, SqlTemplate] = {
    # ---------- 用户 / 订单 ----------
    "get_user": SqlTemplate(
        name="get_user",
        description="按用户 ID 查询用户",
        sql="SELECT user_id, display_name FROM users WHERE user_id = :user_id",
        required=("user_id",),
    ),
    "get_order_by_id": SqlTemplate(
        name="get_order_by_id",
        description="按订单号查询订单主信息",
        sql="""
            SELECT order_id, user_id, status, amount, currency,
                   created_at, payment, receiver_city
            FROM orders
            WHERE order_id = :order_id
        """,
        required=("order_id",),
    ),
    "list_orders_by_user": SqlTemplate(
        name="list_orders_by_user",
        description="按用户查询最近订单",
        sql="""
            SELECT order_id, user_id, status, amount, currency,
                   created_at, payment, receiver_city
            FROM orders
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
        """,
        required=("user_id",),
        optional={"limit": 5},
    ),
    "list_order_items": SqlTemplate(
        name="list_order_items",
        description="查询订单商品明细",
        sql="""
            SELECT product_id, name, sku, qty, price
            FROM order_items
            WHERE order_id = :order_id
        """,
        required=("order_id",),
    ),
    "list_order_items_by_user": SqlTemplate(
        name="list_order_items_by_user",
        description="按用户一次取回全部订单明细（避免 N+1）",
        sql="""
            SELECT oi.order_id, oi.product_id, oi.name, oi.sku, oi.qty, oi.price
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            WHERE o.user_id = :user_id
        """,
        required=("user_id",),
    ),
    # ---------- 物流 ----------
    "get_logistics_by_tracking": SqlTemplate(
        name="get_logistics_by_tracking",
        description="按运单号查询物流主信息",
        sql="""
            SELECT tracking_no, order_id, carrier, status, eta
            FROM logistics_tracks
            WHERE tracking_no = :tracking_no
        """,
        required=("tracking_no",),
    ),
    "get_logistics_by_order": SqlTemplate(
        name="get_logistics_by_order",
        description="按订单号查询关联运单",
        sql="""
            SELECT tracking_no, order_id, carrier, status, eta
            FROM logistics_tracks
            WHERE order_id = :order_id
            LIMIT 1
        """,
        required=("order_id",),
    ),
    "list_logistics_trace": SqlTemplate(
        name="list_logistics_trace",
        description="查询运单轨迹节点",
        sql="""
            SELECT time, desc
            FROM logistics_trace
            WHERE tracking_no = :tracking_no
            ORDER BY time ASC
        """,
        required=("tracking_no",),
    ),
    # ---------- 促销 ----------
    "list_active_promotions": SqlTemplate(
        name="list_active_promotions",
        description="查询进行中的活动",
        sql="""
            SELECT campaign_id, name, status, start, "end",
                   categories_json, tags_json, rules_json
            FROM promotions
            WHERE status = 'active'
            ORDER BY start DESC
        """,
    ),
    "search_promotions": SqlTemplate(
        name="search_promotions",
        description="按关键词模糊搜索活动（名称/标签/规则）",
        sql="""
            SELECT campaign_id, name, status, start, "end",
                   categories_json, tags_json, rules_json
            FROM promotions
            WHERE status = 'active'
              AND (
                    name LIKE :kw
                 OR tags_json LIKE :kw
                 OR rules_json LIKE :kw
                 OR categories_json LIKE :kw
              )
            ORDER BY start DESC
            LIMIT :limit
        """,
        required=("kw",),
        optional={"limit": 10},
    ),
    "search_promotions_by_token": SqlTemplate(
        name="search_promotions_by_token",
        description="按单个短词精确命中标签/名称",
        sql="""
            SELECT campaign_id, name, status, start, "end",
                   categories_json, tags_json, rules_json
            FROM promotions
            WHERE status = 'active'
              AND (
                    name LIKE :token
                 OR tags_json LIKE :token
                 OR rules_json LIKE :token
              )
            ORDER BY start DESC
            LIMIT :limit
        """,
        required=("token",),
        optional={"limit": 10},
    ),
    # ---------- 售后 ----------
    "get_ticket_by_id": SqlTemplate(
        name="get_ticket_by_id",
        description="按工单号查询售后单",
        sql="""
            SELECT ticket_id, type, order_id, user_id, status, reason, variant,
                   amount, refund_status, risk_hold, risk_flags_json, created_at
            FROM after_sales_tickets
            WHERE ticket_id = :ticket_id
        """,
        required=("ticket_id",),
    ),
    "list_tickets_by_order": SqlTemplate(
        name="list_tickets_by_order",
        description="按订单号查询售后工单",
        sql="""
            SELECT ticket_id, type, order_id, user_id, status, reason, variant,
                   amount, refund_status, risk_hold, risk_flags_json, created_at
            FROM after_sales_tickets
            WHERE order_id = :order_id
            ORDER BY created_at DESC
        """,
        required=("order_id",),
    ),
    "list_tickets_by_user": SqlTemplate(
        name="list_tickets_by_user",
        description="按用户查询售后工单",
        sql="""
            SELECT ticket_id, type, order_id, user_id, status, reason, variant,
                   amount, refund_status, risk_hold, risk_flags_json, created_at
            FROM after_sales_tickets
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
        """,
        required=("user_id",),
        optional={"limit": 10},
    ),
    "list_ticket_timeline": SqlTemplate(
        name="list_ticket_timeline",
        description="查询工单时间线",
        sql="""
            SELECT time, step
            FROM after_sales_timeline
            WHERE ticket_id = :ticket_id
            ORDER BY time ASC, id ASC
        """,
        required=("ticket_id",),
    ),
    "insert_ticket": SqlTemplate(
        name="insert_ticket",
        description="创建售后工单",
        sql="""
            INSERT INTO after_sales_tickets(
                ticket_id, type, order_id, user_id, status, reason, variant,
                amount, refund_status, risk_hold, risk_flags_json, created_at
            ) VALUES(
                :ticket_id, :type, :order_id, :user_id, :status, :reason, :variant,
                :amount, :refund_status, :risk_hold, :risk_flags_json, :created_at
            )
        """,
        required=(
            "ticket_id",
            "type",
            "order_id",
            "user_id",
            "status",
            "created_at",
        ),
        optional={
            "reason": None,
            "variant": None,
            "amount": None,
            "refund_status": None,
            "risk_hold": 0,
            "risk_flags_json": "[]",
        },
        mode="write",
        returns="none",
    ),
    "insert_ticket_timeline": SqlTemplate(
        name="insert_ticket_timeline",
        description="写入工单时间线",
        sql="""
            INSERT INTO after_sales_timeline(ticket_id, time, step)
            VALUES(:ticket_id, :time, :step)
        """,
        required=("ticket_id", "time", "step"),
        mode="write",
        returns="none",
    ),
    "update_ticket_status": SqlTemplate(
        name="update_ticket_status",
        description="更新工单状态/风控",
        sql="""
            UPDATE after_sales_tickets
            SET status = :status,
                refund_status = COALESCE(:refund_status, refund_status),
                risk_hold = :risk_hold
            WHERE ticket_id = :ticket_id
        """,
        required=("ticket_id", "status", "risk_hold"),
        optional={"refund_status": None},
        mode="write",
        returns="none",
    ),
}


def get_template(name: str) -> SqlTemplate:
    if name not in SQL_TEMPLATES:
        raise KeyError(f"unknown sql template: {name}")
    return SQL_TEMPLATES[name]


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "mode": t.mode,
            "required": list(t.required),
            "optional": list(t.optional.keys()),
        }
        for t in SQL_TEMPLATES.values()
    ]
