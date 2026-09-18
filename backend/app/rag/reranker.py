"""重排：优先 Ollama 本地 cross-encoder（bge-reranker-v2-m3），失败降级本地融合打分。"""

from __future__ import annotations

import math
import re
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_http: httpx.AsyncClient | None = None


def _get_http() -> httpx.AsyncClient:
    # 模块级共享连接，避免每次检索重建 client
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=settings.rerank_timeout_s)
    return _http


async def aclose() -> None:
    global _http
    if _http is not None and not _http.is_closed:
        await _http.aclose()
    _http = None


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


def _local_fusion_rerank(
    query: str, docs: list[dict[str, Any]], top_n: int
) -> list[dict[str, Any]]:
    """本地融合重排：向量分 0.65 + 关键词重叠 0.35。"""
    q_tokens = _tokenize(query)
    scored: list[dict[str, Any]] = []
    for d in docs:
        t_tokens = _tokenize(d.get("text", ""))
        overlap = len(q_tokens & t_tokens) / (len(q_tokens) or 1)
        vec_score = float(d.get("score", 0.0))
        fused = 0.65 * vec_score + 0.35 * min(1.0, overlap * 2)
        item = dict(d)
        item["rerank_score"] = round(fused, 4)
        item["keyword_overlap"] = round(overlap, 4)
        item["rerank_source"] = "local"
        scored.append(item)
    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    return scored[:top_n]


async def _ollama_scores(query: str, docs: list[dict[str, Any]]) -> dict[int, float] | None:
    """Ollama cross-encoder 打分：query</s></s>doc 经 rank pooling 输出 1 维 logit，sigmoid 归一。

    不可用/输出形态异常时返回 None，由上层降级本地融合。
    """
    model = settings.rerank_model.strip()
    if not model or not docs:
        return None
    pairs = [f"{query}</s></s>{d.get('text', '')}" for d in docs]
    try:
        resp = await _get_http().post(
            f"{settings.ollama_base_url.rstrip('/')}/api/embed",
            json={"model": model, "input": pairs},
        )
        if resp.status_code >= 400:
            logger.warning("ollama rerank HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        embs = resp.json().get("embeddings") or []
        if len(embs) != len(docs) or any(len(e) != 1 for e in embs):
            logger.warning("ollama rerank unexpected output shape: %s docs", len(embs))
            return None
        return {i: 1.0 / (1.0 + math.exp(-float(e[0]))) for i, e in enumerate(embs)}
    except Exception as e:  # noqa: BLE001
        logger.warning("ollama rerank unavailable, fallback to local fusion: %s", e)
        return None


async def rerank(
    query: str, docs: list[dict[str, Any]], top_n: int | None = None
) -> list[dict[str, Any]]:
    """重排入口：auto=优先 Ollama cross-encoder（失败降级）；local=仅本地融合。"""
    top_n = top_n or settings.rag_rerank_top_n
    if not docs:
        return []
    backend = settings.rerank_backend.strip().lower()
    if backend in {"auto", "ollama"}:
        scores = await _ollama_scores(query, docs)
        if scores is not None:
            out = [dict(d) for d in docs]
            for i, item in enumerate(out):
                item["rerank_score"] = round(scores[i], 4)
                item["rerank_source"] = "ollama"
            out.sort(key=lambda x: x["rerank_score"], reverse=True)
            return out[:top_n]
        if backend == "ollama":
            logger.warning("rerank_backend=ollama but unavailable; falling back to local fusion")
    return _local_fusion_rerank(query, docs, top_n)
