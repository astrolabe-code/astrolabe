import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import SkyFx from './components/SkyFx'
import TopNav from './components/TopNav'
import Home from './pages/Home'
import Workspace from './pages/Workspace'
import Login from './pages/Login'
import Register from './pages/Register'
import { setUnauthorizedHandler } from './api/client'
import { useAuthStore } from './store/authStore'

/**
 * ★ 路由骨架（`B163` 建立 · `B164` 挂上工作区 · `B170` 挂上登录 / 注册）
 *
 * ## ⚠★ 与原版的差别
 *
 * | 原版 | 现在 | 为什么 |
 * |---|---|---|
 * | ★ `LegacyRedirect`：未匹配路由**跳回旧站** | ★ 未匹配 ⇒ **回首页** | ★★ 本项目**没有旧站**，无处可跳 ⚠ |
 * | ★ 8 个页面 | ★ **Home + Workspace + Login + Register**，其余按阶段补 | ★ 它们依赖尚未接入的数据层 |
 *
 * ## ★★ 401 的统一出口（★ 本组件负责）
 *
 * ★ 任何请求拿到 `401 unauthenticated` ⇒ `api/client.ts` 会调这里注册的 handler：
 * ★ **清本地登录态 + 跳 `/login?next=<当前路径>`** ⇒ ★ 登录后**回到原处** ✅
 * ⚠★ `next` 是**用户可控**的 ⇒ ★ `/login` 里**必须**过 `safeInternalPath`（★ 防开放重定向）⚠
 *
 * ## ★ 进度
 *
 * - ✅ **第一阶段**（`B163`）：脚手架 + 视觉资产 + Home
 * - ✅ **第二阶段 2a**（`B164`）：`projects` 数据层 + **Workspace**
 * - ✅ **`B170`**：`auth` 数据层 + **Login · Register**（★ **用户名 + 密码**，
 *   ⚠★ 不是 OAuth —— ★ 见 `B167`：★ OAuth 的用途是"**拉代码时验证归属**"）
 * - ⏭ **2b**：`graph/*` ⇒ GraphPage · NodeDetail
 * - ⏭ **2c**：`jobs` + `progress` ⇒ ProjectHome
 * - ⏭ **2e**：`publish/*` + `admin/reviews/*` + `graph/edit` ⇒ 发布 · 管理 · 图修补
 *   ★ 另：`me/*`（`overview` / `storage` / `submissions`）⇒ **「我的」页面**
 *
 * ★★ **保留**：★ `SkyFx`（背景特效）· `TopNav` · **401 统一处理** ✅
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
        {/* ★★ `B170`：用户名 + 密码 —— ★ 两个页面都是【公开】的
            （★ 注册页在"入口隐藏"时也**必须能直接打开** —— ★ 那是被邀请的人唯一的入口）✅ */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        {/* ⚠ 以下页面属后续批次（需先接对应数据层）：
            /p/:key · /p/:key/graph · /search · /analysis · /node/* · /me
            ★ 暂时一律回首页 —— ❌ 不做"跳旧站"那种降级（本项目没有旧站） */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <SkyFx />
    </>
  )
}
