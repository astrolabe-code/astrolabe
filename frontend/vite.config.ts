import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// ============================================================================
// ★★★ 同源策略（B163）：dev 走 proxy ⇒ 浏览器视角【同源】⇒ ❌ 不需要 CORS
// ============================================================================
// ★ 这是用户裁定的「同源防护，用最方便的就行」的落地方式：
//   · 开发：Vite dev server 把 /api · /media · /static 转发给后端
//   · 生产：由 nginx 同源服务（前端产物 + 后端），同样不需要 CORS
//
// ⚠★ 后端地址的取值依据（★ 别照抄旧项目）：
//   旧项目写的是 http://127.0.0.1:8000 —— ⚠ 但本项目后端跑在 Docker 里，
//   `web` 服务的 8000 **没有映射到宿主机**（`docker compose ps` 只见 `8000/tcp`）；
//   ★★ 对外的是 **nginx：0.0.0.0:8090 -> 80**
//   ⇒ ★ 所以 dev proxy 必须指向 **8090**，否则一律 502。
const DJANGO_ORIGIN = process.env.VITE_DJANGO_ORIGIN || 'http://127.0.0.1:8090'

export default defineConfig({
  // ★ 迁移期 SPA 一律挂 /app/ 前缀（D26/D27），不占用 /
  //   ⚠ 必须与 BrowserRouter 的 basename 一致（见 src/main.tsx）
  base: '/app/',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
    port: 5173,
    proxy: {
      '/api': { target: DJANGO_ORIGIN, changeOrigin: true },
      '/media': { target: DJANGO_ORIGIN, changeOrigin: true },
      '/static': { target: DJANGO_ORIGIN, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    // ★ 性能预算（B163）：vis-network 单独分包（由 MiniGraph 的动态 import 自动完成）
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
        },
      },
    },
    chunkSizeWarningLimit: 700,
  },
})
