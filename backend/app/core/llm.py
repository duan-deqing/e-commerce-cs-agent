"""LLM / Embedding 客户端。

- OpenAICompatLLM：对接任意 OpenAI 兼容端点
- MockLLM：无 API Key 时的离线可运行实现
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class StreamChunk:
    """流式增量：kind = reasoning（模型思考，如 qwen3 reasoning_content）| content（正式回答）。"""

    kind: str
    text: str


def _apply_thinking(payload: dict[str, Any]) -> None:
    """思考型模型开关（DashScope qwen3 等）：auto 不下发参数跟随端点默认。"""
    thinking = settings.llm_enable_thinking.strip().lower()
    if thinking in {"true", "false"}:
        payload["enable_thinking"] = thinking == "true"


class BaseLLM(ABC):
    @abstractmethod
    async def chat(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 800,
        usage_out: dict[str, Any] | None = None,
    ) -> str:
        """usage_out 非空时填充 {prompt_tokens, completion_tokens, estimated}。"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 800,
        usage_out: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


def _fill_usage_estimated(usage_out: dict[str, Any] | None, system: str, messages: list[dict[str, str]], answer: str) -> None:
    """端点未返回 usage 时按字符数/2 估算，并打 estimated 标记。"""
    if usage_out is None:
        return
    prompt_chars = len(system) + sum(len(m.get("content", "")) for m in messages)
    usage_out.setdefault("prompt_tokens", prompt_chars // 2)
    usage_out.setdefault("completion_tokens", len(answer) // 2)
    usage_out["estimated"] = True


class OpenAICompatLLM(BaseLLM):
    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.embedding_model = settings.embedding_model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 800,
        usage_out: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        _apply_thinking(payload)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            if usage_out is not None:
                usage = data.get("usage") or {}
                if usage.get("prompt_tokens") is not None:
                    usage_out["prompt_tokens"] = int(usage["prompt_tokens"])
                    usage_out["completion_tokens"] = int(usage.get("completion_tokens") or 0)
                    usage_out["estimated"] = False
                else:
                    _fill_usage_estimated(usage_out, system, messages, answer)
            return answer

    async def chat_stream(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 800,
        usage_out: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        base_payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        _apply_thinking(base_payload)

        async def _attempt(include_usage: bool) -> AsyncIterator[StreamChunk]:
            payload = dict(base_payload)
            if include_usage:
                # 部分端点不支持该参数（会 400），由外层捕获后去掉重试
                payload["stream_options"] = {"include_usage": True}
            got_usage = False
            parts: list[str] = []
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            obj = json.loads(chunk)
                            if usage_out is not None and obj.get("usage"):
                                usage_out["prompt_tokens"] = int(obj["usage"].get("prompt_tokens") or 0)
                                usage_out["completion_tokens"] = int(
                                    obj["usage"].get("completion_tokens") or 0
                                )
                                usage_out["estimated"] = False
                                got_usage = True
                            delta = obj["choices"][0].get("delta", {})
                            # 思考型模型（qwen3 / DeepSeek-R1 等）：思考先于正文产出，
                            # 透出为 reasoning 增量，避免用户在思考阶段长时间无反馈
                            reasoning = delta.get("reasoning_content")
                            if reasoning:
                                yield StreamChunk("reasoning", reasoning)
                            content = delta.get("content")
                            if content:
                                parts.append(content)
                                yield StreamChunk("content", content)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
            if usage_out is not None and not got_usage:
                _fill_usage_estimated(usage_out, system, messages, "".join(parts))

        try:
            async for token in _attempt(True):
                yield token
        except httpx.HTTPStatusError as e:
            # 400 只会发生在首字节前（raise_for_status 处），尚无 token 产出，重试安全
            if e.response.status_code != 400:
                raise
            async for token in _attempt(False):
                yield token

    async def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.embedding_model, "input": texts}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code >= 400:
                body = resp.text[:500]
                raise RuntimeError(
                    f"embedding API {resp.status_code}, model={self.embedding_model}: {body}"
                )
            data = resp.json()
            return [item["embedding"] for item in data["data"]]


class MockLLM(BaseLLM):
    """无 API Key 时的本地可运行实现，保证端到端链路可演示。"""

    async def chat(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 800,
        usage_out: dict[str, Any] | None = None,
    ) -> str:
        user_msg = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        # 仅当系统提示明确是意图分类任务时才返回 JSON
        if ("可选意图" in system or "intent_id" in system) and "当前意图" not in system:
            answer = self._mock_intent(user_msg)
        elif "重排" in system or "rerank" in system.lower():
            answer = "0.82"
        elif "摘要" in system and "压缩" in system:
            # 摘要请求：返回截断的对话要点，避免客服话术污染 session.summary
            answer = user_msg[:80]
        else:
            answer = self._mock_answer(user_msg, system)
        _fill_usage_estimated(usage_out, system, messages, answer)
        return answer

    async def chat_stream(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 800,
        usage_out: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        text = await self.chat(system, messages, temperature, max_tokens, usage_out)
        # 模拟流式：按句切分
        parts = re.split(r"(?<=[。！？\n])", text)
        for p in parts:
            if p:
                yield StreamChunk("content", p)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # 确定性伪向量：字符 unigram + 2-gram 哈希，保证本地可检索
        out: list[list[float]] = []
        dim = 128
        for t in texts:
            vec = [0.0] * dim
            s = t.lower()
            for i, ch in enumerate(s):
                vec[ord(ch) % dim] += 1.0
                if i + 1 < len(s):
                    bigram = s[i : i + 2]
                    # 稳定哈希，避免 PYTHONHASHSEED 导致入库/查询不一致
                    h = (ord(bigram[0]) * 131 + ord(bigram[1])) % dim
                    vec[h] += 0.8
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out

    def _mock_intent(self, text: str) -> str:
        mapping = [
            (r"退货|退款|不想要", "after_sales_return"),
            (r"换货|换一个|换个颜色", "after_sales_exchange"),
            (r"售后|工单|进度", "after_sales_progress"),
            (r"物流|快递|到哪|发货|签收", "logistics_query"),
            (r"订单|下单|买了什么", "order_query"),
            (r"优惠|活动|促销|618|双11|满减|折扣", "promotion_query"),
            (r"投诉|差评|垃圾|骗子", "complaint"),
            (r"人工|客服转|找人", "human_handoff"),
            (r"你好|在吗|hello|hi", "greeting"),
            (r"怎么样|支持|参数|规格|材质|续航|尺码", "product_inquiry"),
        ]
        for pat, intent in mapping:
            if re.search(pat, text, re.I):
                conf = 0.9 if len(text) > 4 else 0.75
                return json.dumps(
                    {
                        "intent": intent,
                        "confidence": conf,
                        "entities": self._extract_entities(text),
                        "reason": "rule-match",
                    },
                    ensure_ascii=False,
                )
        return json.dumps(
            {
                "intent": "fallback",
                "confidence": 0.4,
                "entities": {},
                "reason": "no-match",
            },
            ensure_ascii=False,
        )

    def _extract_entities(self, text: str) -> dict[str, Any]:
        entities: dict[str, Any] = {}
        m = re.search(r"(ORD\d{8,}|订单号?[:：]?\s*(\w{8,}))", text)
        if m:
            entities["order_id"] = re.sub(r"^(ORD|订单号?[:：]?\s*)", "", m.group(0), flags=re.I)
            if not entities["order_id"].startswith("ORD") and re.search(r"ORD", m.group(0), re.I):
                entities["order_id"] = m.group(0).strip()
        m = re.search(r"(YT\d{7,}|\d{10,})", text)
        if m and "物流" in text or "快递" in text:
            entities["tracking_no"] = m.group(1) if m.lastindex else m.group(0)
        m = re.search(r"TK\d{6,}", text)
        if m:
            entities["ticket_id"] = m.group(0)
        m = re.search(r"(\d+(?:\.\d+)?)\s*元", text)
        if m:
            entities["amount"] = float(m.group(1))
        return entities

    def _mock_answer(self, user_msg: str, system: str) -> str:
        # 优先根据注入的业务数据生成可读回答
        if "tracking_no" in system or "运单" in system or "快递员" in system or "派送" in system or "carrier" in system:
            return "包裹最新轨迹：运输中/派送中，具体节点见业务数据。预计近期送达，请保持电话畅通。"
        if "ORD" in system and ("status" in system or "状态" in system or "已发货" in system or "已签收" in system):
            return (
                "已为您查询到订单：当前状态可在下方业务数据中确认。"
                "如需物流轨迹，请提供运单号，或告诉我继续追踪快递。"
            )
        if "ticket_id" in system or "工单" in system or "refund" in system.lower():
            return "已查询到售后/退款信息：处理中将按原路退回，一般 1-3 个工作日到账。如有异常可转人工加急。"
        if "campaign" in system or "满减" in system or "618" in system:
            return "当前活动包含跨店满减与品类折扣，具体门槛见活动规则。结算页会自动择优。"
        if "资料" in system or "知识库" in system or "商品" in system:
            snippet = ""
            m = re.search(
                r"(?:知识资料|资料)[^\n]*：\n(.{10,500})",
                system,
                re.S,
            )
            if m:
                snippet = re.split(r"历史对话|当前意图|业务数据", m.group(1))[0]
                snippet = re.sub(r"\s+", " ", snippet).strip()[:240]
            base = "根据商品/活动资料："
            if snippet and not snippet.startswith("（无）"):
                return f"{base}{snippet}。如需更细说明可继续提问。"
            return (
                f"{base}该商品支持主流使用场景，并提供 7 天无理由退换（未拆封）。"
                "详细参数以商品页与说明书为准。"
            )
        if "found" in system and ("False" in system or "false" in system):
            return "抱歉，没有查到对应记录，请核对单号，或提供更多信息后我再帮您查一次。"
        return (
            "您好，我是电商智能客服。可以帮您处理订单查询、物流追踪、商品咨询、"
            "售后退换与活动规则等问题。请问具体需要哪方面帮助？"
        )


_llm: BaseLLM | None = None


def get_llm() -> BaseLLM:
    global _llm
    if _llm is None:
        if settings.use_mock_llm:
            logger.info("Using MockLLM (no API key or MOCK_LLM enabled)")
            _llm = MockLLM()
        else:
            logger.info("Using OpenAI-compatible LLM at %s", settings.llm_base_url)
            _llm = OpenAICompatLLM()
    return _llm


def set_llm(llm: BaseLLM) -> None:
    global _llm
    _llm = llm
