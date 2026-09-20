import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
// ★ 样式入口：先 token 与语义类，再挂 Tailwind（D20 · B163）
//   ⚠ 顺序不能反 —— Tailwind 只做布局工具类，外观一律由语义类决定
import './styles/index.css'

// ★ SPA 挂 /app/ 前缀（D26/D27）—— basename 必须与 vite base 一致
const basename = import.meta.env.BASE_URL.replace(/\/$/, '')

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
