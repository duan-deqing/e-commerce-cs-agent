# Frontend — Orbit Desk

React + TypeScript + Vite + pnpm 的电商智能客服用户端前端（**浅色主题**）。

## 设计

- 首页即对话窗口：居中悬浮圆角卡片（暖白底 + 燃橙强调），移动端自动全屏
- 对话流单列布局：用户右侧深色气泡，Agent 左侧白卡片
- **执行过程**折叠时间线位于回答上方：生成中自动展开（意图 → 工具 → RAG → 完成），结束自动收起，可手动展开
- **引用溯源**卡可点击展开：懒加载知识库文档全文（`GET /api/v1/kb/doc`）并显示来源文件与章节
- Design tokens 见 `src/styles.css`；动效尊重 `prefers-reduced-motion`

## 联调

- Vite 将 `/api` 代理到 `http://127.0.0.1:8000`
- 顶栏状态 pill 显示「在线 / 连接失败 / 演示模式」
- 后端配置 `API_KEY` 时，在 `frontend/.env.local` 设置 `VITE_API_KEY`

## 启动

```powershell
# 推荐：仓库根目录一键
cd ..
pnpm install
pnpm dev

# 或仅前端（需后端已在 8000）
cd frontend
pnpm install
pnpm dev
```

打开 http://localhost:5173

## 演示话术

- 我的订单到哪了
- 怎么申请退换货 → 确认
- 有什么优惠活动
- 保温杯的保温效果怎么样（触发 RAG，可展开来源溯源）
- 转人工客服
