from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _load_json(name: str) -> Any:
    path = settings.data_path / name
    if not path.exists():
        logger.warning("data file missing: %s", path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class OrderService:
    def __init__(self) -> None:
        self._orders: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        data = _load_json("orders.json")
        items = data.get("orders", data if isinstance(data, list) else [])
        self._orders = {str(o["order_id"]): o for o in items}

    def get_by_id(self, order_id: str) -> dict[str, Any] | None:
        return self._orders.get(order_id)

    def list_by_user(self, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        items = [o for o in self._orders.values() if o.get("user_id") == user_id]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items[:limit]

    def query(self, order_id: str | None, user_id: str | None) -> dict[str, Any]:
        if order_id:
            order = self.get_by_id(order_id)
            if not order:
                return {"found": False, "message": f"未找到订单 {order_id}"}
            return {"found": True, "order": order}
        if user_id:
            orders = self.list_by_user(user_id)
            if not orders:
                return {"found": False, "message": "该用户名下暂无订单"}
            return {"found": True, "orders": orders, "count": len(orders)}
        return {"found": False, "message": "缺少订单号或用户标识"}


class LogisticsService:
    def __init__(self) -> None:
        self._tracks: dict[str, dict] = {}
        self._by_order: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        data = _load_json("logistics.json")
        items = data.get("tracks", data if isinstance(data, list) else [])
        self._tracks = {}
        self._by_order = {}
        for t in items:
            self._tracks[t["tracking_no"]] = t
            if t.get("order_id"):
                self._by_order[t["order_id"]] = t["tracking_no"]

    def query(
        self,
        tracking_no: str | None = None,
        order_id: str | None = None,
    ) -> dict[str, Any]:
        tno = tracking_no
        if not tno and order_id:
            tno = self._by_order.get(order_id)
        if not tno:
            return {"found": False, "message": "缺少运单号，且无法通过订单号关联"}
        track = self._tracks.get(tno)
        if not track:
            return {"found": False, "message": f"未找到运单 {tno}"}
        return {"found": True, "tracking": track}


class PromotionService:
    def __init__(self) -> None:
        self._campaigns: list[dict] = []
        self.reload()

    def reload(self) -> None:
        data = _load_json("promotions.json")
        self._campaigns = data.get("campaigns", [])

    def query(self, keyword: str | None = None, category: str | None = None) -> dict[str, Any]:
        items = self._campaigns
        if keyword:
            kw = keyword.strip()
            # 抽取短关键词（618/双11/满减 等）
            tokens = set()
            if kw:
                tokens.add(kw)
            for t in ("618", "双11", "满减", "新人", "优惠券", "秒杀", "鞋", "数码", "服饰", "折扣"):
                if t in kw or t in (keyword or ""):
                    tokens.add(t)
            matched = []
            for c in items:
                hay = " ".join(
                    [
                        c.get("name", ""),
                        " ".join(c.get("tags", [])),
                        " ".join(c.get("rules", [])),
                        " ".join(c.get("categories", [])),
                    ]
                )
                if any(tok and tok in hay for tok in tokens):
                    matched.append(c)
            items = matched
        if category:
            items = [c for c in items if category in c.get("categories", [])]
        # 无匹配时返回全部进行中活动，避免假阴性
        if not items:
            active = [c for c in self._campaigns if c.get("status") == "active"]
            if active:
                return {"found": True, "campaigns": active, "count": len(active), "fallback": True}
            return {"found": False, "message": "暂无匹配活动", "campaigns": []}
        return {"found": True, "campaigns": items, "count": len(items)}

    def list_all(self) -> list[dict]:
        return list(self._campaigns)
