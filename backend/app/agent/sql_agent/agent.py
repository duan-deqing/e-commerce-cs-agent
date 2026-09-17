from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.db.connection import db_lock, get_connection
from app.agent.sql_agent.templates import SQL_TEMPLATES, SqlTemplate, get_template, list_templates

logger = get_logger(__name__)

# 业务动作 → 模板路由（确定性优先，LLM 只做模板选择，绝不生成 SQL）
ACTION_ROUTES: dict[str, str] = {
    "order.by_id": "get_order_by_id",
    "order.by_user": "list_orders_by_user",
    "order.items": "list_order_items",
    "logistics.by_tracking": "get_logistics_by_tracking",
    "logistics.by_order": "get_logistics_by_order",
    "logistics.trace": "list_logistics_trace",
    "promotion.search": "search_promotions",
    "promotion.active": "list_active_promotions",
    "ticket.by_id": "get_ticket_by_id",
    "ticket.by_order": "list_tickets_by_order",
    "ticket.by_user": "list_tickets_by_user",
    "ticket.timeline": "list_ticket_timeline",
    "ticket.create": "insert_ticket",
    "ticket.append_timeline": "insert_ticket_timeline",
    "ticket.update_status": "update_ticket_status",
}

# 工具层默认动作仅作文档参考；实际分支在 services / resolve_action



@dataclass
class SqlResult:
    template: str
    sql: str
    rows: list[dict[str, Any]]
    rowcount: int
    latency_ms: float
    params: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "rowcount": self.rowcount,
            "latency_ms": self.latency_ms,
            # 默认不回显 SQL 与完整 params，避免泄露；调试可开
            "rows_preview": self.rows[:3],
        }


class SqlAgent:
    """模板化 SQL Agent。

    安全约束：
    1. 只允许执行 SQL_TEMPLATES 中登记的模板
    2. 一律使用 sqlite 命名参数绑定，禁止 f-string 拼 SQL
    3. LLM（若启用）只输出 template_name + params 的 JSON，不生成 SQL 文本
    """

    def __init__(self) -> None:
        self._llm_selector_enabled = False  # 预留：用 LLM 选模板

    # ----- 执行 -----
    async def execute(
        self,
        template_name: str,
        params: dict[str, Any] | None = None,
    ) -> SqlResult:
        """执行已登记模板；SQL 在线程池跑，避免阻塞事件循环。"""
        tpl = get_template(template_name)
        bound = self._bind_params(tpl, params or {})
        sql = self._normalize_sql(tpl.sql)
        start = time.perf_counter()

        def _run() -> tuple[list[dict[str, Any]], int]:
            conn = get_connection()
            # 读操作不加全局锁（WAL 多读安全）；仅写串行，避免写冲突
            if tpl.mode == "select":
                cur = conn.execute(sql, bound)
                rows = [dict(r) for r in cur.fetchall()]
                return rows, len(rows)
            with db_lock():
                cur = conn.execute(sql, bound)
                conn.commit()
                rc = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
                return [], rc

        rows, rowcount = await asyncio.to_thread(_run)
        latency = (time.perf_counter() - start) * 1000
        safe_params = {k: bound.get(k) for k in tpl.required}
        logger.debug("sql_agent exec %s rows=%s %.1fms", template_name, rowcount, latency)
        return SqlResult(
            template=template_name,
            sql=sql,
            rows=rows,
            rowcount=rowcount,
            latency_ms=round(latency, 2),
            params=safe_params,
        )

    async def query_one(self, template_name: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        result = await self.execute(template_name, params)
        return result.rows[0] if result.rows else None

    async def query_all(self, template_name: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = await self.execute(template_name, params)
        return result.rows

    async def write(self, template_name: str, params: dict[str, Any] | None = None) -> SqlResult:
        return await self.execute(template_name, params)

    # ----- 路由（业务动作 → 模板）-----
    def resolve_action(
        self,
        action: str,
        entities: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """业务动作 + 实体 → (模板名, 参数)。

        例：物流优先 tracking_no，否则回退 order_id；不生成 SQL 文本。
        """
        entities = entities or {}

        if action == "order.lookup":
            if entities.get("order_id"):
                return "get_order_by_id", {"order_id": entities["order_id"]}
            if entities.get("user_id"):
                return "list_orders_by_user", {
                    "user_id": entities["user_id"],
                    "limit": entities.get("limit", 5),
                }
            raise ValueError("missing order_id or user_id")

        if action == "logistics.lookup":
            if entities.get("tracking_no"):
                return "get_logistics_by_tracking", {"tracking_no": entities["tracking_no"]}
            if entities.get("order_id"):
                return "get_logistics_by_order", {"order_id": entities["order_id"]}
            raise ValueError("missing tracking_no or order_id")

        if action == "ticket.lookup":
            if entities.get("ticket_id"):
                return "get_ticket_by_id", {"ticket_id": entities["ticket_id"]}
            if entities.get("order_id"):
                return "list_tickets_by_order", {"order_id": entities["order_id"]}
            if entities.get("user_id"):
                return "list_tickets_by_user", {
                    "user_id": entities["user_id"],
                    "limit": entities.get("limit", 10),
                }
            raise ValueError("missing ticket_id / order_id / user_id")

        if action == "promotion.lookup":
            kw = entities.get("keyword") or entities.get("product_kw") or entities.get("query")
            if kw:
                return "search_promotions", {"kw": f"%{kw}%", "limit": 10}
            return "list_active_promotions", {}

        if action not in ACTION_ROUTES:
            raise KeyError(f"unknown action: {action}")
        tpl_name = ACTION_ROUTES[action]
        tpl = get_template(tpl_name)
        return tpl_name, self._bind_params(tpl, entities)

    async def run_action(
        self,
        action: str,
        entities: dict[str, Any] | None = None,
    ) -> SqlResult:
        name, params = self.resolve_action(action, entities)
        return await self.execute(name, params)

    # ----- 工具内部 -----
    @staticmethod
    def _normalize_sql(sql: str) -> str:
        return re.sub(r"\s+", " ", sql.strip())

    @staticmethod
    def _bind_params(tpl: SqlTemplate, params: dict[str, Any]) -> dict[str, Any]:
        missing = [k for k in tpl.required if params.get(k) is None]
        if missing:
            raise ValueError(f"template {tpl.name} missing params: {missing}")
        bound: dict[str, Any] = {}
        for key in list(tpl.required) + list(tpl.optional.keys()):
            if key in params and params[key] is not None:
                bound[key] = params[key]
            elif key in tpl.optional:
                bound[key] = tpl.optional[key]
        return bound

    @staticmethod
    def catalog() -> list[dict[str, Any]]:
        return list_templates()


sql_agent = SqlAgent()


def dumps_list(value: list | None) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def loads_list(value: str | None) -> list:
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
