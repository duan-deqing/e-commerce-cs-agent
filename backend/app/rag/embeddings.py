from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.llm import get_llm


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    # 独立向量端点（OpenAI 兼容，如本地 Ollama）；未配置时跟随 LLM 端点（DashScope / Mock）
    base = settings.embedding_base_url.strip().rstrip("/")
    if not base:
        llm = get_llm()
        # DashScope text-embedding 单次 input 上限 10，保持兼容
        batch = 10
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch):
            part = texts[i : i + batch]
            vectors.extend(await llm.embed(part))
        return vectors

    key = settings.embedding_api_key.strip() or settings.llm_api_key.strip()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    vectors: list[list[float]] = []
    batch = 32
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(texts), batch):
            part = texts[i : i + batch]
            resp = await client.post(
                f"{base}/embeddings",
                headers=headers,
                json={"model": settings.embedding_model, "input": part},
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"embedding API {resp.status_code}, model={settings.embedding_model}: "
                    f"{resp.text[:500]}"
                )
            data = resp.json()
            vectors.extend(item["embedding"] for item in data["data"])
    return vectors


async def embed_query(text: str) -> list[float]:
    vecs = await embed_texts([text])
    return vecs[0] if vecs else []
