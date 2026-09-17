# Backend — 电商智能客服服务平台

基于 **Python + FastAPI** 的智能客服 Agent 后端：意图识别与路由、业务工具并行编排、RAG 知识问答、售后状态机、SSE 流式输出、风控脱敏与故障降级。

| 项 | 说明 |
|----|------|
| 运行时 | Python 3.11+（推荐 3.12+） |
| Web 框架 | FastAPI + Uvicorn |
| 向量库 | ChromaDB（不可用时自动降级内存检索） |
| 模型协议 | OpenAI 兼容（OpenAI / DeepSeek / DashScope / Ollama 等） |
| 无 Key 模式 | 内置 Mock LLM，可离线跑通全链路 |
| 默认端口 | `8000` |

完整设计文档：[../docs/SPEC.md](../docs/SPEC.md)

---

## 功能特性

### 1. 意图识别与智能路由
- 覆盖 **12 类**电商业务意图：订单、物流、商品咨询、退货、换货、售后进度、退款、促销、投诉、转人工、寒暄、兜底
- 本地规则快速通道（降首包延迟）+ LLM 零样本分类
- 置信度阈值分流：低置信走澄清反问
- 实体抽取：订单号、运单号、工单号、金额、原因等

### 2. 业务工具编排
| 工具 | 能力 |
|------|------|
| `query_order` | 订单状态 / 明细 |
| `query_logistics` | 物流轨迹 / 预计送达 |
| `create_return` / `create_exchange` | 售后建单 |
| `query_after_sales` / `query_refund` | 工单与退款进度 |
| `query_promotion` | 活动规则 |
| `web_search` | Tavily 全网搜索（可选） |

编排能力：参数校验 → 并行调用 → 指数退避重试 → 超时熔断 → 工具失败降级 RAG/话术。

### 3. RAG 知识问答
- Markdown 语义分块（标题优先 + 句边界）
- Embedding 入库 ChromaDB，Top-K 召回 + 关键词/向量融合重排（Top-5）
- 回答附带 **来源溯源**（doc_id / 标题 / 片段）
- 低置信命中拒答，避免幻觉

### 4. 稳定性与风控
- SSE 流式输出（`intent` / `tool_*` / `sources` / `token` / `done`）
- 滑动上下文窗口（默认 12 轮）
- 敏感信息脱敏（手机号 / 身份证 / 银行卡 / 邮箱 / 详细地址）
- 高金额退款风控（默认 ≥ ¥2000 转人工审核）
- 售后对话状态机：收集信息 → 确认 → 建单 → 处理 / 风控升级

---

## 快速开始

### 环境准备

```powershell
cd backend

# 使用 uv（推荐）
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt

# 或使用 pip
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 配置（可选）

```powershell
Copy-Item .env.example .env
notepad .env
```

不配置 `LLM_API_KEY` 时自动使用 **Mock LLM**，本地即可演示订单/物流/售后/RAG 等链路。

### 启动

```powershell
python run.py
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

| 入口 | URL |
|------|-----|
| 服务 | http://127.0.0.1:8000 |
| Swagger UI | http://127.0.0.1:8000/docs |
| ReDoc | http://127.0.0.1:8000/redoc |
| 健康检查 | http://127.0.0.1:8000/api/v1/health |

### 冒烟测试

```powershell
# 强制 Mock（即使配置了真实 Key）
$env:MOCK_LLM='true'
python scripts/smoke_test.py
```

---

## 项目结构

```
backend/
├── app/
│   ├── main.py                 # FastAPI 入口与生命周期
│   ├── api/
│   │   ├── routes_chat.py      # /chat  /chat/stream
│   │   ├── routes_admin.py     # intents/tools/sessions/metrics/reindex
│   │   └── routes_health.py    # 健康检查
│   ├── agent/
│   │   ├── orchestrator.py     # 入口：会话准备 + 意图 + 流式/非流式 + trace 收尾
│   │   ├── pipeline.py         # 统一流水线：工具 → RAG → 生成
│   │   ├── continuity.py       # 售后确认态会话继承
│   │   ├── after_sales_flow.py # 售后追问/建单/风控短路
│   │   ├── summarizer.py       # 上下文摘要压缩（滑动窗口将满时触发）
│   │   ├── sql_agent/          # 模板化 SQL Agent（参数绑定，禁拼接）
│   │   │   ├── templates.py
│   │   │   └── agent.py
│   │   ├── prompts.py          # 系统提示词（稳定前缀 + 版本注册表/灰度路由）
│   │   └── fallback.py         # 降级与模板回答
│   ├── intent/
│   │   ├── labels.py           # 12 类意图定义
│   │   ├── classifier.py       # 规则 + LLM 分类
│   │   └── entities.py         # 实体抽取与合并
│   ├── tools/
│   │   ├── base.py             # ToolResult / 重试 / 并行 / 注册表
│   │   ├── order_tool.py
│   │   ├── logistics_tool.py
│   │   ├── after_sales_tool.py
│   │   ├── promotion_tool.py
│   │   └── search_tool.py
│   ├── rag/
│   │   ├── chunker.py          # 语义分块
│   │   ├── embeddings.py
│   │   ├── vectorstore.py      # Chroma + 内存降级
│   │   ├── reranker.py
│   │   ├── chain.py            # 检索问答链
│   │   └── ingest.py           # 入库 CLI
│   ├── services/               # 业务服务（经 SQL Agent 访问库）
│   ├── db/                     # SQLite 连接 / Schema / Seed
│   ├── risk/                   # 脱敏、退款风控
│   ├── state/session.py        # 会话窗口 + 摘要 + 售后状态机
│   ├── schemas/chat.py         # 请求/响应模型
│   └── core/                   # config / llm / logging / metrics / tracing
├── evals/                      # 离线评测：dataset.jsonl / badcases.jsonl / 报告
├── data/                       # mock 业务 JSON
├── knowledge/                  # RAG 语料（商品/FAQ/活动）
├── scripts/
│   ├── smoke_test.py           # 端到端冒烟（Mock LLM）
│   ├── run_eval.py             # 离线评测：Recall@5 / 覆盖率 / judge / 坏案例回归
│   └── verify_p2.py            # 上下文工程验证（摘要触发 / 前缀稳定）
├── requirements.txt
├── run.py
└── .env.example
```

### `app/agent/` 模块说明

`agent/` 保持**扁平结构，不再分子目录**（模块少、职责已按文件拆清，再分层只会增加跳转成本）。

| 模块 | 职责 | 调用方 |
|------|------|--------|
| `orchestrator.py` | 会话准备、脱敏、摘要触发、意图分类；非流式返回完整 JSON；流式用 Queue 转发 SSE；`_finalize` 统一记录 tokens/cost/转接/坏案例并落库 trace | `api/routes_chat.py` |
| `pipeline.py` | 统一流水线：快捷回复 → 售后预检 → 工具并行（≤4 次护栏）→ RAG → LLM 生成（max_output_tokens 上限） | `orchestrator` |
| `continuity.py` | 「确认/取消」与售后确认态下的意图继承 | `orchestrator` |
| `after_sales_flow.py` | 缺参追问、确认建单、风控/建单短路话术 | `pipeline` |
| `summarizer.py` | 滑动窗口将满时把早期对话压缩为 ≤80 字摘要，随历史注入；失败仅降级 | `orchestrator` |
| `prompts.py` | 稳定前缀 + 动态块拼装（可命中 provider 前缀缓存）；PROMPT_VERSIONS 版本注册表与 crc32 灰度路由；工具结果结构化 JSON 行 | `pipeline` |
| `fallback.py` | 寒暄/转人工/兜底/工具失败模板回答 | `pipeline` |

调用链：

```
routes_chat
  └─ orchestrator.handle_message / handle_message_stream
        ├─ continuity.apply_session_continuity
        └─ pipeline.run_pipeline
              ├─ after_sales_flow.*
              ├─ tools.run_parallel
              ├─ rag.retrieve
              └─ llm.chat / chat_stream
```

---

## API 一览

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/chat` | 非流式对话，返回完整 JSON |
| POST | `/api/v1/chat/stream` | SSE 流式对话 |
| GET | `/api/v1/health` | 存活与依赖状态 |
| GET | `/api/v1/intents` | 意图枚举 |
| GET | `/api/v1/tools` | 已注册工具 |
| GET | `/api/v1/sessions/{session_id}` | 会话摘要（意图/实体/售后状态） |
| POST | `/api/v1/knowledge/reindex` | 重建向量知识库 |
| GET | `/api/v1/metrics` | 请求量、意图分布、P50/P95、TTFT、Token/成本、错误率、转接率、自助解决率、坏案例率 |
| GET | `/api/v1/sql-templates` | SQL Agent 模板目录 |

### 非流式对话

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"u_1001\",\"session_id\":\"s_demo\",\"message\":\"查询订单 ORD20260301001\"}"
```

响应字段（节选）：

```json
{
  "session_id": "s_demo",
  "intent": "order_query",
  "intent_name": "订单查询",
  "confidence": 0.9,
  "answer": "...",
  "tools": [{ "tool": "query_order", "success": true, "data": {} }],
  "sources": [{ "doc_id": "...", "title": "...", "snippet": "..." }],
  "handoff": false,
  "risk_flags": [],
  "after_sales_state": "idle",
  "latency_ms": 12.5
}
```

### 流式对话（SSE）

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"u_1001\",\"message\":\"这款手机支持快充吗\"}"
```

事件顺序：

```
event: intent        # 意图与置信度
event: tool_start    # 工具开始
event: tool_result   # 工具结果
event: sources       # RAG 来源（如有）
event: token         # 回答增量
event: done          # 最终汇总
event: error         # 异常
```

前端解析示例（fetch + SSE）：

```ts
const res = await fetch("http://127.0.0.1:8000/api/v1/chat/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ user_id: "u_1001", message: "查询物流" }),
});
const reader = res.body!.getReader();
// 按 event/data 行解析后渲染 token / sources
```

---

## 配置说明

在 `backend/.env` 中配置（参见 `.env.example`）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `APP_HOST` / `APP_PORT` | `0.0.0.0` / `8000` | 监听地址 |
| `API_KEY` | 空 | 非空则要求请求头 `X-API-Key` |
| `CORS_ORIGINS` | 空 | 逗号分隔；dev 默认 `*` |
| `SESSION_TTL_SECONDS` | `1800` | 会话过期 |
| `SESSION_MAX_SIZE` | `5000` | 会话 LRU 上限 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 Base URL |
| `LLM_API_KEY` | 空 | 空则 Mock LLM |
| `LLM_MODEL` | `gpt-4o-mini` | 对话模型 |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | 向量模型 |
| `MOCK_LLM` | `auto` | `auto` / `true` / `false` |
| `TAVILY_API_KEY` | 空 | 全网搜索，空则关闭 |
| `CHROMA_PERSIST_DIR` | `.chroma` | 向量库目录 |
| `RAG_TOP_K` | `15` | 初召回条数 |
| `RAG_RERANK_TOP_N` | `5` | 精排后条数 |
| `RAG_SCORE_THRESHOLD` | `0.35` | 召回分数阈值 |
| `REFUND_RISK_THRESHOLD` | `2000` | 高金额退款风控（元） |
| `CONTEXT_MAX_TURNS` | `12` | 上下文保留轮数 |
| `TOOL_TIMEOUT_S` | `3.0` | 单工具超时 |
| `TOOL_MAX_RETRIES` | `2` | 工具最大重试次数 |
| `MAX_OUTPUT_TOKENS` | `800` | 单次回答输出长度上限 |
| `LLM_PRICE_PROMPT_PER_1K` | `0.00015` | Prompt Token 单价（$/1k，成本估算） |
| `LLM_PRICE_COMPLETION_PER_1K` | `0.0006` | 补全 Token 单价（$/1k，成本估算） |
| `PROMPT_VERSION` | `v1` | 全量 prompt 版本（回滚开关） |
| `PROMPT_GRAY_PERCENT` | `0` | v2 灰度百分比 0-100（crc32(session_id) 稳定分流） |

### 对接真实模型（示例）

**OpenAI**
```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=gpt-4o-mini
MOCK_LLM=false
```

**DashScope（通义）**
```env
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=qwen-plus
# Embedding 必须用向量模型 ID，不能用 qwen 对话模型名
EMBEDDING_MODEL=text-embedding-v3
MOCK_LLM=false
```

启动日志若出现 `embedding API 400`，优先检查 `EMBEDDING_MODEL` 是否为该平台合法的向量模型。

**Ollama（本地）**
```env
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:7b
MOCK_LLM=false
```

---

## 评测与监控（可观测 + 质量闭环）

### 线上监控

- 每条请求生成 `trace_id`（贯穿 SSE 事件），结束后由 `orchestrator._finalize` 旁路落库 `request_trace` 表：
  模型 / prompt 版本 / 意图与置信度 / 工具与检索片段 / TTFT / 总耗时 / Token 用量与成本 / 转接 / 错误；
  敏感输入只记录脱敏标记（0/1），不落原文；落库失败仅记日志，不阻塞主链路。
- `GET /api/v1/metrics` 返回进程内聚合：请求量、意图分布、P50/P95、TTFT P50/P95、错误率、人工转接率、
  自助解决率（= 1 − 转接率 − 错误率）、坏案例率、Token 用量与成本（端点无 usage 时按字符数估算并标记 `estimated`）。
- 查询线上指标时排除评测流量：`WHERE user_id != 'eval_user'`（离线评测与线上请求共用 trace 表）。

### 离线评测

```powershell
python scripts/run_eval.py                # 全量 30 条：Recall@5 / 意图正确率 / 引用覆盖率 / LLM judge
python scripts/run_eval.py --regress      # 坏案例回归集（5 条），产出 report-regress.json
python scripts/run_eval.py --skip-judge   # 跳过 LLM judge（Mock 模式自动跳过）
```

基线（qwen3.7-flash，prompt v1，2026-09-18）：

| 指标 | 结果 |
|------|------|
| Recall@5 | 1.0 |
| 意图正确率 | 0.9333（仅支付方式/发票 2 条落入 fallback，属知识覆盖缺口） |
| 引用覆盖率 | 0.68（FAQ 类问题被售后/订单工具路径短路，不返回来源） |
| 幻觉率（judge n=22） | 0.0 |
| 忠诚度（judge） | 0.7273 |
| 置信度分布 | 30/30 ≥ 0.8 |

坏案例回归 5/5 未复现，详见 [evals/badcase-regression-report.md](evals/badcase-regression-report.md)。

### 坏案例闭环

```
线上 trace / 评测发现 → badcases.jsonl 分类入库（hallucinated / wrong_intent / tool_fail / low_conf）
  → 每次改动后 --regress 回归 → 新版 prompt 注册到 PROMPT_VERSIONS
  → PROMPT_GRAY_PERCENT=50 灰度（crc32 稳定分流，同一会话版本不变）
  → 劣化时 PROMPT_VERSION=v1 + PROMPT_GRAY_PERCENT=0 一键回滚
```

## 业务数据（SQLite + SQL Agent）

业务数据已从 JSON mock 迁移到 **SQLite**（默认 `backend/data/app.db`），读写均通过**模板化 SQL Agent**：

- SQL 全部登记在 `app/agent/sql_agent/templates.py`，使用 `:param` 参数绑定
- **禁止** LLM 生成裸 SQL；Agent 只负责「选模板 + 填参数」
- 启动时自动建表并 Seed 演示数据

常用表：`orders` / `order_items` / `logistics_tracks` / `logistics_trace` / `promotions` / `after_sales_tickets` / `after_sales_timeline`

查看模板目录：

```http
GET /api/v1/sql-templates
```

**原 JSON 文件**仍保留在 `backend/data/*.json` 作为初始 Seed 来源参考，运行时以库为准。

| 演示单号 | 说明 |
|----------|------|
| `ORD20260301001` | 已发货 / ¥299 |
| `ORD20260310003` | 高金额 ¥2599（风控样例） |
| `YT1234567890` | 运单 |
| `TK100001` | 售后工单 |

常用单号：

- 订单：`ORD20260301001`、`ORD20260228015`、`ORD20260310003`（高金额风控样例）
- 运单：`YT1234567890`、`SF9876543210`
- 工单：`TK100001`

知识库语料：`backend/knowledge/`（商品手册 / FAQ / 活动规则）。修改后可调用：

```bash
python -m app.rag.ingest
# 或 POST /api/v1/knowledge/reindex
```

---

## 可试对话

| 用户消息 | 预期行为 |
|----------|----------|
| 你好 | 欢迎语 |
| 查询订单 ORD20260301001 | 订单状态 |
| 物流到哪了 YT1234567890 | 物流轨迹 |
| 这款手机支持快充吗 | RAG 商品问答 + 溯源 |
| 618有什么优惠 | 活动规则 |
| 我要退货 ORD20260301001 因为尺码不合适 | 进入确认态 |
| 确认 | 创建退货工单 |
| 我要退 ORD20260310003 因为不想要了 → 确认 | 高金额风控，转人工 |
| 投诉，你们太慢了 | 共情安抚 |
| 转人工 | 标记人工转接 |

---

## 架构简图

```
用户消息
   │
   ▼
脱敏 ──► 意图识别 ──► 路由
              │
    ┌─────────┼──────────┬─────────┐
    ▼         ▼          ▼         ▼
  业务工具   RAG 知识   售后状态机  兜底/转人工
    │         │          │
    └─────────┴──────────┘
              │
              ▼
      LLM 流式生成（SSE）
              │
              ▼
      风控校验 / 脱敏输出
```

---

## 与前端联调

- 开发期 CORS 已全开，前端可直接跨域调用 `http://127.0.0.1:8000`
- 非流式：`POST /api/v1/chat`
- 流式：`POST /api/v1/chat/stream`（`text/event-stream`）
- 前端目录说明见 [../frontend/README.md](../frontend/README.md)

---

## 常见问题

**1. 启动后一直 Mock，不走真实模型**  
检查 `backend/.env` 是否存在、`LLM_API_KEY` 是否非空、`MOCK_LLM` 是否为 `false` 或 `auto`。

**2. Chroma 安装失败 / 向量库报错**  
服务仍可启动，会降级为内存检索；也可删除 `backend/.chroma` 后重新 `python -m app.rag.ingest`。

**3. 知识库问答不准确**  
- 确认 `EMBEDDING_MODEL` 与提供方一致  
- 调低 `RAG_SCORE_THRESHOLD` 或增加 `RAG_TOP_K`  
- 执行 reindex 后重试  

**4. 端口占用**  
修改 `.env` 中 `APP_PORT`，或结束占用 8000 的进程。

**5. PowerShell 激活脚本被禁止**  
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

---

## 开发约定

- 业务数据为 JSON mock，替换真实中台时只改 `app/services/`，Tool 接口保持不变
- 工具编排语义对齐 LCEL（并行 / 重试 / 超时 / 降级），实现采用 asyncio
- 新增意图：改 `app/intent/labels.py` + 分类规则，并在 `orchestrator` 补路由
- 新增工具：继承 `BaseTool`，在 `app/tools/__init__.py` 注册

---

## License

仅供学习与项目演示使用。
