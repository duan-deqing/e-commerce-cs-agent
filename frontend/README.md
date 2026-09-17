# Frontend — 电商智能客服（规划中）

后端 API 已就绪，本目录用于前端页面。建议技术栈（可按喜好调整）：

- **方案 A（推荐）**：Vite + React + TypeScript + Tailwind
- **方案 B**：Vite + Vue 3 + TypeScript

## 建议页面

| 页面 | 功能 |
|------|------|
| 会话主界面 | 聊天流、SSE 流式渲染、来源卡片 |
| 侧边栏 | 历史会话、意图/状态展示 |
| 工具面板（可选） | 展示 tool 调用与耗时（调试用） |

## 对接约定

- Base URL：`http://127.0.0.1:8000`
- 非流式：`POST /api/v1/chat`
- 流式：`POST /api/v1/chat/stream`（SSE）
- 健康检查：`GET /api/v1/health`

启动后端：

```powershell
cd ..\backend
.\.venv\Scripts\Activate.ps1
python run.py
```

## 初始化示例（Vite + React）

```powershell
cd frontend
# npm create vite@latest . -- --template react-ts
# npm i
# npm run dev
```

将代理或请求地址指到 `http://127.0.0.1:8000` 即可。
