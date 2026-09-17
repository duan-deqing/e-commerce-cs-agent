"""SQLite 连接管理与 Schema。写操作经全局锁，避免多线程并发写冲突。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def db_lock() -> threading.Lock:
    """对外暴露写锁，供 SQL Agent 同步执行段使用。"""
    return _lock

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    created_at TEXT,
    payment TEXT,
    receiver_city TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    product_id TEXT,
    name TEXT,
    sku TEXT,
    qty INTEGER NOT NULL DEFAULT 1,
    price REAL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS logistics_tracks (
    tracking_no TEXT PRIMARY KEY,
    order_id TEXT,
    carrier TEXT,
    status TEXT,
    eta TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE IF NOT EXISTS logistics_trace (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_no TEXT NOT NULL,
    time TEXT,
    desc TEXT,
    FOREIGN KEY (tracking_no) REFERENCES logistics_tracks(tracking_no) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS promotions (
    campaign_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT,
    start TEXT,
    "end" TEXT,
    categories_json TEXT,
    tags_json TEXT,
    rules_json TEXT
);

CREATE TABLE IF NOT EXISTS after_sales_tickets (
    ticket_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    order_id TEXT NOT NULL,
    user_id TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    variant TEXT,
    amount REAL,
    refund_status TEXT,
    risk_hold INTEGER NOT NULL DEFAULT 0,
    risk_flags_json TEXT,
    created_at TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE IF NOT EXISTS after_sales_timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL,
    time TEXT,
    step TEXT,
    FOREIGN KEY (ticket_id) REFERENCES after_sales_tickets(ticket_id) ON DELETE CASCADE
);

-- 每请求全链路 Trace：监控指标（P50/P95/TTFT/成本/转接率）与坏案例回溯的数据源
CREATE TABLE IF NOT EXISTS request_trace (
    trace_id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    session_id TEXT,
    user_id TEXT,
    intent TEXT,
    confidence REAL,
    route TEXT,
    model TEXT,
    prompt_version TEXT,
    tools_json TEXT,
    sources_json TEXT,
    ttft_ms REAL,
    total_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    tokens_estimated INTEGER NOT NULL DEFAULT 0,
    cost REAL,
    handoff INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    answer_snippet TEXT,
    masked_input INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_trace_ts ON request_trace(ts);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_logi_order ON logistics_tracks(order_id);
CREATE INDEX IF NOT EXISTS idx_ticket_order ON after_sales_tickets(order_id);
CREATE INDEX IF NOT EXISTS idx_ticket_user ON after_sales_tickets(user_id);
"""


def get_db_path() -> Path:
    p = Path(settings.db_path)
    if not p.is_absolute():
        p = settings.backend_root / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is None:
            path = get_db_path()
            _conn = sqlite3.connect(
                str(path),
                check_same_thread=False,
                timeout=30,
            )
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            logger.info("SQLite connected: %s", path)
    return _conn


def init_db() -> None:
    conn = get_connection()
    with _lock:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def close_db() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
