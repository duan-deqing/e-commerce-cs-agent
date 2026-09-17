from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field


@dataclass
class Metrics:
    lock: threading.Lock = field(default_factory=threading.Lock)
    total_requests: int = 0
    total_errors: int = 0
    intent_counts: Counter = field(default_factory=Counter)
    tool_calls: int = 0
    tool_failures: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def record_request(self) -> None:
        with self.lock:
            self.total_requests += 1

    def record_error(self) -> None:
        with self.lock:
            self.total_errors += 1

    def record_intent(self, intent: str) -> None:
        with self.lock:
            self.intent_counts[intent] += 1

    def record_tool(self, success: bool) -> None:
        with self.lock:
            self.tool_calls += 1
            if not success:
                self.tool_failures += 1

    def record_latency(self, ms: float) -> None:
        with self.lock:
            self.latencies_ms.append(ms)
            if len(self.latencies_ms) > 2000:
                self.latencies_ms = self.latencies_ms[-1000:]

    def snapshot(self) -> dict:
        with self.lock:
            lats = sorted(self.latencies_ms)
            p95 = lats[int(len(lats) * 0.95) - 1] if lats else 0.0
            avg = sum(lats) / len(lats) if lats else 0.0
            return {
                "uptime_s": round(time.time() - self.started_at, 2),
                "total_requests": self.total_requests,
                "total_errors": self.total_errors,
                "intent_counts": dict(self.intent_counts),
                "tool_calls": self.tool_calls,
                "tool_failures": self.tool_failures,
                "latency_avg_ms": round(avg, 2),
                "latency_p95_ms": round(p95, 2),
            }


metrics = Metrics()
