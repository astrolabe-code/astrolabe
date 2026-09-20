import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import SkyFx from './components/SkyFx'
import TopNav from './components/TopNav'
import Home from './pages/Home'
import Workspace from './pages/Workspace'
import { setUnauthorizedHandler } from './api/client'
import { useAuthStore } from './store/authStore'

/**
 * ★ 路由骨架（`B163` 建立 · `B164` 挂上工作区）
 *
 * ## ⚠★ 与原版的差别
 *
 * | 原版 | 现在 | 为什么 |
 * |---|---|---|
 * | ★ `LegacyRedirect`：未匹配路由**跳回旧站** | ★ 未匹配 ⇒ **回首页** | ★★ 本项目**没有旧站**，无处可跳 ⚠ |
 * | ★ 8 个页面 | ★ **Home + Workspace**，其余按阶段补 | ★ 它们依赖尚未接入的数据层 |
 *
 * ## ★ 进度
 *
 * - ✅ **第一阶段**（`B163`）：脚手架 + 视觉资产 + Home
 * - ✅ **第二阶段 2a**（`B164`）：`projects` 数据层 + **Workspace**
 * - ⏭ **2b**：`graph/*` ⇒ GraphPage · NodeDetail
 * - ⏭ **2c**：`jobs` + `parse` + `progress` ⇒ ProjectHome
 * - ⏭ **2d**：`auth/*`（OAuth）+ `me/*` + `invites/*` ⇒ Login · 我的
 * - ⏭ **2e**：`publish/*` + `admin/reviews/*` + `graph/edit` ⇒ 发布 · 管理 · 图修补
 *
 * ★★ **保留**：★ `SkyFx`（背景特效）· `TopNav` · **401 统一处理** · 路由级懒加载 ✅
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
        <Route path="/workspace" element={<Workspace />} />
        {/* ⚠ 以下页面属后续批次（需先接对应数据层）：
            /login · /p/:key · /p/:key/graph · /search · /analysis · /node/*
            ★ 暂时一律回首页 —— ❌ 不做"跳旧站"那种降级（本项目没有旧站） */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <SkyFx />
    </>
  )
}
