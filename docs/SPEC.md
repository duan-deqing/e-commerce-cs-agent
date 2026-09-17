# 电商智能客服服务平台 — 后端 Spec

> 版本：v0.1.0（仅后端）  
> 技术栈：Python 3.11+ / FastAPI / LangChain / LCEL / ChromaDB / OpenAI 兼容协议 / Tavily

---

## 1. 项目目标

面向电商业务的智能客服 Agent 后端平台，覆盖：

| 业务域 | 能力 |
|--------|------|
| 订单 | 下单状态、明细、取消、发票等实时查询 |
| 物流 | 运单轨迹、预计送达、异常件 |
| 商品咨询 | 参数、规格、库存、使用说明（RAG） |
| 售后 | 退换货进度、工单状态机闭环 |
| 促销 | 活动规则、优惠计算（RAG + 工具） |
| 投诉 / 其他 | 情绪安抚、升级人工、兜底澄清 |

核心链路：

```
用户消息 → 脱敏 → 意图识别 → 路由
              ├─ 业务工具链（并行调用 / 重试 / 降级）
              ├─ RAG 知识问答（召回 + 重排 + 溯源）
              ├─ 售后状态机（工单流转）
              └─ 兜底澄清 / 人工转接
                    ↓
              LLM 流式生成（SSE）→ 风控校验 → 输出
```

---

## 2. 非功能目标（对齐简历指标）

| 指标 | 目标值 | 实现要点 |
|------|--------|----------|
| 意图识别准确率 | ≥ 92% | 零样本 Prompt + 显式意图枚举 + 置信度阈值 |
| 工具调用成功率 | ≥ 95% | 参数校验、重试（指数退避）、降级到 FAQ |
| RAG Top-5 召回 | ≥ 85% | 语义分块 + 向量召回 + Rerank |
| 回答准确率 / 幻觉率 | 86% / ≤ 8% | 来源溯源、无命中则拒答并转人工 |
| 首 Token 延迟 | ≤ 2s | SSE 流式、轻量意图链路 |
| P95 响应延迟 | ≤ 4s | 并行工具、超时熔断、上下文裁剪 |

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI (app/main.py)                  │
│  /api/v1/chat/stream  /api/v1/chat  /api/v1/health  ...     │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                 Orchestrator (Agent 编排器)                  │
│  context window · pipeline · streaming · fallback           │
└──┬──────────┬──────────┬──────────┬──────────┬──────────────┘
   │          │          │          │          │
┌──▼───┐  ┌──▼────┐  ┌──▼───┐  ┌──▼────┐  ┌──▼──────────┐
│Intent│  │Tools  │  │ RAG  │  │After- │  │Risk & Mask  │
│Router│  │Runtime│  │Chain │  │sales  │  │             │
└──┬───┘  └──┬────┘  └──┬───┘  │ SM    │  └─────────────┘
   │         │          │      └───────┘
   │    ┌────▼──────────────────┐
   │    │ order / logistics /   │
   │    │ after_sales / promo / │
   │    │ web_search            │
   │    └───────────────────────┘
   │         ┌──────────────────┐
   └────────►│ LLM Client       │
             │ (OpenAI 兼容)    │
             └──────────────────┘
```

### 分层职责

| 层 | 目录 | 职责 |
|----|------|------|
| API | `app/api/` | HTTP/SSE 路由、请求校验、响应模型 |
| Schemas | `app/schemas/` | Pydantic 入参/出参 DTO |
| Orchestrator | `app/agent/` | 入口编排 + 统一流水线（工具/RAG/生成）、流式输出、降级 |
| Intent | `app/intent/` | 11+ 意图零样本分类 |
| Tools | `app/tools/` | 业务工具封装 + LCEL 并行编排 |
| RAG | `app/rag/` | 解析、分块、Embedding、Chroma、Rerank、溯源 |
| Services | `app/services/` | 订单/物流/售后/促销 mock 业务服务 |
| Risk | `app/risk/` | 退款风控、敏感信息脱敏 |
| Core | `app/core/` | 配置、LLM 客户端、日志、异常 |
| Data | `data/` | mock 业务数据 JSON |
| Knowledge | `knowledge/` | 商品手册 / FAQ / 活动规则示例 |

---

## 4. 意图体系（12 类）

| intent_id | 名称 | 触发示例 | 处理链路 |
|-----------|------|----------|----------|
| `order_query` | 订单查询 | 我的订单到哪了 | Tool: order |
| `logistics_query` | 物流追踪 | 快递什么时候到 | Tool: logistics |
| `product_inquiry` | 商品咨询 | 这款手机支持快充吗 | RAG |
| `after_sales_return` | 退货 | 我要退货 | After-sales SM + Tool |
| `after_sales_exchange` | 换货 | 换个颜色 | After-sales SM + Tool |
| `after_sales_progress` | 售后进度 | 退款处理到哪一步了 | After-sales SM + Tool |
| `refund_query` | 退款查询 | 钱什么时候退回来 | Tool: after_sales |
| `promotion_query` | 促销活动 | 618 有什么优惠 | RAG + Tool: promo |
| `complaint` | 投诉 | 你们服务太差了 | 情绪安抚 + 升级策略 |
| `human_handoff` | 转人工 | 找人工客服 | 直接转接 |
| `greeting` | 寒暄 | 你好 / 在吗 | 欢迎语 |
| `fallback` | 兜底 | 无法识别 | 澄清反问 |

**意图识别实现**

- LangChain `PromptTemplate` + `LLM`（零样本）
- 输出强制 JSON：`{"intent": "...", "confidence": 0.0-1.0, "entities": {...}, "reason": "..."}`
- `confidence < 0.55` → `fallback` 澄清
- `confidence ∈ [0.55, 0.72)` → 可带澄清确认
- 本地规则快速通道（正则命中高置信意图，降低延迟）

**实体抽取**

- `order_id` / `tracking_no` / `ticket_id` / `product_id` / `amount` / `phone` 等
- 与上下文窗口合并，缺参时向用户追问

---

## 5. 工具编排（Tools + LCEL）

### 5.1 工具清单

| Tool | 入参 | 返回 | 后端服务 |
|------|------|------|----------|
| `query_order` | order_id 或 user_id | 订单状态/明细 | OrderService |
| `query_logistics` | tracking_no / order_id | 轨迹列表 | LogisticsService |
| `create_return` | order_id, reason | 售后工单 | AfterSalesService |
| `create_exchange` | order_id, variant | 售后工单 | AfterSalesService |
| `query_after_sales` | ticket_id | 工单状态 | AfterSalesService |
| `query_refund` | ticket_id / order_id | 退款进度 | AfterSalesService |
| `query_promotion` | campaign / category | 活动规则摘要 | PromotionService |
| `web_search` | query | Tavily 搜索摘要 | Tavily API（可选） |

### 5.2 LCEL 编排策略

```
RunnableParallel(
  tools=[selected tools]
) → 合并器 → 上下文注入 Prompt → LLM 生成
```

1. **参数校验**：Pydantic schema，失败则向用户要参数  
2. **并行调用**：`RunnableParallel` 同时拉订单+物流  
3. **重试**：单工具最多 2 次，指数退避 0.3s / 0.9s  
4. **超时**：单工具 3s，整体工具阶段 5s  
5. **降级**：工具全失败 → RAG FAQ；RAG 也无命中 → 礼貌兜底 + 建议转人工  
6. **结果合并**：结构化 `ToolResult` 列表注入 system/context

### 5.3 ToolResult 契约

```json
{
  "tool": "query_order",
  "success": true,
  "data": { },
  "error": null,
  "latency_ms": 42,
  "retried": 0
}
```

---

## 6. RAG 知识问答

### 6.1 文档类型

- 商品手册 `knowledge/products/*.md`
- FAQ `knowledge/faq/*.md`
- 活动规则 `knowledge/promotions/*.md`

### 6.2 处理流水线

```
解析 → 语义分块 → Embedding → ChromaDB 持久化
用户问题 → Query Embedding → Top-K 召回(默认 K=15)
         → Rerank(保留 Top-5) → 注入 Prompt → LLM
```

- 分块：`chunk_size=500`，`overlap=80`；标题层级优先切分  
- Embedding：OpenAI 兼容 `/v1/embeddings`（可配本地 mock）  
- 存储：ChromaDB 持久化目录 `.chroma/`  
- Rerank：本地交叉打分（关键词重叠 + 向量距离融合）；可切换外部 Rerank API  
- **溯源**：回答附带 `sources: [{doc_id, title, score, snippet}]`  
- **无命中**：`score < threshold` 时拒答幻觉，改为「未查到相关规则，建议…」

### 6.3 入库命令

```bash
python -m app.rag.ingest
```

---

## 7. 售后对话状态机

```
idle → collecting_info → confirming → submitted → processing
                                      ↘ rejected
processing → waiting_user → completed
processing → escalated (人工)
```

| 状态 | 行为 |
|------|------|
| collecting_info | 收集订单号、原因、凭证说明 |
| confirming | 展示将提交的信息，等用户确认 |
| submitted | 创建工单，返回 ticket_id |
| processing | 查询物流签收/质检进度 |
| waiting_user | 要求补充凭证或地址 |
| completed | 退款完成 / 换货寄出 |
| escalated | 高风险或用户明确要求转人工 |

事件由意图 + 实体 + 用户确认词驱动；状态与上下文绑定 `session_id`。

---

## 8. 服务稳定性与风控

### 8.1 滑动上下文窗口

- 默认保留最近 `12` 轮（可配置）
- 超长时按 token 估算裁剪最旧消息
- 每轮缓存意图与关键实体，避免重复追问

### 8.2 敏感数据脱敏（输入前 / 输出前）

| 类型 | 策略 |
|------|------|
| 手机号 | `138****5678` |
| 身份证 | 保留前 3 后 4 |
| 银行卡 | 保留后 4 位 |
| 邮箱 | `a***@example.com` |
| 收货地址 | 保留市/区，抹平详细门牌 |

### 8.3 高金额退款风控

- 阈值默认 `¥2000`（可配）
- 触发后：不直接同意，生成人工审核提示，工单标记 `risk_hold`
- 连续多次退款 / 高频投诉 → 建议转人工

### 8.4 LLM 故障降级

| 故障 | 策略 |
|------|------|
| 意图 LLM 超时/失败 | 本地规则分类器 |
| 生成 LLM 失败 | 模板化工具结果摘要 |
| Embedding 失败 | 关键词 FAQ 匹配 |
| 全链路失败 | 统一兜底话术 + 人工入口 |

### 8.5 SSE 流式

- `POST /api/v1/chat/stream` → `text/event-stream`
- 事件类型：`intent` / `tool_start` / `tool_result` / `sources` / `token` / `done` / `error`
- 首包优先推意图与工具进度，降低体感延迟

---

## 9. API 设计

### 9.1 会话流式对话

```http
POST /api/v1/chat/stream
Content-Type: application/json

{
  "session_id": "s_abc",
  "user_id": "u_1001",
  "message": "我的订单 ORD20260301001 到哪了"
}
```

SSE 响应事件见 8.5。

### 9.2 非流式对话

```http
POST /api/v1/chat
```

返回完整 JSON：`intent`、`answer`、`sources`、`tools`、`handoff`、`risk_flags`。

### 9.3 其他接口

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/health` | 存活与依赖状态 |
| GET | `/api/v1/intents` | 意图枚举 |
| POST | `/api/v1/knowledge/reindex` | 重建知识库索引 |
| GET | `/api/v1/sessions/{id}` | 会话上下文摘要 |
| GET | `/metrics` | 简易指标（QPS/延迟/意图分布） |

---

## 10. 配置（环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `APP_ENV` | `dev` | dev/prod |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 |
| `LLM_API_KEY` | 空 | 空则 mock LLM |
| `LLM_MODEL` | `gpt-4o-mini` | 对话模型 |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | 向量模型 |
| `TAVILY_API_KEY` | 空 | 空则禁用 web_search |
| `CHROMA_PERSIST_DIR` | `.chroma` | 向量库目录 |
| `RAG_TOP_K` | `15` | 初召回 |
| `RAG_RERANK_TOP_N` | `5` | 精排 |
| `REFUND_RISK_THRESHOLD` | `2000` | 风控金额 |
| `CONTEXT_MAX_TURNS` | `12` | 上下文轮数 |
| `TOOL_TIMEOUT_S` | `3.0` | 单工具超时 |
| `MOCK_LLM` | `auto` | auto/true/false |

---

## 11. 项目结构

```
e-commerce-cs-agent/
├── README.md                   # 全栈仓库说明
├── docs/SPEC.md                # 本设计文档
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── main.py             # FastAPI 入口
│   │   ├── api/                # chat / admin / health
│   │   ├── agent/              # orchestrator / pipeline / continuity / after_sales_flow
│   │   ├── intent/             # 意图 + 实体
│   │   ├── tools/              # 业务工具 + 并行运行时
│   │   ├── rag/                # RAG 链路
│   │   ├── services/           # mock 业务服务
│   │   ├── risk/               # 脱敏、风控
│   │   ├── state/              # 会话与售后状态机
│   │   ├── schemas/
│   │   └── core/               # 配置、LLM、日志、指标
│   ├── data/                   # mock 业务数据
│   ├── knowledge/              # RAG 语料
│   ├── scripts/smoke_test.py
│   ├── requirements.txt
│   ├── run.py
│   └── .env.example
└── frontend/                   # 前端（规划中）
    └── README.md
```

---

## 12. 里程碑

| 阶段 | 内容 | 状态 |
|------|------|------|
| M1 | Spec + 目录骨架 + 配置 | 本版 |
| M2 | 意图识别 + 会话 + 脱敏 + FastAPI 骨架 | 本版 |
| M3 | 业务 Tools + LCEL 编排 + mock 数据 | 本版 |
| M4 | RAG 入库/召回/重排/溯源 | 本版 |
| M5 | 售后状态机 + 风控 + SSE 流式 | 本版 |
| M6 | 评估脚本 / 压测 / 生产部署（后续） | 待做 |

---

## 13. 明确不做（本阶段）

- 前端 UI / 管理后台
- 真实支付与真实电商中台对接（用 mock 服务）
- 多租户鉴权与计费
- 向量库集群与分布式部署
