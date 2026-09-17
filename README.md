# 电商智能客服服务平台

面向电商业务的智能客服 Agent 全栈项目（FastAPI 后端 + React 前端）。

```
e-commerce-cs-agent/
├── backend/          # FastAPI 后端服务
├── frontend/         # React + TypeScript 前端（Orbit Desk）
├── docs/             # 设计文档
├── README.md
└── .gitignore
```

## 一键启动（前后端 · pnpm）

在仓库根目录：

```powershell
pnpm install
pnpm dev
```

同时拉起：

- 后端 http://127.0.0.1:8000（api）
- 前端 http://localhost:5173（web）

`Ctrl+C` 结束。也可单独：`pnpm run api` / `pnpm run web`，或使用 `.\run-dev.ps1`。

## 快速开始（后端）

```powershell
cd backend
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
python run.py
# API 文档: http://127.0.0.1:8000/docs
```

## 快速开始（前端 · Orbit Desk）

```powershell
cd frontend
pnpm install
pnpm dev
# http://localhost:5173
```

React + TypeScript + Vite，`/api` 已代理到后端 `8000`。设计说明见 [frontend/README.md](frontend/README.md)。

更完整说明见 [backend/README.md](backend/README.md)，架构设计见 [docs/SPEC.md](docs/SPEC.md)。

## 核心能力

- 12 类意图识别与智能路由
- 订单 / 物流 / 售后 / 促销 / 搜索工具并行编排（重试、超时、降级、单请求 ≤4 次工具护栏）
- RAG：语义分块、Embedding、ChromaDB、Top-5 重排、来源溯源
- SSE 流式输出、滑动上下文 + LLM 摘要压缩、输出长度上限、退款风控、敏感信息脱敏、LLM 故障降级
- 线上监控：全链路 Trace 落库（Trace ID / 模型与 Prompt 版本 / 工具与检索片段 / TTFT / Token 成本），`/metrics` 暴露 P50/P95、首 Token、错误率、转接率、自助解决率、坏案例率
- 离线评测与坏案例闭环：Recall@5 / 引用覆盖率 / 意图正确率 / LLM judge（准确率·幻觉率·忠诚度），坏案例分类回归 + Prompt 灰度 + 一键回滚
- 前端：对话窗口式 UI、执行过程可折叠时间线、引用溯源卡（点击展开查看知识库全文与来源文件）

后端 `app/agent/` 为扁平模块（`orchestrator` / `pipeline` / `continuity` / `after_sales_flow` 等），不再分子目录；评测与监控用法见 [backend/README.md](backend/README.md) 的「评测与监控」一节。
