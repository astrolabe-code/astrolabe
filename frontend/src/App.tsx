import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import SkyFx from './components/SkyFx'
import TopNav from './components/TopNav'
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

/** ★★ `D98`：**图谱页懒加载** —— G6 是大件，* 只在打开图谱时才下载 ⚠ */
const ProjectGraphPage = lazy(() => import('./pages/ProjectGraphPage'))

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
        {/* ★ 用户空间（参考 B 站 · 2026-10-24）：/u/<username> 公开看，/me 是本人视角 ⚠ */}
        <Route path="/u/:username" element={<UserSpacePage />} />
        <Route path="/me" element={<UserSpacePage />} />
        {/* ★★ D109：独立搜索结果页（* 路径先走 /search，* 以后换子域名只改路由）⚠ */}
        <Route path="/search" element={<SearchPage />} />
        {/* ★★ `F2`（D92）：**项目页 + 设置两页** ✅
            · `/p/:projectRef`     双栏：左节点列表 + 右笔记面板（图谱画布是 2b，未做）
            · `/p/:projectRef/settings`  项目设置（owner ∨ 协作者，后端判）
            · `/me/settings`             用户设置（登录即可）
            · ⚠★ 私有/隐藏项目**页面自己不做拦截** —— 后端 404 即「不存在或无权」，
              前端照实显示错误文案（⛔ 不泄露"项目存在但你不配"）⚠ */}
        <Route path="/p/:projectRef" element={<ProjectPage />} />
        {/* ★★ `F3`：**笔记阅读页** —— 评论 / 点赞 / 段评都挂在笔记上 ⇒* 它需要
            一个「能停下来读」的地方（* 可分享 URL + 纵向空间），* ⛔ 不是抽屉 ✅ */}
        {/* ⚠ 这两条必须在 `/notes/:noteId` 之前 —— 否则 `new` 会被当成 noteId ⚠ */}
        <Route path="/p/:projectRef/notes/new" element={<NoteEditPage />} />
        <Route path="/p/:projectRef/notes/:noteId/edit" element={<NoteEditPage />} />
        <Route path="/p/:projectRef/notes/:noteId" element={<NotePage />} />
        <Route path="/p/:projectRef/settings" element={<ProjectSettingsPage />} />
        {/* ★★ `D98`（2026-10-17）：**图谱页** —— 代码结构可视化（AntV G6）✅
            · · ⚠ 懒加载：* G6 只在打开本页时下载 ⚠ */}
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
        {/* ★★ `F4`（`D96`）：**回收站** ——* 被删的笔记（软删）+ 恢复 ✅ */}
        <Route path="/me/deleted" element={<RecycleBinPage />} />
        {/* ★★ `F5`（`D97`/`B215`）：**已处置** ——* 被隐藏的项目/笔记，* staff 从这儿恢复 ⚠ */}
        <Route path="/admin/moderated" element={<AdminModeratedPage />} />
        {/* ★★ `B170`：用户名 + 密码 —— ★ 两个页面都是【公开】的
            （★ 注册页在"入口隐藏"时也**必须能直接打开** —— ★ 那是被邀请的人唯一的入口）✅ */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        {/* ★★ `B171`：**管理页** —— ⚠★ 注意：★ 这里的"谁能进"是**页面自己判断**的，
            ★ 而**真正的拦截在后端**（`web/views/invites.py` 三个端点都带 `@staff_only`）⚠ */}
        <Route path="/admin" element={<AdminInvites />} />
        {/* ★★ `B171`：邀请链接落地 —— ★ `/invite/<token>` ⇒ 转发到注册页
            （★ 让"后端拼的链接形态"与"管理页生成的链接形态"**都能用**）✅ */}
        <Route path="/invite/:token" element={<InviteLanding />} />
        {/* ⚠ 以下页面属后续批次（需先接对应数据层）：
            /p/:key · /p/:key/graph · /search · /analysis · /node/* · /me
            ★ 暂时一律回首页 —— ❌ 不做"跳旧站"那种降级（本项目没有旧站） */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <SkyFx />
    </>
  )
}
