"""端到端冒烟测试（Mock LLM，无需外部 API）。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.logging import setup_logging
from app.tools import bootstrap_tools


async def main() -> int:
    setup_logging("WARNING")
    from app.db import init_db, seed_if_empty

    init_db()
    seed_if_empty()
    bootstrap_tools()
    from app.agent.orchestrator import orchestrator
    from app.rag.vectorstore import ingest_knowledge_dir

    n = await ingest_knowledge_dir()
    print(f"ingested={n}")

    cases = [
        ("u_1001", "你好"),
        ("u_1001", "查询订单 ORD20260301001"),
        ("u_1001", "物流到哪了 YT1234567890"),
        ("u_1001", "这款手机支持快充吗"),
        ("u_1001", "618有什么优惠"),
        ("u_1001", "我要退货 ORD20260301001 因为尺码不合适"),
        ("u_1001", "确认"),
        ("u_1003", "我要退 ORD20260310003 因为不想要了"),
        ("u_1003", "确认"),
        ("u_1001", "转人工"),
        ("u_1001", "投诉你们太慢了"),
    ]
    session_id = "smoke_s1"
    failed = 0
    for uid, msg in cases:
        resp = await orchestrator.handle_message(uid, msg, session_id=session_id)
        print("-" * 60)
        print(f"Q: {msg}")
        print(f"intent={resp.get('intent')} conf={resp.get('confidence')} handoff={resp.get('handoff')}")
        print(f"A: {resp.get('answer', '')[:180]}")
        if resp.get("error"):
            failed += 1
            print("ERROR:", resp["error"])
        if not resp.get("answer"):
            failed += 1
            print("EMPTY ANSWER")

    # 流式
    print("=" * 60)
    print("STREAM:")
    tokens = []
    async for ev in orchestrator.handle_message_stream("u_1001", "查询订单", session_id="smoke_s2"):
        print(ev["event"], str(ev.get("data"))[:120])
        if ev["event"] == "token":
            tokens.append(ev["data"]["token"])
    if not tokens:
        failed += 1
        print("NO STREAM TOKENS")

    print("=" * 60)
    print("FAILED" if failed else "ALL OK", f"issues={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
