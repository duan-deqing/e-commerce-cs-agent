"""上下文摘要压缩：滑动窗口将满时，把早期对话压缩为 LLM 摘要，替代被裁剪的历史。

触发时机：在 add_user 之前调用（此时被裁剪的内容还在 messages 里），
压缩后保留「摘要 + 最近一半窗口」，保证早期关键信息（订单号、诉求）不丢。
"""

from __future__ import annotations

from app.core.config import settings
from app.core.llm import get_llm
from app.core.logging import get_logger
from app.state.session import Session

logger = get_logger(__name__)

_SUMMARY_SYSTEM = (
    "你是对话摘要助手。把客服对话压缩为不超过 80 字的要点，"
    "必须保留：订单号/运单号/工单号、用户诉求、已给出的处理结果。只输出摘要正文。"
)


async def maybe_summarize(session: Session) -> None:
    """消息数达到滑动窗口上限时，把前段压缩为摘要，保留最近一半窗口。"""
    max_msgs = settings.context_max_turns * 2
    if len(session.messages) < max_msgs:
        return

    keep = max_msgs // 2
    overflow = len(session.messages) - keep
    old_msgs = session.messages[:overflow]
    session.messages = session.messages[overflow:]
    logger.info("context summarize: compress %d messages, keep %d", len(old_msgs), keep)

    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in old_msgs)
    if session.summary:
        transcript = f"已有摘要：{session.summary}\n\n新对话：\n{transcript}"

    try:
        llm = get_llm()
        summary = await llm.chat(system=_SUMMARY_SYSTEM, messages=[{"role": "user", "content": transcript}], max_tokens=120)
        # 空结果时保留旧摘要，避免丢失已有历史信息
        new_summary = (summary or "").strip()[:400]
        if new_summary:
            session.summary = new_summary
    except Exception as e:  # noqa: BLE001
        # 摘要失败不影响主链路：退化为仅保留最近窗口
        logger.warning("summarize failed (non-fatal): %s", e)
