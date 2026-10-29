import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
// ★ 样式入口：先 token 与语义类，再挂 Tailwind（D20 · B163）
//   ⚠ 顺序不能反 —— Tailwind 只做布局工具类，外观一律由语义类决定
import './styles/index.css'

/**
 * ★★★ 个人版 = **全白**（`POSITIONING` 0.4）
 *
 * ```
 * 社区版  天青渐变 / 星点 / 网格 / 玻璃卡 —— 那是站点的"身份"
 * 个人版  白底黑字，只留结构 —— 这是"我的工具"
 * ```

 * ⚠ 只在 `VITE_PERSONAL` 构建里打这个标记；社区版不受影响。
 */
if (import.meta.env.VITE_PERSONAL === '1') {
  document.documentElement.dataset.theme = 'plain'
}

// ★ SPA 挂 /app/ 前缀（D26/D27）—— basename 必须与 vite base 一致
const basename = import.meta.env.BASE_URL.replace(/\/$/, '')

// ★★ 构建时间写进**标签页标题** ——* 一眼看出浏览器加载的是不是最新包 ⚠
//   · · ★ 标题里没有这串 ⇒* 旧包（* 缓存/没刷新）⚠
const BUILD = typeof __BUILD_TIME__ === 'string' ? __BUILD_TIME__.slice(5, 16).replace('T', ' ') : ''
if (BUILD) document.title = `Astrolabe · ${BUILD}`

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
