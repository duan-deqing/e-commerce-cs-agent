"""RAG 问答链：召回 → 重排 → 低置信拒答 → LLM 回答。"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.llm import get_llm
from app.core.logging import get_logger
from app.rag.reranker import rerank
from app.rag.vectorstore import similarity_search

logger = get_logger(__name__)

RAG_SYSTEM = """你是电商客服知识问答助手。请严格依据提供的资料回答，不要编造。
若资料不足以回答，明确说明未找到，并建议用户转人工或补充信息。
回答使用简洁中文，可分点。不要输出资料中不存在的承诺。

资料：
{context}
"""

NO_HIT_MSG = (
    "我在知识库中没有找到足够匹配的内容，为避免给您错误信息，"
    "这里不做猜测。您可以换个说法，或转人工客服获取准确答复。"
)


async def retrieve(query: str, top_k: int | None = None, top_n: int | None = None) -> dict[str, Any]:
    hits = await similarity_search(query, k=top_k or settings.rag_top_k)
    ranked = await rerank(query, hits, top_n=top_n or settings.rag_rerank_top_n)
    threshold = settings.rag_score_threshold
    kept = [d for d in ranked if d.get("rerank_score", 0) >= threshold]
    # 无一过阈值：保留相对高分 top_n 并标记 low_confidence（避免 mock 向量全灭）
    low_confidence = not kept
    if not kept and ranked:
        kept = ranked[: max(1, top_n or settings.rag_rerank_top_n)]
    sources = [
        {
            "doc_id": d["id"],
            "title": d.get("metadata", {}).get("title", "知识库"),
            "score": d.get("rerank_score"),
            "rerank_source": d.get("rerank_source", "local"),
            "snippet": (d.get("text") or "")[:180],
        }
        for d in kept
    ]
    return {
        "chunks": kept,
        "sources": sources,
        "low_confidence": low_confidence,
        "raw_count": len(hits),
    }


async def answer_with_rag(
    query: str,
    history: list[dict[str, str]] | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    retrieval = await retrieve(query)
    chunks = retrieval["chunks"]
    sources = retrieval["sources"]
    llm = get_llm()

    if not chunks:
        return {
            "answer": NO_HIT_MSG,
            "sources": [],
            "low_confidence": True,
        }

    context = "\n\n".join(
        f"[{i+1}] {c.get('metadata', {}).get('title', '')}\n{c.get('text', '')}"
        for i, c in enumerate(chunks)
    )
    system = RAG_SYSTEM.format(context=context)
    messages = list(history or []) + [{"role": "user", "content": query}]

    if stream:
        # 由 orchestrator 负责真正流式；这里返回 generator 元信息
        return {
            "stream": True,
            "system": system,
            "messages": messages,
            "sources": sources,
            "low_confidence": retrieval["low_confidence"],
        }

    try:
        answer = await llm.chat(system=system, messages=messages, temperature=0.2)
    except Exception as e:  # noqa: BLE001
        logger.warning("rag llm failed: %s", e)
        # 降级：直接返回资料摘要
        answer = "已为您检索到相关资料：\n" + "\n".join(
            f"- {s['title']}: {s['snippet']}" for s in sources
        )
    return {
        "answer": answer,
        "sources": sources,
        "low_confidence": retrieval["low_confidence"],
    }
