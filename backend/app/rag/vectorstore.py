from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.chunker import Chunk, chunk_directory
from app.rag.embeddings import embed_query, embed_texts

logger = get_logger(__name__)

_collection = None
_use_chroma = True


def _get_collection():
    global _collection, _use_chroma
    if _collection is not None:
        return _collection
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.PersistentClient(
            path=str(settings.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        # 维度变更时强制重建，避免 upsert 维度不一致
        try:
            _collection = client.get_collection(name="ecommerce_kb")
            if _collection.metadata and _collection.metadata.get("dim") != "128":
                client.delete_collection("ecommerce_kb")
                _collection = client.get_or_create_collection(
                    name="ecommerce_kb",
                    metadata={"hnsw:space": "cosine", "dim": "128"},
                )
        except Exception:  # noqa: BLE001
            _collection = client.get_or_create_collection(
                name="ecommerce_kb",
                metadata={"hnsw:space": "cosine", "dim": "128"},
            )
        _use_chroma = True
        logger.info("ChromaDB ready at %s", settings.chroma_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("Chroma unavailable, fallback to in-memory store: %s", e)
        _use_chroma = False
        _collection = _MemoryCollection()
    return _collection


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


async def ingest_chunks(chunks: list[Chunk]) -> int:
    if not chunks:
        return 0
    col = _get_collection()
    texts = [c.text for c in chunks]
    embs = await embed_texts(texts)
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
        # chroma upsert
        col.upsert(ids=ids, embeddings=embs, documents=texts, metadatas=metadatas)
    else:
        col.add(ids=ids, embeddings=embs, documents=texts, metadatas=metadatas)
    logger.info("ingested %s chunks (chroma=%s)", len(ids), _use_chroma)
    return len(ids)


async def ingest_knowledge_dir() -> int:
    chunks = chunk_directory()
    return await ingest_chunks(chunks)


async def similarity_search(query: str, k: int | None = None) -> list[dict[str, Any]]:
    k = k or settings.rag_top_k
    col = _get_collection()
    try:
        count = col.count()
    except Exception:  # noqa: BLE001
        count = 0
    if count == 0:
        return []
    qvec = await embed_query(query)
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
