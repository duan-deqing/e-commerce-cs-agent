"""会话内存存储：滑动上下文窗口 + TTL/LRU 淘汰 + 售后状态机上下文。"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.config import settings
from app.intent.entities import merge_entities


class AfterSalesState(str, Enum):
    IDLE = "idle"
    COLLECTING_INFO = "collecting_info"
    CONFIRMING = "confirming"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    REJECTED = "rejected"
    ESCALATED = "escalated"


@dataclass
class AfterSalesContext:
    state: AfterSalesState = AfterSalesState.IDLE
    kind: str | None = None  # return | exchange
    order_id: str | None = None
    reason: str | None = None
    variant: str | None = None
    ticket_id: str | None = None
    risk_hold: bool = False
    updated_at: float = field(default_factory=time.time)


@dataclass
class Session:
    session_id: str
    user_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)
    last_intent: str | None = None
    after_sales: AfterSalesContext = field(default_factory=AfterSalesContext)
    handoff: bool = False
    # 超出滑动窗口的早期对话由 LLM 压缩成的要点摘要，随上下文注入
    summary: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self._trim()
        self.updated_at = time.time()

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})
        self._trim()
        self.updated_at = time.time()

    def _trim(self) -> None:
        max_msgs = settings.context_max_turns * 2
        if len(self.messages) > max_msgs:
            self.messages = self.messages[-max_msgs:]

    def recent_messages(self, n: int = 8) -> list[dict[str, str]]:
        return self.messages[-n:]

    def merge_entities(self, new: dict[str, Any]) -> None:
        self.entities = merge_entities(self.entities, new)

    def as_history_messages(self) -> list[dict[str, str]]:
        msgs = self.recent_messages(10)
        if self.summary:
            msgs = [{"role": "system", "content": f"历史对话摘要：{self.summary}"}, *msgs]
        return msgs


class SessionStore:
    """线程安全的 LRU + TTL 会话缓存，防止无限增长。"""

    def __init__(self) -> None:
        self._store: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str | None, user_id: str) -> Session:
        sid = session_id or f"s_{uuid.uuid4().hex[:12]}"
        now = time.time()
        ttl = settings.session_ttl_seconds
        max_size = settings.session_max_size
        with self._lock:
            self._evict(now, ttl, max_size)
            sess = self._store.get(sid)
            if sess is not None:
                # 同一 session 被不同 user 使用时以最新请求为准并刷新
                sess.user_id = user_id
                sess.updated_at = now
                self._store.move_to_end(sid)
                return sess
            sess = Session(session_id=sid, user_id=user_id)
            self._store[sid] = sess
            self._store.move_to_end(sid)
            while len(self._store) > max_size:
                self._store.popitem(last=False)
            return sess

    def get(self, session_id: str) -> Session | None:
        now = time.time()
        with self._lock:
            sess = self._store.get(session_id)
            if sess is None:
                return None
            if now - sess.updated_at > settings.session_ttl_seconds:
                self._store.pop(session_id, None)
                return None
            self._store.move_to_end(session_id)
            return sess

    def _evict(self, now: float, ttl: int, max_size: int) -> None:
        expired = [sid for sid, s in self._store.items() if now - s.updated_at > ttl]
        for sid in expired:
            self._store.pop(sid, None)
        while len(self._store) > max_size:
            self._store.popitem(last=False)

    def summary(self, session_id: str) -> dict[str, Any] | None:
        sess = self.get(session_id)
        if not sess:
            return None
        return {
            "session_id": sess.session_id,
            "user_id": sess.user_id,
            "message_count": len(sess.messages),
            "last_intent": sess.last_intent,
            "entities": sess.entities,
            "handoff": sess.handoff,
            "after_sales": {
                "state": sess.after_sales.state.value,
                "kind": sess.after_sales.kind,
                "order_id": sess.after_sales.order_id,
                "ticket_id": sess.after_sales.ticket_id,
                "risk_hold": sess.after_sales.risk_hold,
            },
            "created_at": sess.created_at,
            "updated_at": sess.updated_at,
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "sessions": len(self._store),
                "ttl_seconds": settings.session_ttl_seconds,
                "max_size": settings.session_max_size,
            }


session_store = SessionStore()
