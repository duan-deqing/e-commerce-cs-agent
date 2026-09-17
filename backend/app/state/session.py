from __future__ import annotations

import time
import uuid
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
        return self.recent_messages(10)


class SessionStore:
    def __init__(self) -> None:
        self._store: dict[str, Session] = {}

    def get_or_create(self, session_id: str | None, user_id: str) -> Session:
        sid = session_id or f"s_{uuid.uuid4().hex[:12]}"
        if sid not in self._store:
            self._store[sid] = Session(session_id=sid, user_id=user_id)
        sess = self._store[sid]
        sess.user_id = user_id
        return sess

    def get(self, session_id: str) -> Session | None:
        return self._store.get(session_id)

    def summary(self, session_id: str) -> dict[str, Any] | None:
        sess = self._store.get(session_id)
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


session_store = SessionStore()
