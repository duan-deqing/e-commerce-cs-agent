# 坏案例回归测试报告

- **运行时间**：2026-09-18 02:03:34
- **运行模式**：`regress(badcases)`（坏案例回归集）
- **模型**：qwen3.7-flash（真实 LLM，非 Mock）
- **Prompt 版本**：v1（灰度 0%，全量基线版本）
- **回归集**：`badcases.jsonl`，5 条，覆盖 4 类失败模式
- **复现命令**：`python backend/scripts/run_eval.py --regress`
- **报告数据**：`report-regress.json`

## 一、总体结论

**5/5 条历史坏案例全部未复现**，当前 v1 基线已通过全部回归项。

| 指标 | 结果 | 说明 |
|---|---|---|
| 意图正确率 | **1.0**（5/5） | b02 投诉、b04 乱码等易误判样本均路由正确 |
| 引用覆盖率 | **1.0**（2/2） | 有知识库依据的 b01/b05 均带来源 |
| Recall@5 | **1.0**（2/2） | golden 文档均进入 top-5 |
| fallback 率 | 0.2（1/5） | 仅 b04 乱码输入，**属预期行为**而非失败 |
| 置信度分布 | 5/5 落在 0.8-1.0 | 无低置信硬答 |
| 答案准确率（judge） | **1.0**（n=3） | 可判定样本全部正确 |
| **幻觉率（judge）** | **0.0** | 无编造事实 |
| 忠诚度（judge） | 0.667 | 1 条 faithful + 2 条 partial，见遗留观察 |
| 平均时延 | 14.9s | 真实 LLM 含检索与工具调用 |

## 二、逐条明细

| ID | 分类 | 问题 | 当前行为 | Judge | 结论 |
|---|---|---|---|---|---|
| b01 | hallucinated | 保温杯能直接煮鸡蛋吗？ | intent=product_inquiry conf=0.95，引用 2 条商品手册来源 | correct=true，faithful=partial | **通过**：未编造煮制方法，基于知识库回答 |
| b02 | wrong_intent | 我买的手机屏幕碎了你们必须赔 | intent=complaint conf=0.95 | 跳过（无资料可判） | **通过**：投诉+归责混合表述未误判为 fallback |
| b03 | tool_fail | 查一下订单 ORD99999999 | intent=order_query conf=0.98，工具返回 found=false 后礼貌兜底 | correct=true，faithful=partial | **通过**：未编造订单信息 |
| b04 | low_conf | asdfghjkl | intent=fallback conf=0.95 | 跳过（无资料可判） | **通过**：乱码输入走 fallback 引导，未硬答 |
| b05 | hallucinated | 618 满减是全场无门槛直接减吗？ | intent=promotion_query conf=0.86，引用 5 条活动规则来源 | correct=true，faithful=faithful | **通过**：依据活动规则纠正了错误前提，无诱导 |

## 三、Judge 口径说明

- LLM judge 输入【问题】【客服回答】【参考资料】，输出 `{"correct": bool, "faithful": "faithful"|"partial"|"unfaithful"}`
- **无资料可判时跳过**（无检索片段且无工具结果），本轮 b02/b04 属此类，n=3
- 忠诚度 = (faithful×1 + partial×0.5) / n；幻觉率 = unfaithful / n
- 忠诚度 0.667 = (1 + 0.5×2) / 3（b01、b03 为 partial）

## 四、遗留观察（v2 优化点）

1. **b01 / b03 忠诚度 partial**：答案正确但存在超出参考资料/工具结果的表述倾向，v2 prompt（回答控制在 3 句话以内、只给关键信息）针对此项优化，可通过灰度验证后全量
2. **b04 fallback 率 0.2 为预期**：低置信/乱码输入本应 fallback，该样本不计入坏信号

## 五、闭环机制

```
线上 trace / 评测发现坏案例
        │  按 category 归类：hallucinated / wrong_intent / tool_fail / low_conf
        ▼
badcases.jsonl 入库（含 source_trace_id 溯源、note 记录期望行为）
        │  python backend/scripts/run_eval.py --regress
        ▼
回归验证（每次 prompt/检索/工具改动后必跑）
        │  新版 prompt = v2（PROMPT_VERSIONS 注册）
        ▼
灰度发布（PROMPT_GRAY_PERCENT=50，crc32(session_id) 稳定分流，同一会话版本不变）
        │  指标达标 → 提至 100；劣化 → 回滚
        ▼
回滚开关（PROMPT_VERSION=v1 + PROMPT_GRAY_PERCENT=0，立即全量切回稳定版）
```

> 注：本轮回归基于 v1 全量基线。坏案例在 v1 下已全部通过，说明其对应的历史失败模式（编造煮制方法、意图误判、编造订单、乱码硬答、诱导确认）在当前检索+结构化工具结果+护栏体系下已有防护；v2 上线后需重跑本回归确认无退化。
