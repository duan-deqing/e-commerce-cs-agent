"""TTFT 探针：测量流式对话的首个 reasoning / token 事件延迟。

用法：
    python scripts/ttft_probe.py --base http://127.0.0.1:8001 --message "这款手机支持快充吗"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx


async def probe(base: str, message: str, session_id: str | None) -> None:
    t0 = time.perf_counter()
    first_reasoning: float | None = None
    first_token: float | None = None
    reasoning_chars = 0
    answer_chars = 0
    events = 0
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{base}/api/v1/chat/stream",
            json={"user_id": "u_probe", "session_id": session_id, "message": message},
            headers={"Accept": "text/event-stream"},
        ) as resp:
            resp.raise_for_status()
            event = "message"
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                events += 1
                now = (time.perf_counter() - t0) * 1000
                if event == "reasoning":
                    reasoning_chars += len(str(data.get("text") or ""))
                    if first_reasoning is None:
                        first_reasoning = now
                elif event == "token":
                    answer_chars += len(str(data.get("token") or ""))
                    if first_token is None:
                        first_token = now
                elif event == "done":
                    print(f"server_total_ms={data.get('latency_ms')}")
    print(
        f"events={events} "
        f"first_reasoning_ms={first_reasoning and round(first_reasoning)} "
        f"ttft_ms={first_token and round(first_token)} "
        f"reasoning_chars={reasoning_chars} answer_chars={answer_chars}"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--message", default="这款手机支持快充吗")
    p.add_argument("--session", default=None)
    a = p.parse_args()
    asyncio.run(probe(a.base, a.message, a.session))
