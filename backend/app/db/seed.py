"""演示数据 Seed：首次启动或 force 时写入 SQLite。"""

from __future__ import annotations

import json

from app.db.connection import get_connection, init_db
from app.core.logging import get_logger

logger = get_logger(__name__)

SEED_ORDERS = [
    {
        "order_id": "ORD20260301001",
        "user_id": "u_1001",
        "status": "已发货",
        "amount": 299.0,
        "currency": "CNY",
        "created_at": "2026-03-01T14:22:00",
        "payment": "微信支付",
        "receiver_city": "上海市",
        "items": [
            {
                "product_id": "P_SHOE_001",
                "name": "轻量跑步鞋",
                "sku": "黑色/42",
                "qty": 1,
                "price": 299.0,
            }
        ],
    },
    {
        "order_id": "ORD20260228015",
        "user_id": "u_1001",
        "status": "已签收",
        "amount": 1299.0,
        "currency": "CNY",
        "created_at": "2026-02-28T09:10:00",
        "payment": "支付宝",
        "receiver_city": "杭州市",
        "items": [
            {
                "product_id": "P_PHONE_002",
                "name": "星环智能手机 12+256G",
                "sku": "深空灰",
                "qty": 1,
                "price": 1299.0,
            }
        ],
    },
    {
        "order_id": "ORD20260305008",
        "user_id": "u_1002",
        "status": "待付款",
        "amount": 59.9,
        "currency": "CNY",
        "created_at": "2026-03-05T20:01:00",
        "payment": "未支付",
        "receiver_city": "北京市",
        "items": [
            {
                "product_id": "P_CUP_003",
                "name": "保温杯 500ml",
                "sku": "奶油白",
                "qty": 1,
                "price": 59.9,
            }
        ],
    },
    {
        "order_id": "ORD20260310003",
        "user_id": "u_1003",
        "status": "已发货",
        "amount": 2599.0,
        "currency": "CNY",
        "created_at": "2026-03-10T11:30:00",
        "payment": "银行卡",
        "receiver_city": "深圳市",
        "items": [
            {
                "product_id": "P_LAPTOP_004",
                "name": "极光轻薄本 16G/512G",
                "sku": "银色",
                "qty": 1,
                "price": 2599.0,
            }
        ],
    },
]

SEED_LOGISTICS = [
    {
        "tracking_no": "YT1234567890",
        "order_id": "ORD20260301001",
        "carrier": "圆通速递",
        "status": "运输中",
        "eta": "2026-03-12",
        "trace": [
            {"time": "2026-03-01T18:00:00", "desc": "商家已发货"},
            {"time": "2026-03-02T08:20:00", "desc": "上海转运中心已发出"},
            {"time": "2026-03-03T21:15:00", "desc": "到达目的地分拨中心"},
            {"time": "2026-03-04T09:00:00", "desc": "快递员正在派送"},
        ],
    },
    {
        "tracking_no": "SF9876543210",
        "order_id": "ORD20260228015",
        "carrier": "顺丰速运",
        "status": "已签收",
        "eta": "2026-03-01",
        "trace": [
            {"time": "2026-02-28T12:00:00", "desc": "商家已发货"},
            {"time": "2026-03-01T10:30:00", "desc": "已签收，签收人：本人"},
        ],
    },
    {
        "tracking_no": "JD5566778899",
        "order_id": "ORD20260310003",
        "carrier": "京东物流",
        "status": "运输中",
        "eta": "2026-03-13",
        "trace": [
            {"time": "2026-03-10T16:00:00", "desc": "商家已发货"},
            {"time": "2026-03-11T07:40:00", "desc": "深圳分拣中心已发出"},
        ],
    },
]

SEED_PROMOTIONS = [
    {
        "campaign_id": "CAMP_618_2026",
        "name": "618 年中大促",
        "status": "active",
        "start": "2026-06-01",
        "end": "2026-06-20",
        "categories": ["数码", "服饰", "家居"],
        "tags": ["618", "满减", "数码"],
        "rules": [
            "全场满 300 减 50，满 800 减 120",
            "指定手机品类满 1500 减 200",
            "优惠券可与店铺券叠加，不可与秒杀叠加",
        ],
    },
    {
        "campaign_id": "CAMP_NEWUSER",
        "name": "新人专享券",
        "status": "active",
        "start": "2026-01-01",
        "end": "2026-12-31",
        "categories": ["全类目"],
        "tags": ["新人", "优惠券"],
        "rules": [
            "新注册用户可领 20 元无门槛券",
            "有效期 7 天，每账号限领一次",
        ],
    },
    {
        "campaign_id": "CAMP_SHOE_SPRING",
        "name": "春季鞋服焕新",
        "status": "active",
        "start": "2026-03-01",
        "end": "2026-03-31",
        "categories": ["服饰", "鞋靴"],
        "tags": ["鞋", "换季", "折扣"],
        "rules": [
            "鞋靴专区 8.5 折起",
            "两件再享 9 折",
        ],
    },
]

SEED_TICKETS = [
    {
        "ticket_id": "TK100001",
        "type": "return",
        "order_id": "ORD20260301001",
        "user_id": "u_1001",
        "status": "processing",
        "reason": "尺码不合适",
        "variant": None,
        "amount": 299.0,
        "refund_status": "pending",
        "risk_hold": False,
        "risk_flags": [],
        "created_at": "2026-03-02T10:00:00",
        "timeline": [
            {"time": "2026-03-02T10:00:00", "step": "工单创建"},
            {"time": "2026-03-02T12:30:00", "step": "仓库已签收退货包裹"},
        ],
    }
]


def seed_if_empty(force: bool = False) -> None:
    """首次启动写入演示数据。force=True 时清空后重灌。"""
    init_db()
    conn = get_connection()
    with conn:
        if force:
            for table in (
                "after_sales_timeline",
                "after_sales_tickets",
                "logistics_trace",
                "logistics_tracks",
                "order_items",
                "orders",
                "promotions",
                "users",
            ):
                conn.execute(f"DELETE FROM {table}")

        cur = conn.execute("SELECT COUNT(*) AS c FROM orders")
        if cur.fetchone()["c"] > 0 and not force:
            logger.info("DB already seeded, skip")
            return

        users = sorted({o["user_id"] for o in SEED_ORDERS} | {t["user_id"] for t in SEED_TICKETS if t.get("user_id")})
        for uid in users:
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id, display_name) VALUES(?, ?)",
                (uid, f"用户{uid[-4:]}"),
            )

        for o in SEED_ORDERS:
            conn.execute(
                """
                INSERT OR REPLACE INTO orders(
                    order_id, user_id, status, amount, currency, created_at, payment, receiver_city
                ) VALUES(:order_id, :user_id, :status, :amount, :currency, :created_at, :payment, :receiver_city)
                """,
                o,
            )
            for item in o.get("items", []):
                conn.execute(
                    """
                    INSERT INTO order_items(order_id, product_id, name, sku, qty, price)
                    VALUES(:order_id, :product_id, :name, :sku, :qty, :price)
                    """,
                    {**item, "order_id": o["order_id"]},
                )

        for t in SEED_LOGISTICS:
            conn.execute(
                """
                INSERT OR REPLACE INTO logistics_tracks(tracking_no, order_id, carrier, status, eta)
                VALUES(:tracking_no, :order_id, :carrier, :status, :eta)
                """,
                {k: t[k] for k in ("tracking_no", "order_id", "carrier", "status", "eta")},
            )
            for tr in t.get("trace", []):
                conn.execute(
                    "INSERT INTO logistics_trace(tracking_no, time, desc) VALUES(?, ?, ?)",
                    (t["tracking_no"], tr["time"], tr["desc"]),
                )

        for p in SEED_PROMOTIONS:
            conn.execute(
                """
                INSERT OR REPLACE INTO promotions(
                    campaign_id, name, status, start, "end",
                    categories_json, tags_json, rules_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p["campaign_id"],
                    p["name"],
                    p["status"],
                    p["start"],
                    p["end"],
                    json.dumps(p.get("categories", []), ensure_ascii=False),
                    json.dumps(p.get("tags", []), ensure_ascii=False),
                    json.dumps(p.get("rules", []), ensure_ascii=False),
                ),
            )

        for tk in SEED_TICKETS:
            conn.execute(
                """
                INSERT OR REPLACE INTO after_sales_tickets(
                    ticket_id, type, order_id, user_id, status, reason, variant,
                    amount, refund_status, risk_hold, risk_flags_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tk["ticket_id"],
                    tk["type"],
                    tk["order_id"],
                    tk["user_id"],
                    tk["status"],
                    tk["reason"],
                    tk.get("variant"),
                    tk["amount"],
                    tk["refund_status"],
                    1 if tk.get("risk_hold") else 0,
                    json.dumps(tk.get("risk_flags", []), ensure_ascii=False),
                    tk["created_at"],
                ),
            )
            for ev in tk.get("timeline", []):
                conn.execute(
                    "INSERT INTO after_sales_timeline(ticket_id, time, step) VALUES(?, ?, ?)",
                    (tk["ticket_id"], ev["time"], ev["step"]),
                )

        logger.info("DB seeded: orders=%s logistics=%s promotions=%s tickets=%s",
                    len(SEED_ORDERS), len(SEED_LOGISTICS), len(SEED_PROMOTIONS), len(SEED_TICKETS))
