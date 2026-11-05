import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'

import SkyFx from './components/SkyFx'
import TopNav from './components/TopNav'
import QuickNote from './components/notes/QuickNote'
import Home from './pages/Home'
import Workspace from './pages/Workspace'
import SearchPage from './pages/SearchPage'
import ProjectPage from './pages/ProjectPage'
import NotePage from './pages/NotePage'
import NoteEditPage from './pages/NoteEditPage'
import UserSpacePage from './pages/UserSpacePage'
import ProjectSettingsPage from './pages/ProjectSettingsPage'
import UserSettingsPage from './pages/UserSettingsPage'
import RecycleBinPage from './pages/RecycleBinPage'
import AdminModeratedPage from './pages/AdminModeratedPage'
import Login from './pages/Login'
import Register from './pages/Register'
import AdminInvites from './pages/AdminInvites'
import InviteLanding from './pages/InviteLanding'
import { setUnauthorizedHandler } from './api/client'
import { useAuthStore } from './store/authStore'

/** ★★ 图谱页懒加载 —— G6 是大件，只在打开图谱时才下载 ⚠ */
const ProjectGraphPage = lazy(() => import('./pages/ProjectGraphPage'))

/**
 * ★★★ 网页版路由表（2026-11-05：把"双模式"拆干净）
 *
 * 这里**只有网页版的路由**。个人版有自己独立的前端（`desktop/ui`），
 * 两边不再共享任何文件。
 *
 * ⚠ 401 统一出口：请求拿到 `401 unauthenticated` ⇒ 清登录态并跳 `/login?next=…`
 *   （`next` 是用户可控的 ⇒ `/login` 里必须过 safeInternalPath，防开放重定向）
 */
export default function App() {
  const navigate = useNavigate()
  const clear = useAuthStore((s) => s.clear)

  useEffect(() => {
    setUnauthorizedHandler(() => {
      // ★ 只有"原本登录着"才跳（会话过期 / 被禁用）；游客安静保持未登录态
      const wasLoggedIn = !!useAuthStore.getState().user
      if (!wasLoggedIn) return

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
      <QuickNote />

      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/workspace" element={<Workspace />} />
        {/* ★ 用户空间：/u/<username> 公开看，/me 是本人视角 */}
        <Route path="/u/:username" element={<UserSpacePage />} />
        <Route path="/me" element={<UserSpacePage />} />
        <Route path="/search" element={<SearchPage />} />

        <Route path="/p/:projectRef" element={<ProjectPage />} />
        {/* ⚠ 这两条必须在 `/notes/:noteId` 之前 —— 否则 `new` 会被当成 noteId */}
        <Route path="/p/:projectRef/notes/new" element={<NoteEditPage />} />
        <Route path="/p/:projectRef/notes/:noteId/edit" element={<NoteEditPage />} />
        <Route path="/p/:projectRef/notes/:noteId" element={<NotePage />} />
        <Route path="/p/:projectRef/settings" element={<ProjectSettingsPage />} />
        <Route
          path="/p/:projectRef/graph"
          element={
            <Suspense
              fallback={
                <div className="faint" style={{ padding: 48, textAlign: 'center', fontSize: 13 }}>
                  正在加载图谱引擎…
                </div>
              }
            >
              <ProjectGraphPage />
            </Suspense>
          }
        />

        <Route path="/me/settings" element={<UserSettingsPage />} />
        <Route path="/me/deleted" element={<RecycleBinPage />} />
        <Route path="/admin/moderated" element={<AdminModeratedPage />} />

        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/admin" element={<AdminInvites />} />
        <Route path="/invite/:token" element={<InviteLanding />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      <SkyFx />
    </>
  )
}
