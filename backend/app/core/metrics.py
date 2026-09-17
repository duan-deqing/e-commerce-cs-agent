"""进程内简易指标：请求量、意图分布、工具成功率、延迟分位。"""

from __future__ import annotations

import threading
import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Metrics:
    lock: threading.Lock = field(default_factory=threading.Lock)
    total_requests: int = 0
    total_errors: int = 0
    total_handoffs: int = 0
    total_badcases: int = 0
    intent_counts: Counter = field(default_factory=Counter)
    tool_calls: int = 0
    tool_failures: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    ttfts_ms: list[float] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tokens_estimated_count: int = 0
    cost_total: float = 0.0
    started_at: float = field(default_factory=time.time)

    def record_request(self) -> None:
        with self.lock:
            self.total_requests += 1

    def record_error(self) -> None:
        with self.lock:
            self.total_errors += 1

    def record_handoff(self) -> None:
        with self.lock:
            self.total_handoffs += 1

    def record_badcase(self) -> None:
        with self.lock:
            self.total_badcases += 1

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

    def record_ttft(self, ms: float) -> None:
        with self.lock:
            self.ttfts_ms.append(ms)
            if len(self.ttfts_ms) > 2000:
                self.ttfts_ms = self.ttfts_ms[-1000:]

    def record_tokens(self, prompt_tokens: int, completion_tokens: int, estimated: bool, cost: float) -> None:
        with self.lock:
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            if estimated:
                self.tokens_estimated_count += 1
            self.cost_total += cost

    @staticmethod
    def _percentile(sorted_vals: list[float], q: float) -> float:
        if not sorted_vals:
            return 0.0
        idx = min(int(len(sorted_vals) * q), len(sorted_vals) - 1)
        return sorted_vals[max(idx, 0)]

    def snapshot(self) -> dict:
        with self.lock:
            lats = sorted(self.latencies_ms)
            ttfts = sorted(self.ttfts_ms)
            avg = sum(lats) / len(lats) if lats else 0.0
            total = self.total_requests or 1
            error_rate = self.total_errors / total
            handoff_rate = self.total_handoffs / total
            return {
                "uptime_s": round(time.time() - self.started_at, 2),
                "total_requests": self.total_requests,
                "total_errors": self.total_errors,
                "intent_counts": dict(self.intent_counts),
                "tool_calls": self.tool_calls,
                "tool_failures": self.tool_failures,
                "latency_avg_ms": round(avg, 2),
                "latency_p50_ms": round(self._percentile(lats, 0.50), 2),
                "latency_p95_ms": round(self._percentile(lats, 0.95), 2),
                "ttft_p50_ms": round(self._percentile(ttfts, 0.50), 2),
                "ttft_p95_ms": round(self._percentile(ttfts, 0.95), 2),
                "error_rate": round(error_rate, 4),
                "handoff_rate": round(handoff_rate, 4),
                # 自助解决率 = 未转人工且未出错的请求占比
                "self_resolve_rate": round(max(0.0, 1.0 - error_rate - handoff_rate), 4),
                "badcase_rate": round(self.total_badcases / total, 4),
                "tokens": {
                    "prompt": self.prompt_tokens,
                    "completion": self.completion_tokens,
                    "estimated_count": self.tokens_estimated_count,
                },
                "cost_total": round(self.cost_total, 6),
            }


metrics = Metrics()
