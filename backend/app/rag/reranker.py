from __future__ import annotations

import re
from typing import Any

from app.core.config import settings


def _tokenize(text: str) -> set[str]:
    # 中英文混合粗分词
    text = text.lower()
    parts = set(re.findall(r"[a-z0-9]+", text))
    # 中文按 2-gram
    chinese = re.findall(r"[一-鿿]+", text)
    for seg in chinese:
        if len(seg) == 1:
            parts.add(seg)
        else:
            for i in range(len(seg) - 1):
                parts.add(seg[i : i + 2])
    return parts


def rerank(query: str, docs: list[dict[str, Any]], top_n: int | None = None) -> list[dict[str, Any]]:
    """本地融合重排：向量分 + 关键词重叠。

    生产可替换为 bge-reranker / Cohere Rerank API，接口保持一致。
    """
    top_n = top_n or settings.rag_rerank_top_n
    if not docs:
        return []
    q_tokens = _tokenize(query)
    scored: list[dict[str, Any]] = []
    for d in docs:
        t_tokens = _tokenize(d.get("text", ""))
        overlap = len(q_tokens & t_tokens) / (len(q_tokens) or 1)
        vec_score = float(d.get("score", 0.0))
        # 融合：向量 0.65 + 词重叠 0.35
        fused = 0.65 * vec_score + 0.35 * min(1.0, overlap * 2)
        item = dict(d)
        item["rerank_score"] = round(fused, 4)
        item["keyword_overlap"] = round(overlap, 4)
        scored.append(item)
    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    return scored[:top_n]
