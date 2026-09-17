"""向量存储：ChromaDB 持久化，维度变更自动重建；不可用时内存降级。"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.chunker import Chunk, chunk_directory
from app.rag.embeddings import embed_query, embed_texts

logger = get_logger(__name__)

_client = None
_collection = None
_use_chroma = True
_collection_dim: int | None = None


def _get_chroma_client():
    global _client
    if _client is not None:
        return _client
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    _client = chromadb.PersistentClient(
        path=str(settings.chroma_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    return _client


def _ensure_collection(dim: int | None = None):
    """按需打开/重建集合；embedding 维度变化时自动重建。"""
    global _collection, _use_chroma, _collection_dim

    if _use_chroma is False and isinstance(_collection, _MemoryCollection):
        return _collection

    try:
        client = _get_chroma_client()
    except Exception as e:  # noqa: BLE001
        logger.warning("Chroma unavailable, fallback to in-memory store: %s", e)
        _use_chroma = False
        _collection = _MemoryCollection()
        return _collection

    try:
        col = client.get_collection(name="ecommerce_kb")
        stored_dim = None
        if col.metadata:
            stored_dim = int(col.metadata.get("dim") or 0) or None
        # 旧库无 dim 元数据时，用已有向量长度推断
        if stored_dim is None and col.count() > 0:
            try:
                peek = col.peek(limit=1)
                embs = peek.get("embeddings")
                if embs is not None and len(embs):
                    stored_dim = len(embs[0])
            except Exception:  # noqa: BLE001
                stored_dim = None

        need_rebuild = dim is not None and stored_dim is not None and stored_dim != dim
        if need_rebuild:
            logger.warning(
                "Chroma dim mismatch (stored=%s, new=%s), rebuilding collection",
                stored_dim,
                dim,
            )
            client.delete_collection("ecommerce_kb")
            col = client.get_or_create_collection(
                name="ecommerce_kb",
                metadata={"hnsw:space": "cosine", "dim": str(dim)},
            )
        elif dim is not None and not col.metadata:
            # 补写维度元数据
            client.modify_collection(
                "ecommerce_kb",
                metadata={"hnsw:space": "cosine", "dim": str(dim)},
            )
        _collection = col
        _collection_dim = dim or stored_dim
        _use_chroma = True
        logger.info("ChromaDB ready at %s (dim=%s)", settings.chroma_path, _collection_dim)
    except Exception:
        # 集合不存在
        meta = {"hnsw:space": "cosine"}
        if dim is not None:
            meta["dim"] = str(dim)
        _collection = client.get_or_create_collection(name="ecommerce_kb", metadata=meta)
        _collection_dim = dim
        _use_chroma = True
        logger.info("ChromaDB ready at %s (new collection dim=%s)", settings.chroma_path, dim)
    return _collection


def _get_collection(dim: int | None = None):
    global _collection
    if _collection is not None and (dim is None or _collection_dim in (None, dim)):
        return _collection
    return _ensure_collection(dim)


class _MemoryCollection:
    """Chroma 不可用时的内存降级实现。"""

    def __init__(self) -> None:
        self.ids: list[str] = []
        self.documents: list[str] = []
        self.metadatas: list[dict] = []
        self.embeddings: list[list[float]] = []

    def count(self) -> int:
        return len(self.ids)

    def add(self, ids, embeddings, documents, metadatas):  # type: ignore[no-untyped-def]
        # upsert by delete+add
        existing = set(self.ids)
        for i, id_ in enumerate(ids):
            if id_ in existing:
                idx = self.ids.index(id_)
                self.documents[idx] = documents[i]
                self.metadatas[idx] = metadatas[i]
                self.embeddings[idx] = embeddings[i]
            else:
                self.ids.append(id_)
                self.documents.append(documents[i])
                self.metadatas.append(metadatas[i])
                self.embeddings.append(embeddings[i])

    def query(self, query_embeddings, n_results=15):  # type: ignore[no-untyped-def]
        if not self.ids:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        q = query_embeddings[0]
        scored = []
        for i, emb in enumerate(self.embeddings):
            # cosine distance
            dot = sum(a * b for a, b in zip(q, emb))
            na = sum(a * a for a in q) ** 0.5 or 1
            nb = sum(b * b for b in emb) ** 0.5 or 1
            sim = dot / (na * nb)
            scored.append((1 - sim, i))
        scored.sort()
        top = scored[:n_results]
        return {
            "ids": [[self.ids[i] for _, i in top]],
            "documents": [[self.documents[i] for _, i in top]],
            "metadatas": [[self.metadatas[i] for _, i in top]],
            "distances": [[d for d, _ in top]],
        }

    def get(self, ids):  # type: ignore[no-untyped-def]
        idx = [self.ids.index(i) for i in ids if i in self.ids]
        return {
            "ids": [self.ids[i] for i in idx],
            "documents": [self.documents[i] for i in idx],
            "metadatas": [self.metadatas[i] for i in idx],
        }


async def ingest_chunks(chunks: list[Chunk]) -> int:
    if not chunks:
        return 0
    texts = [c.text for c in chunks]
    try:
        embs = await embed_texts(texts)
    except Exception as e:  # noqa: BLE001
        logger.warning("embedding failed, fallback to mock vectors: %s", e)
        from app.core.llm import MockLLM

        embs = await MockLLM().embed(texts)
    dim = len(embs[0]) if embs else None
    col = _ensure_collection(dim=dim)
    ids = [c.doc_id for c in chunks]
    metadatas = [
        {
            "title": c.title,
            "source": c.source,
            **{k: str(v) for k, v in c.metadata.items()},
        }
        for c in chunks
    ]
    if _use_chroma:
        col.upsert(ids=ids, embeddings=embs, documents=texts, metadatas=metadatas)
    else:
        col.add(ids=ids, embeddings=embs, documents=texts, metadatas=metadatas)
    logger.info("ingested %s chunks (chroma=%s dim=%s)", len(ids), _use_chroma, dim)
    return len(ids)


async def ingest_knowledge_dir() -> int:
    chunks = chunk_directory()
    return await ingest_chunks(chunks)


async def get_chunk_by_id(chunk_id: str) -> dict[str, Any] | None:
    """按 chunk id 取完整文档块（含来源元数据），供引用溯源展示。"""
    col = _ensure_collection()
    if col is None:
        return None
    try:
        res = col.get(ids=[chunk_id])
    except Exception as e:  # noqa: BLE001
        logger.warning("get chunk %s failed: %s", chunk_id, e)
        return None
    docs = res.get("documents") or []
    if not docs:
        return None
    meta = (res.get("metadatas") or [{}])[0] or {}
    return {
        "doc_id": chunk_id,
        "title": meta.get("title", "知识库"),
        "content": docs[0] or "",
        "source": meta.get("source", ""),
        "section": meta.get("section", ""),
    }


async def similarity_search(query: str, k: int | None = None) -> list[dict[str, Any]]:
    k = k or settings.rag_top_k
    qvec = await embed_query(query)
    col = _ensure_collection(dim=len(qvec))
    try:
        count = col.count()
    except Exception:  # noqa: BLE001
        count = 0
    if count == 0:
        return []
    res = col.query(query_embeddings=[qvec], n_results=min(k, count))
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    ids = res.get("ids", [[]])[0]
    out: list[dict[str, Any]] = []
    for i, doc in enumerate(docs):
        dist = dists[i] if i < len(dists) else 1.0
        score = max(0.0, 1.0 - float(dist))
        out.append(
            {
                "id": ids[i] if i < len(ids) else f"c{i}",
                "text": doc,
                "metadata": metas[i] if i < len(metas) else {},
                "score": round(score, 4),
            }
        )
    return out
