"""请求级全链路 Trace：每条对话请求落库 SQLite，支撑监控指标与坏案例回溯。

设计原则：save_trace 绝不抛错、不阻塞主链路——监控是旁路，不是关键路径。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_TRACE_COLUMNS = (
    "trace_id",
    "ts",
    "session_id",
    "user_id",
    "intent",
    "confidence",
    "route",
    "model",
    "prompt_version",
    "tools_json",
    "sources_json",
    "ttft_ms",
    "total_ms",
    "prompt_tokens",
    "completion_tokens",
    "tokens_estimated",
    "cost",
    "handoff",
    "error",
    "answer_snippet",
    "masked_input",
)


def new_trace_id() -> str:
    """trace_id：时间可读 + 随机后缀，贯穿 SSE 事件与 trace 表。"""
    return f"tr_{int(time.time() * 1000):x}_{uuid.uuid4().hex[:8]}"


def _coerce(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, bool):
        return int(value)
    return str(value)


def save_trace(row: dict[str, Any]) -> None:
    """写入 request_trace 表；列按 _TRACE_COLUMNS 白名单取值，失败只记日志。"""
    try:
        from app.db.connection import db_lock, get_connection

        record = {k: row.get(k) for k in _TRACE_COLUMNS}
        for key in ("tools_json", "sources_json"):
            v = record.get(key)
            if v is not None and not isinstance(v, str):
                record[key] = json.dumps(v, ensure_ascii=False)
        record["ts"] = record.get("ts") or time.time()
        cols = ", ".join(_TRACE_COLUMNS)
        holders = ", ".join(f":{c}" for c in _TRACE_COLUMNS)
        conn = get_connection()
        with db_lock():
            conn.execute(f"INSERT OR REPLACE INTO request_trace ({cols}) VALUES ({holders})", record)
            conn.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("save_trace failed (non-fatal): %s", e)
