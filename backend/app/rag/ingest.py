"""知识库入库 CLI：python -m app.rag.ingest"""
from __future__ import annotations

import asyncio
import sys

from app.core.logging import setup_logging
from app.rag.vectorstore import ingest_knowledge_dir


async def main() -> int:
    setup_logging()
    n = await ingest_knowledge_dir()
    print(f"OK: ingested {n} chunks")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
