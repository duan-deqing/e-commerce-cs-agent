"""P2 验证脚本：14 轮对话触发摘要压缩 + 稳定前缀字节级检查。"""
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
    from app.agent.prompts import ANSWER_RULES, build_answer_system
    from app.core.config import settings
    from app.state.session import session_store

    # 1) 稳定前缀字节级检查
    s1 = build_answer_system("订单查询", "（无）", "（无）")
    s2 = build_answer_system("物流查询", '{"tool":"x","success":true}', "资料")
    assert s1.startswith(ANSWER_RULES) and s2.startswith(ANSWER_RULES)
    assert ANSWER_RULES in s1 and ANSWER_RULES in s2
    # 前缀部分与动态部分严格分离
    assert s1[: len(ANSWER_RULES)] == s2[: len(ANSWER_RULES)]
    print(f"[1] stable prefix OK (len={len(ANSWER_RULES)}), byte-identical across requests")

    # 2) 14 轮对话触发摘要
    uid, sid = "u_p2", "smoke_summary_s1"
    for i in range(14):
        await orchestrator.handle_message(uid, f"查询订单 ORD2026030100{i:02d} 的状态", session_id=sid)
    sess = session_store.get(sid)
    assert sess is not None, "session lost"
    print(f"[2] turns=14 messages={len(sess.messages)} summary={'YES: ' + (sess.summary or '')[:60] if sess.summary else 'NO'}")
    hist = sess.as_history_messages()
    has_summary_in_hist = bool(hist) and hist[0]["role"] == "system" and "历史对话摘要" in hist[0]["content"]
    print(f"[2] history_head_is_summary={has_summary_in_hist}, history_len={len(hist)}")

    # 3) 早期信息可被摘要回溯（摘要里应含订单号）
    if sess.summary:
        print(f"[3] summary contains order ref: {'ORD' in sess.summary or '订单' in sess.summary}")

    ok = has_summary_in_hist and len(sess.messages) <= settings.context_max_turns * 2
    print("P2 VERIFY", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
