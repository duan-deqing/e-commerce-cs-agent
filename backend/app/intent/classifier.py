"""意图分类：本地规则快通道 + LLM 零样本分类，输出统一 JSON。"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.llm import BaseLLM, get_llm
from app.core.logging import get_logger
from app.intent.entities import extract_entities
from app.intent.labels import INTENT_META, Intent

logger = get_logger(__name__)

INTENT_PROMPT = """你是电商客服意图分类器。根据用户消息判断意图，只输出 JSON，不要解释。

可选意图：
{intent_list}

输出格式：
{{"intent": "<intent_id>", "confidence": 0.0到1.0, "entities": {{}}, "reason": "简短原因"}}

规则：
1. confidence 必须是 0-1 的小数
2. entities 只抽取明确出现的字段：order_id, tracking_no, ticket_id, phone, amount, reason, product_kw
3. 拿不准时降低 confidence，不要乱猜 intent
4. 用户要求人工/转客服 → human_handoff
5. 用户骂人/投诉服务 → complaint

用户消息：{user_message}
"""

# 高置信本地规则（降低首包延迟，LLM 作为补充/兜底）
_RULES: list[tuple[re.Pattern, Intent, float]] = [
    (re.compile(r"转人工|人工客服|找人工|真人", re.I), Intent.HUMAN_HANDOFF, 0.96),
    (re.compile(r"投诉|差评|骗子|垃圾|态度差|举报", re.I), Intent.COMPLAINT, 0.9),
    (re.compile(r"退货|退款申请|不想要了|申请退|我要退|想退", re.I), Intent.AFTER_SALES_RETURN, 0.88),
    (re.compile(r"换货|换一个|换个颜色|换尺码|换规格|我要换", re.I), Intent.AFTER_SALES_EXCHANGE, 0.88),
    (
        re.compile(r"售后.*进度|工单.*进度|退换.*到哪|处理到哪", re.I),
        Intent.AFTER_SALES_PROGRESS,
        0.86,
    ),
    (re.compile(r"退款.*(到|进度|多久)|钱.*退", re.I), Intent.REFUND_QUERY, 0.85),
    (re.compile(r"物流|快递|运单|到哪了|什么时候到|发货了吗", re.I), Intent.LOGISTICS_QUERY, 0.84),
    (re.compile(r"订单(状态|查询|号)|我(的)?订单|买了什么", re.I), Intent.ORDER_QUERY, 0.84),
    (
        re.compile(r"优惠|满减|折扣|活动|618|双11|优惠券|秒杀", re.I),
        Intent.PROMOTION_QUERY,
        0.86,
    ),
    (
        re.compile(r"支持|参数|规格|材质|续航|尺码|怎么用|说明书|容量|保修|快充|防水|偏码", re.I),
        Intent.PRODUCT_INQUIRY,
        0.8,
    ),
    (re.compile(r"^(你好|您好|hi|hello|在吗|在么)[\s!！。.~]*$", re.I), Intent.GREETING, 0.92),
]


def rule_classify(text: str) -> dict[str, Any] | None:
    for pat, intent, conf in _RULES:
        if pat.search(text):
            return {
                "intent": intent.value,
                "confidence": conf,
                "entities": extract_entities(text),
                "reason": "local-rule",
                "source": "rule",
            }
    return None


def _build_intent_list() -> str:
    lines = []
    for k, v in INTENT_META.items():
        lines.append(f"- {k.value}: {v['desc']}")
    return "\n".join(lines)


def _normalize(raw: str, user_message: str) -> dict[str, Any]:
    text = raw.strip()
    # 提取 JSON 块
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"invalid intent json: {text[:200]}")
    data = json.loads(m.group(0))
    intent_id = str(data.get("intent", "fallback")).strip()
    valid = {i.value for i in Intent}
    if intent_id not in valid:
        intent_id = Intent.FALLBACK.value
    try:
        conf = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    local_entities = extract_entities(user_message)
    llm_entities = data.get("entities") or {}
    merged = {**local_entities}
    for k, v in llm_entities.items():
        if v not in (None, "", [], {}):
            merged[k] = v
    return {
        "intent": intent_id,
        "confidence": conf,
        "entities": merged,
        "reason": str(data.get("reason", ""))[:120],
        "source": "llm",
    }


class IntentClassifier:
    def __init__(self, llm: BaseLLM | None = None) -> None:
        self.llm = llm or get_llm()

    async def classify(self, user_message: str, prefer_llm: bool = False) -> dict[str, Any]:
        text = (user_message or "").strip()
        if not text:
            return {
                "intent": Intent.FALLBACK.value,
                "confidence": 0.3,
                "entities": {},
                "reason": "empty",
                "source": "rule",
            }

        if not prefer_llm:
            rule = rule_classify(text)
            if rule and rule["confidence"] >= 0.84:
                return rule

        prompt = INTENT_PROMPT.format(intent_list=_build_intent_list(), user_message=text)
        try:
            raw = await self.llm.chat(
                system=prompt,
                messages=[{"role": "user", "content": text}],
                temperature=0.0,
                max_tokens=400,
            )
            result = _normalize(raw, text)
        except Exception as e:  # noqa: BLE001
            logger.warning("intent llm failed: %s", e)
            result = rule_classify(text) or {
                "intent": Intent.FALLBACK.value,
                "confidence": 0.45,
                "entities": extract_entities(text),
                "reason": f"llm-error:{e}",
                "source": "fallback",
            }

        if result["confidence"] < 0.55:
            result["intent"] = Intent.FALLBACK.value
            result["low_confidence"] = True
        return result
