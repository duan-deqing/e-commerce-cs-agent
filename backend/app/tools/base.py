"""业务工具运行时：Tool 抽象、重试、超时、并行执行与注册表。"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import metrics

logger = get_logger(__name__)


@dataclass
class ToolResult:
    tool: str
    success: bool
    data: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    retried: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolContext:
    user_id: str
    session_id: str
    entities: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class BaseTool(ABC):
    name: str = "base"
    description: str = ""
    required_entities: list[str] = []
    optional_entities: list[str] = []

    @abstractmethod
    async def run(self, ctx: ToolContext) -> dict[str, Any]:
        ...

    def missing_required(self, ctx: ToolContext) -> list[str]:
        return [k for k in self.required_entities if not ctx.entities.get(k)]


async def run_with_retry(
    tool: BaseTool,
    ctx: ToolContext,
    max_retries: int | None = None,
    timeout_s: float | None = None,
) -> ToolResult:
    """单工具执行：缺参直接失败；超时+指数退避重试；最终包成 ToolResult。"""
    max_retries = max_retries if max_retries is not None else settings.tool_max_retries
    timeout_s = timeout_s if timeout_s is not None else settings.tool_timeout_s
    start = time.perf_counter()
    last_err: str | None = None
    retried = 0

    missing = tool.missing_required(ctx)
    if missing:
        return ToolResult(
            tool=tool.name,
            success=False,
            error=f"missing_entities:{','.join(missing)}",
            latency_ms=0,
            data={"missing": missing},
        )

    for attempt in range(max_retries + 1):
        try:
            data = await asyncio.wait_for(tool.run(ctx), timeout=timeout_s)
            latency = (time.perf_counter() - start) * 1000
            metrics.record_tool(True)
            return ToolResult(
                tool=tool.name,
                success=True,
                data=data,
                latency_ms=round(latency, 2),
                retried=retried,
            )
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            if attempt < max_retries:
                retried += 1
                await asyncio.sleep(0.3 * (2**attempt))
            else:
                break

    latency = (time.perf_counter() - start) * 1000
    metrics.record_tool(False)
    return ToolResult(
        tool=tool.name,
        success=False,
        error=last_err or "unknown_error",
        latency_ms=round(latency, 2),
        retried=retried,
    )


async def run_parallel(
    tools: list[BaseTool],
    ctx: ToolContext,
) -> list[ToolResult]:
    """并行执行多个工具（语义对齐 LCEL RunnableParallel）。"""
    if not tools:
        return []
    results = await asyncio.gather(*[run_with_retry(t, ctx) for t in tools])
    return list(results)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def resolve(self, names: list[str]) -> list[BaseTool]:
        out = []
        for n in names:
            t = self._tools.get(n)
            if t:
                out.append(t)
        return out

    def all(self) -> list[BaseTool]:
        return list(self._tools.values())


registry = ToolRegistry()
