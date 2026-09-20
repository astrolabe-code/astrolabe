import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import SkyFx from './components/SkyFx'
import TopNav from './components/TopNav'
import Home from './pages/Home'
import { setUnauthorizedHandler } from './api/client'
import { useAuthStore } from './store/authStore'

/**
 * ★ 路由骨架（B163 · 第一阶段）
 *
 * ## ⚠★ 与原版的差别
 *
 * | 原版 | 现在 | 为什么 |
 * |---|---|---|
 * | ★ `LegacyRedirect`：未匹配路由**跳回旧站** | ★ 未匹配 ⇒ **回首页** | ★★ 本项目**没有旧站**，无处可跳 ⚠ |
 * | ★ 8 个页面（含 Graph / NodeDetail / Search / Analysis）| ★ **先挂 Home**，其余按阶段补 | ★ 它们依赖 `query/*` 数据层，★ 属第二阶段 |
 *
 * ★★★ **保留**：★ `SkyFx`（背景特效）· `TopNav` · 401 统一处理 · 路由级懒加载的做法 ✅
 *
 * ## ★ 一个刻意保留的设计（来自原版）
 *
 * ★★ **401 统一处理**：★ 任何请求返回 `unauthenticated` ⇒
 *   ★ 清 token + 跳登录页（★ 带 `next`）—— ⚠ 且**由 `client.ts` 保证只触发一次**
 *   （★ 否则并发的多个请求会把人踢来踢去）✅
 */
export default function App() {
  const navigate = useNavigate()
  const clear = useAuthStore((s) => s.clear)

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clear()
      // ⚠ 去掉 /app 前缀（那是 SPA 的 basename，不是路由的一部分）
      const next = `${window.location.pathname.replace('/app', '')}${window.location.search}`
      navigate(`/login?next=${encodeURIComponent(next || '/')}`, { replace: true })
    })
    return () => setUnauthorizedHandler(null)
  }, [clear, navigate])

  return (
    <>
      <TopNav />
      <Routes>
        <Route path="/" element={<Home />} />
        {/* ⚠ 以下页面属第二阶段（需先接 query 数据层）：
            /login · /workspace · /p/:key · /p/:key/graph · /search · /analysis · /node/*
            ★ 暂时一律回首页，❌ 不做"跳旧站"那种降级 —— 本项目没有旧站 */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <SkyFx />
    </>
  )
}
