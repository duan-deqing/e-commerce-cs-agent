import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 前后端联调：/api 代理到 FastAPI :8000
// SSE 使用 POST + text/event-stream，Vite 默认可透传
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: false,
      },
    },
  },
})
