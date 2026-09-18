# Orbit Desk — 电商智能客服 Agent

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

面向电商业务的智能客服 Agent 全栈项目：**意图路由 → 工具编排 → RAG 知识问答 → SSE 流式生成**，配套全链路监控、离线评测与坏案例闭环，开箱即可本地演示与二次开发。

## 功能特性

**Agent 核心**
- 12 类意图识别与智能路由，规则快通道优先，LLM 兜底
- 订单 / 物流 / 售后 / 促销 / 搜索工具并行编排：指数退避重试、超时熔断、失败降级，单请求 ≤4 次工具护栏
- 售后状态机（退换货进度追问）与高金额退款风控（默认 ≥ ¥2000 转人工）

**RAG 知识问答**
- Markdown 语义分块（标题优先 + 句边界）入 ChromaDB
- 两级重排：本地 cross-encoder（Ollama `bge-reranker-v2-m3`）优先，不可用自动降级向量 + 关键词融合打分
- 支持独立向量端点（本地 Ollama `bge-large` / DashScope / OpenAI）
- 来源溯源（doc_id / 标题 / 片段 / 来源文件全文）+ 低置信拒答防幻觉

**工程化**
- SSE 流式输出（含思考型模型 `reasoning` 增量透出，执行面板实时「深度思考」）
- 滑动上下文窗口 + LLM 摘要压缩（14 轮触发）、输出长度上限、cache-friendly 稳定前缀
- 全链路 Trace 落库：Trace ID / 模型与 Prompt 版本 / 工具与检索片段 / TTFT / Token 成本
- `/metrics`：P50/P95、首 Token 延迟、错误率、转接率、自助解决率、坏案例率
- 离线评测：Recall@5 / 引用覆盖率 / 意图正确率 / LLM judge（准确率·幻觉率·忠诚度）
- 坏案例闭环：分类回归 + Prompt 灰度（crc32 稳定分流）+ 一键回滚

**前端（Orbit Desk）**
- 对话窗口式 UI，执行过程可折叠时间线，深度思考流式滚动
- 引用溯源卡点击展开知识库全文，移动端自适应全屏

## 快速开始

### 前置要求

- Python 3.11+（推荐 3.13）、[uv](https://docs.astral.sh/uv/) 或 pip
- Node.js 18+、pnpm 9+
- （可选）[Ollama](https://ollama.com/) — 本地向量与重排模型

### 一键启动（前后端）

```bash
pnpm install
pnpm dev
```

- 后端 http://127.0.0.1:8000 （API 文档 `/docs`）
- 前端 http://localhost:5173

也可单独运行：`pnpm run api` / `pnpm run web`，或 `.\scripts\run-dev.ps1`。

### 手动启动

```bash
# 后端
cd backend
uv venv && .\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
python run.py

# 前端（另开终端）
cd frontend
pnpm install && pnpm dev
```

首次启动自动入库 `knowledge/` 语料；未配置 `LLM_API_KEY` 时自动使用 Mock LLM，全链路可离线演示。

### 本地模型（可选）

```bash
ollama pull bge-large                # 向量（1024 维）
ollama pull qllama/bge-reranker-v2-m3  # 重排 cross-encoder
```

配置见 `backend/.env.example` 的 `EMBEDDING_BASE_URL` / `RERANK_*` 项；切换向量模型后需重建向量库（`python -m app.rag.ingest`）。

## 评测基线

30 条基线测试集（`backend/evals/`）：

| 指标 | 数值 |
|------|------|
| Recall@5 | 1.00 |
| 引用覆盖率 | 0.68 |
| 意图正确率 | 0.93 |
| 幻觉率 | 0 |
| LLM judge 忠诚度 | 0.73 |

复现：

```bash
cd backend
python scripts/run_eval.py              # 全量评测 → report.json
python scripts/run_eval.py --regress    # 坏案例回归 → report-regress.json
python scripts/smoke_test.py            # 端到端冒烟（Mock LLM）
```

监控与坏案例闭环用法详见 [backend/README.md](backend/README.md)「评测与监控」。

## 项目结构

```
e-commerce-cs-agent/
├── backend/           # FastAPI 后端（意图路由 / 工具编排 / RAG / 监控 / 评测）
│   ├── app/           # agent · api · core · rag · tools · db · risk ...
│   ├── evals/         # 评测集 · 坏案例 · 评测报告
│   ├── knowledge/     # RAG 语料（商品 / FAQ / 活动）
│   └── scripts/       # run_eval · smoke_test · ttft_probe · verify_p2
├── frontend/          # React + TypeScript + Vite（Orbit Desk）
├── docs/              # 设计文档（SPEC.md）
└── scripts/           # 开发启动脚本
```

## 文档

- [后端说明](backend/README.md) — 架构、配置、API、评测与监控
- [前端说明](frontend/README.md) — 设计规范与组件
- [设计 SPEC](docs/SPEC.md) — 完整架构设计

## Roadmap

- [ ] CI（lint + 冒烟）
- [ ] 多轮槽位填充与工单进度主动推送
- [ ] RAG 重排模型 A/B 灰度接入监控

## License

[MIT](LICENSE) © 2026 duan-deqing
