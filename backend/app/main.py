from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin_router, chat_router, health_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.tools import bootstrap_tools


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    bootstrap_tools()
    # 尽力预建索引；失败不阻断启动
    try:
        from app.rag.vectorstore import ingest_knowledge_dir

        n = await ingest_knowledge_dir()
        print(f"[startup] knowledge chunks ready: {n}")
    except Exception as e:  # noqa: BLE001
        print(f"[startup] knowledge ingest skipped: {e}")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="电商智能客服服务平台",
        description="意图识别 · 工具编排 · RAG 问答 · 售后状态机 · 风控脱敏",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(chat_router)
    app.include_router(admin_router)
    app.include_router(health_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "dev",
    )
