from __future__ import annotations

from app.core.llm import get_llm


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    llm = get_llm()
    # 批量，避免过大请求
    batch = 32
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        part = texts[i : i + batch]
        vectors.extend(await llm.embed(part))
    return vectors


async def embed_query(text: str) -> list[float]:
    vecs = await embed_texts([text])
    return vecs[0] if vecs else []
