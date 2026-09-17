"""订单 / 物流 / 促销业务服务：统一走模板化 SQL Agent。"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.agent.sql_agent.agent import loads_list, sql_agent

logger = get_logger(__name__)


def _order_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def _ticket_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["risk_hold"] = bool(data.get("risk_hold"))
    data["risk_flags"] = loads_list(data.pop("risk_flags_json", None))
    return data


class OrderService:
    """订单服务：通过模板化 SQL Agent 访问 SQLite。"""

    async def get_by_id(
        self, order_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        """user_id 非空时校验订单归属，防止越权读单。"""
        row = await sql_agent.query_one("get_order_by_id", {"order_id": order_id})
        if not row:
            return None
        if user_id and row.get("user_id") != user_id:
            logger.warning(
                "order ownership mismatch order=%s owner=%s caller=%s",
                order_id,
                row.get("user_id"),
                user_id,
            )
            return None
        order = _order_row_to_dict(row)
        items = await sql_agent.query_all("list_order_items", {"order_id": order_id})
        order["items"] = [dict(i) for i in items]
        return order

    async def list_by_user(self, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = await sql_agent.query_all(
            "list_orders_by_user", {"user_id": user_id, "limit": limit}
        )
        if not rows:
            return []
        item_rows = await sql_agent.query_all(
            "list_order_items_by_user", {"user_id": user_id}
        )
        items_map: dict[str, list[dict[str, Any]]] = {}
        for it in item_rows:
            items_map.setdefault(it["order_id"], []).append(dict(it))
        out = []
        for row in rows:
            order = _order_row_to_dict(row)
            order["items"] = items_map.get(order["order_id"], [])
            out.append(order)
        return out

    async def query(self, order_id: str | None, user_id: str | None) -> dict[str, Any]:
        if order_id:
            # 始终带上 user_id 做归属校验
            order = await self.get_by_id(order_id, user_id=user_id)
            if not order:
                return {"found": False, "message": f"未找到订单 {order_id}（或无权查看）"}
            return {"found": True, "order": order}
        if user_id:
            orders = await self.list_by_user(user_id)
            if not orders:
                return {"found": False, "message": "该用户名下暂无订单"}
            return {"found": True, "orders": orders, "count": len(orders)}
        return {"found": False, "message": "缺少订单号或用户标识"}


class LogisticsService:
    """物流服务：运单与轨迹查询。"""

    async def _load_track(self, tracking_no: str) -> dict[str, Any] | None:
        row = await sql_agent.query_one(
            "get_logistics_by_tracking", {"tracking_no": tracking_no}
        )
        if not row:
            return None
        track = dict(row)
        trace = await sql_agent.query_all(
            "list_logistics_trace", {"tracking_no": tracking_no}
        )
        track["trace"] = [dict(t) for t in trace]
        return track

    async def _owned(self, order_id: str | None, user_id: str | None) -> bool:
        if not order_id or not user_id:
            return True
        order = await sql_agent.query_one("get_order_by_id", {"order_id": order_id})
        return (not order) or order.get("user_id") == user_id

    async def query(
        self,
        tracking_no: str | None = None,
        order_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        tno = tracking_no
        if not tno and order_id:
            row = await sql_agent.query_one("get_logistics_by_order", {"order_id": order_id})
            tno = row.get("tracking_no") if row else None
        if not tno:
            return {"found": False, "message": "缺少运单号，且无法通过订单号关联"}
        track = await self._load_track(tno)
        if not track:
            return {"found": False, "message": f"未找到运单 {tno}"}
        if not await self._owned(track.get("order_id"), user_id):
            return {"found": False, "message": "无权查看该运单"}
        return {"found": True, "tracking": track}


class PromotionService:
    """促销活动查询。"""

    async def query(
        self, keyword: str | None = None, category: str | None = None
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        if keyword:
            kw = keyword.strip()
            tokens = {kw}
            for t in ("618", "双11", "满减", "新人", "优惠券", "秒杀", "鞋", "数码", "服饰", "折扣"):
                if t in kw:
                    tokens.add(t)
            seen: set[str] = set()
            for tok in tokens:
                part = await sql_agent.query_all(
                    "search_promotions_by_token",
                    {"token": f"%{tok}%", "limit": 10},
                )
                for r in part:
                    if r["campaign_id"] not in seen:
                        seen.add(r["campaign_id"])
                        rows.append(r)
        else:
            rows = await sql_agent.query_all("list_active_promotions", {})

        campaigns = [self._map_campaign(r) for r in rows]
        if category:
            campaigns = [c for c in campaigns if category in c.get("categories", [])]
        if not campaigns:
            active = await sql_agent.query_all("list_active_promotions", {})
            active_c = [self._map_campaign(r) for r in active]
            if active_c:
                return {"found": True, "campaigns": active_c, "count": len(active_c), "fallback": True}
            return {"found": False, "message": "暂无匹配活动", "campaigns": []}
        return {"found": True, "campaigns": campaigns, "count": len(campaigns)}

    async def list_all(self) -> list[dict]:
        rows = await sql_agent.query_all("list_active_promotions", {})
        return [self._map_campaign(r) for r in rows]

    @staticmethod
    def _map_campaign(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "campaign_id": row.get("campaign_id"),
            "name": row.get("name"),
            "status": row.get("status"),
            "start": row.get("start"),
            "end": row.get("end"),
            "categories": loads_list(row.get("categories_json")),
            "tags": loads_list(row.get("tags_json")),
            "rules": loads_list(row.get("rules_json")),
        }
