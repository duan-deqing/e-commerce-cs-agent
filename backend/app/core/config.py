"""应用配置：从环境变量 / .env 读取，全局单例 settings。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # 简易鉴权：配置后要求请求头 X-API-Key 与之相等（空则关闭，便于本地调试）
    api_key: str = ""
    # CORS 白名单，逗号分隔；空则 dev 用 *，非 dev 收紧为空（需显式配置）
    cors_origins: str = ""

    # 会话内存上限
    session_ttl_seconds: int = 1800
    session_max_size: int = 5000

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    mock_llm: str = "auto"  # auto | true | false
    # 思考型模型（DashScope qwen3 / DeepSeek-R1 等）思考开关：
    # auto=不下发参数（跟随端点默认）；false=enable_thinking:false，显著降低首 token 延迟（意图分类同步受益）
    llm_enable_thinking: str = "auto"

    tavily_api_key: str = ""

    chroma_persist_dir: str = str(BASE_DIR / ".chroma")
    rag_top_k: int = 15
    rag_rerank_top_n: int = 5
    rag_score_threshold: float = 0.35
    chunk_size: int = 500
    chunk_overlap: int = 80

    refund_risk_threshold: float = 2000.0
    context_max_turns: int = 12
    tool_timeout_s: float = 3.0
    tool_max_retries: int = 2

    # 监控：输出长度上限与 Token 单价（$/1k tokens，用于成本估算）
    max_output_tokens: int = 800
    llm_price_prompt_per_1k: float = 0.00015
    llm_price_completion_per_1k: float = 0.0006

    # Prompt 版本与灰度百分比（0-100）：按 session_id 哈希路由到不同 prompt 版本
    prompt_version: str = "v1"
    prompt_gray_percent: int = 0

    knowledge_dir: str = str(BASE_DIR / "knowledge")
    data_dir: str = str(BASE_DIR / "data")
    db_path: str = str(BASE_DIR / "data" / "app.db")

    @property
    def use_mock_llm(self) -> bool:
        if self.mock_llm.lower() == "true":
            return True
        if self.mock_llm.lower() == "false":
            return False
        return not bool(self.llm_api_key.strip())

    @property
    def knowledge_path(self) -> Path:
        p = Path(self.knowledge_dir)
        return p if p.is_absolute() else BASE_DIR / p

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else BASE_DIR / p

    @property
    def backend_root(self) -> Path:
        return BASE_DIR

    @property
    def chroma_path(self) -> Path:
        p = Path(self.chroma_persist_dir)
        return p if p.is_absolute() else BASE_DIR / p

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if raw:
            return [x.strip() for x in raw.split(",") if x.strip()]
        return ["*"] if self.app_env == "dev" else []


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
