import { lazy, Suspense, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import QuickNote from './pages/notes/QuickNote'
import PersonalBar from './components/PersonalBar'
import CommandPalette from './components/CommandPalette'
import PersonalHome from './pages/home/PersonalHome'
import SettingsPage from './pages/settings/SettingsPage'
import Ribbon from './components/Ribbon'
import RibbonPanel from './components/RibbonPanel'
import WorkbenchShell from './components/layout/WorkbenchShell'
import type { PanelKind } from './lib/ribbonBus'
import { patchRibbon } from './lib/ribbonBus'

/** ★★ 图谱页懒加载 —— G6 是大件，只在打开图谱时才下载 ⚠ */
const ProjectGraphPage = lazy(() => import('./pages/graph/ProjectGraphPage'))

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
  const location = useLocation()
  const [panel, setPanel] = useState<PanelKind | null>(null)
  const togglePanel = (k: PanelKind) => setPanel((cur) => (cur === k ? null : k))
  useEffect(() => {
    patchRibbon({ closePanel: () => setPanel(null) })
  }, [])
  /** 图谱页懒加载 + 统一 fallback（项目内所有路由共用） */
  const graphRoute = (
    <Suspense
      fallback={
        <div className="faint" style={{ padding: 48, textAlign: 'center', fontSize: 13 }}>
          正在加载图谱引擎…
        </div>
      }
    >
      <ProjectGraphPage />
    </Suspense>
  )

  return (
    /* ★★ 根层锁死一屏：⛔ 窗口本身不再滚动（否则标题栏会被滚走、
       最右侧还会露出一条 Win11 滚动条滑块）。滚动下放到内容区 div。 */
    <div
      style={{
        height: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <PersonalBar />
      <CommandPalette />
      {/* ★ 「写一笔」只在首页出现：进项目后已经能看到节点，用标签栏的 ＋ 新建即可 */}
      {location.pathname === '/' && <QuickNote />}

        {/* ★★★ 工作台外壳：活动栏（固定 36）/ 侧边栏（可拖）/ 内容区。
            · 语义集中在 WorkbenchShell，页面只负责路由
            · 活动栏不可拖 ⇒ 普通 div；只有侧栏那条线用 SplitPane */}
        <WorkbenchShell
          activityBar={<Ribbon active={panel} onToggle={togglePanel} />}
          sideBar={panel ? <RibbonPanel kind={panel} onClose={() => setPanel(null)} /> : null}
        >
      <Routes>
        <Route path="/" element={<PersonalHome />} />

        {/* ★★★ 项目内的所有页面都走图谱页（原「节点列表页」已删除）：
            · 节点列表 → 侧栏「节点」分组
            · 笔记 / 白板 → 右栏正文区
            ⛔ 不再有第二个页面骨架 */}
        <Route path="/p/:projectRef" element={graphRoute} />
        <Route path="/p/:projectRef/graph" element={graphRoute} />
        <Route path="/p/:projectRef/settings" element={<SettingsPage />} />
        <Route path="/p/:projectRef/board/:boardId" element={graphRoute} />
        <Route path="/p/:projectRef/notes/new" element={graphRoute} />
        <Route path="/p/:projectRef/notes/:noteId/edit" element={graphRoute} />
        <Route path="/p/:projectRef/notes/:noteId" element={graphRoute} />

        <Route path="/me/settings" element={<SettingsPage />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
        </WorkbenchShell>
    </div>
  )
}
