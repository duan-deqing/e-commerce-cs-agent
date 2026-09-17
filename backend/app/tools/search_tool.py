from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.tools.base import BaseTool, ToolContext, registry

logger = get_logger(__name__)


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "全网搜索补充外部信息（Tavily）"
    optional_entities = ["query"]

    def __init__(self) -> None:
        self.enabled = bool(settings.tavily_api_key.strip())

    async def run(self, ctx: ToolContext) -> dict[str, Any]:
        if not self.enabled:
            return {
                "found": False,
                "message": "未配置 Tavily_API_KEY，全网搜索已降级关闭",
                "degraded": True,
            }
        query = ctx.entities.get("query") or ctx.message
        if not query:
            return {"found": False, "message": "缺少搜索关键词"}
        payload = {
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": 3,
            "search_depth": "basic",
        }
        async with httpx.AsyncClient(timeout=settings.tool_timeout_s + 2) as client:
            resp = await client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
        results = [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": (r.get("content") or "")[:400],
            }
            for r in data.get("results", [])
        ]
        return {"found": bool(results), "results": results}


def register_search_tools() -> None:
    registry.register(WebSearchTool())
