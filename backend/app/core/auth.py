"""简易 API Key 鉴权：settings.api_key 非空时校验 X-API-Key 头。"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected = (settings.api_key or "").strip()
    if not expected:
        return  # 未配置则关闭鉴权（本地演示）
    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-API-Key",
        )
