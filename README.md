# 电商智能客服服务平台

面向电商业务的智能客服 Agent 全栈项目（后端已实现，前端预留）。

```
e-commerce-cs-agent/
├── backend/          # FastAPI 后端服务
├── frontend/         # 前端页面（规划中）
├── docs/             # 设计文档
├── README.md
└── .gitignore
```

## 快速开始（后端）

```powershell
cd backend

# 使用 uv 创建虚拟环境（推荐在仓库根目录创建，或 backend 下创建均可）
# 方式 A：在 backend 内
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt

python run.py
# API 文档: http://127.0.0.1:8000/docs
```

更完整说明见 [backend/README.md](backend/README.md)，架构设计见 [docs/SPEC.md](docs/SPEC.md)。

## 前端

见 [frontend/README.md](frontend/README.md)。后端已开启 CORS，可直接对接。

## 核心能力

- 12 类意图识别与智能路由
- 订单 / 物流 / 售后 / 促销 / 搜索工具并行编排（重试、超时、降级）
- RAG：语义分块、Embedding、ChromaDB、Top-5 重排、来源溯源
- SSE 流式输出、滑动上下文、退款风控、敏感信息脱敏、LLM 故障降级

后端 `app/agent/` 为扁平模块（`orchestrator` / `pipeline` / `continuity` / `after_sales_flow` 等），不再分子目录，详见 [backend/README.md](backend/README.md)。
