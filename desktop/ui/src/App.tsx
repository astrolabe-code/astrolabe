import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import QuickNote from './components/notes/QuickNote'
import PersonalBar from './components/PersonalBar'
import CommandPalette from './components/CommandPalette'
import PersonalHome from './pages/PersonalHome'
import ProjectPage from './pages/ProjectPage'
import NotePage from './pages/NotePage'
import NoteEditPage from './pages/NoteEditPage'
import ProjectSettingsPage from './pages/ProjectSettingsPage'
import UserSettingsPage from './pages/UserSettingsPage'
import RecycleBinPage from './pages/RecycleBinPage'

/** ★★ 图谱页懒加载 —— G6 是大件，只在打开图谱时才下载 ⚠ */
const ProjectGraphPage = lazy(() => import('./pages/ProjectGraphPage'))

/**
 * ★★★ 个人版路由表（2026-11-05 从"双模式"里拆出来）
 *
 * 这里**只有个人版的路由**：项目 → 图谱 → 笔记；设置；回收站。
 * ⛔ 没有首页营销页、登录/注册、搜索页、用户空间、管理、邀请
 *   —— 个人版只有你一个人用，那些东西没有对象。
 *
 * ⚠ 与网页版的关系：**没有关系**。网页版的路由在 `frontend/src/App.tsx`，
 *    改那边不会影响这里（反之亦然）。
 */
export default function App() {
  return (
    <>
      <PersonalBar />
      <CommandPalette />
      <QuickNote />

      <Routes>
        <Route path="/" element={<PersonalHome />} />

        <Route path="/p/:projectRef" element={<ProjectPage />} />
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
        {/* ⚠ 这两条必须在 `/notes/:noteId` 之前 —— 否则 `new` 会被当成 noteId */}
        <Route path="/p/:projectRef/notes/new" element={<NoteEditPage />} />
        <Route path="/p/:projectRef/notes/:noteId/edit" element={<NoteEditPage />} />
        <Route path="/p/:projectRef/notes/:noteId" element={<NotePage />} />

        <Route path="/me/settings" element={<UserSettingsPage />} />
        <Route path="/me/deleted" element={<RecycleBinPage />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
