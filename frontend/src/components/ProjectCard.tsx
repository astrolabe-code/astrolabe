import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CloudDownload, FolderGit2, Globe, Lock, Pencil, Trash2, User } from 'lucide-react'
import type { ProjectSummary } from '../api/types'
import { errorMessage } from '../api/errors'
import { useDeleteProject, useStartFetch, useUpdateProject } from '../query/projects'
import ParseStatus from './ParseStatus'
import ProjectEditModal from './ProjectEditModal'
import ConfirmDialog from './ui/ConfirmDialog'
import ProgressBar from './ui/ProgressBar'

interface ProjectCardProps {
  project: ProjectSummary
  /** ★ 已登录（★ 写操作可用；★ 游客只看得到公开项目与只读入口） */
  canManage?: boolean
}

type DialogKey = 'public' | 'fetch' | 'delete'

/**
 * ★ 项目卡片（`B164` 改写）
 *
 * ## ⚠★ 与旧项目（`/home/webapp/demo/.../ProjectCard.tsx`）的差别
 *
 * | 去掉 | 为什么 |
 * |---|---|
 * | ★ **「上传源码」按钮** | ⚠★ 新设计**源码只能服务端拉取**（`B109`）—— ❌ 没有 zip 上传这条路 |
 * | ★★ **「复制到我的工作区」按钮** | ❌ 新后端没有 `copy/` 端点 |
 * | ★ **分类（`category`）显示** | ❌ 新后端不做分类 |
 *
 * | 改动 | 说明 |
 * |---|---|
 * | ★★ `project.key` ⇒ **`project.project_ref`** | ⚠ 主键字段名不同（★ 照搬会「页面空白」） |
 * | ★★ 图标由 `projectIcon(project.icon_lucide)` ⇒ **固定图标** | ❌ 新后端没有图标字段 |
 * | ★★★ `useReparse` ⇒ **`useStartFetch`**（`B169`） | ⚠★ 原写法叫「**补投**」—— ★★ **那是 AI 自己发明的语义，所有者从没要过**；★ 现在是「**发起拉取授权**」（★ 真正的动作在 OAuth 回调里） |
 * | ★★★ 「补投解析」按钮 ⇒ **「拉取代码」按钮** | ★ 所有者原话：「**只有一个拉取 github 或 gitee 代码的按钮，拉了就解析，不给用户一点搞破坏的机会**」 |
 * | ★★ 按钮显隐：`!hasData` ⇒ **`!graph_built`** | ⚠★ 见下方 `canFetch` 的说明 —— ★ 两者在"失败"这个情形上**恰好相反** |
 * | ★ `status !== 'idle'` ⇒ `status !== 'none'` | ★ 新后端用 `none` 表示"还没解析" |
 */
export default function ProjectCard({ project, canManage = false }: ProjectCardProps) {
  // ★ 对齐旧站：owner 项须「本人 + 已登录」
  const mine = !!project.mine && canManage
  const hasData = project.status !== 'none'
  /**
   * ★★★ 「拉取代码」按钮的显示条件（`B169`）—— ⚠★ **不能用 `hasData`**：
   * ★ `hasData` 说的是"**作业跑过**"，★ 而闸门看的是"**是否定版**"（`graph_built`）。
   * ★★ 两者在「**拉取失败 / 解析失败**」这个最常见的情形上**恰好相反**：
   *   ⚠ 那时 `hasData = true`、`graph_built = false` —— ★ 若用 `hasData` 就**不给按钮**，
   *   ★★ 而那恰恰是所有者明确要求「**还允许再发起**」的情形 ⚠
   */
  const canFetch = !project.graph_built
  const ref = project.project_ref

  const [dialog, setDialog] = useState<DialogKey | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [error, setError] = useState('')

  const update = useUpdateProject(ref)
  const fetchStart = useStartFetch(ref, '/workspace')
  const del = useDeleteProject(ref)

  const close = () => {
    setDialog(null)
    setError('')
  }

  const runAction = async <T,>(
    mutate: () => Promise<T>,
    errObj: unknown,
    onDone?: (r: T) => void,
  ) => {
    setError('')
    const r = await mutate().catch((e: unknown) => {
      console.error('project action failed', e)
      return undefined
    })
    if (r === undefined) {
      setError(errorMessage(errObj, '操作失败，请重试'))
      return
    }
    onDone?.(r as T)
  }

  const confirmPublic = () =>
    runAction(() => update.mutateAsync({ is_public: !project.is_public }), update.error, close)

  /**
   * ★★★ 「拉取代码」—— ⚠★ **它不投递作业，而是把用户【送去授权】**（`B169`）。
   *
   * ★ 为什么不能在这里直接投递：⚠ 本平台**不保存 `access_token`**（`B148`）
   * ⇒ ★ 不拿到 token 就**无法验证"这个库是不是他的"** ⚠
   * ⇒ ★★ 所以这里只跳转；★ **归属校验 + 投递（拉取 + 解析）都在 OAuth 回调里完成** ✅
   */
  const confirmFetch = () =>
    runAction(
      () => fetchStart.mutateAsync(),
      fetchStart.error,
      (r) => {
        // ★ 授权页在**第三方域名**上 ⇒ ★ 只能整页跳转（❌ 不是路由跳转）
        window.location.href = r.authorize_url
      },
    )

  const confirmDelete = () => runAction(() => del.mutateAsync(), del.error, close)

  const dialogs: Record<DialogKey, {
    title: string
    message: string
    confirmText: string
    danger?: boolean
    onConfirm: () => void
  }> = {
    public: {
      title: project.is_public ? '取消公开' : '设为公开',
      message: project.is_public
        ? '取消公开后，项目仅你可见（游客将无法再访问）。\n\n确定取消公开？'
        : '设为公开后，任何人（含游客）都能看到并阅读该项目的图谱与解释。\n\n确定公开？',
      confirmText: project.is_public ? '取消公开' : '设为公开',
      danger: project.is_public,
      onConfirm: confirmPublic,
    },
    fetch: {
      title: '拉取代码',
      // ★★★ `B169`：★ 文案要说清三件事 —— **去哪儿 · 为什么 · 我们不留你的 token**
      message:
        `将从「${project.repo_url || '项目仓库'}」拉取源码并解析。\n\n` +
        '接下来会跳转到 GitHub / Gitee 授权：\n' +
        '★ 这一步是为了确认【这个仓库确实属于你】——\n' +
        '   ★ 只允许拉取你有控制权的代码，避免侵权。\n' +
        '★ 本站【不会保存】你的授权 token，用完即丢。\n' +
        '★ 拉取与解析一次完成，之后【不允许重新拉取】；\n' +
        '   需要另一个版本请新建项目，想重来请删了重建。\n\n' +
        '确定继续？',
      confirmText: '去授权并拉取',
      onConfirm: confirmFetch,
    },
    delete: {
      title: '删除项目',
      message:
        `确定要删除项目「${project.name}」吗？\n\n` +
        '将删除以下内容：\n' +
        `· 项目本身（${project.name}）\n` +
        '· 源码分析数据（文件 / 函数 / 调用关系）\n' +
        '· 磁盘上的源码副本（★ 同时释放你的存储空间）\n\n' +
        '此操作不可恢复！',
      confirmText: '删除',
      danger: true,
      onConfirm: confirmDelete,
    },
  }

  const active = dialog ? dialogs[dialog] : null
  const pending = update.isPending || fetchStart.isPending || del.isPending

  return (
    <div className="card hoverable flex flex-col p-5">
      <div className="flex items-start gap-3">
        <div
          className="flex items-center justify-center rounded-xl shrink-0"
          style={{ width: 38, height: 38, background: 'var(--accent-dim)', color: 'var(--accent)' }}
        >
          {/* ★ 固定图标 —— 新后端没有 icon 字段 */}
          <FolderGit2 size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <Link
            to={`/p/${encodeURIComponent(ref)}`}
            className="font-semibold no-underline text-text-main hover:text-accent"
            style={{ fontSize: 15 }}
          >
            {project.name}
          </Link>
          <div className="flex items-center gap-1.5 mt-1 text-text-faint" style={{ fontSize: 11 }}>
            {project.is_public ? <Globe size={11} /> : <Lock size={11} />}
            <span>{project.is_public ? '公开' : '私有'}</span>
            {project.provider && <span>· {project.provider}</span>}
          </div>
        </div>
      </div>

      <p className="text-text-sub mt-3 mb-0 flex-1" style={{ fontSize: 12.5, lineHeight: 1.7 }}>
        {project.desc || '还没有简介。进入项目主页可以补充说明。'}
      </p>

      <div className="flex items-center justify-between gap-2 mt-4">
        <ParseStatus status={project.status} size="sm" />
        <span className="inline-flex items-center gap-1 text-text-faint" style={{ fontSize: 11 }}>
          <User size={11} />
          {project.mine ? '我的项目' : project.owner || '内置'}
        </span>
      </div>

      {(project.status === 'queued' ||
        project.status === 'running' ||
        (project.progress || 0) > 0) && (
        <ProgressBar
          className="mt-3"
          value={project.progress || 0}
          status={project.status}
          showValue
        />
      )}

      <div
        className="flex items-center gap-2 flex-wrap mt-4 pt-3"
        style={{ borderTop: '1px solid var(--card-border)' }}
      >
        <Link className="btn ghost flex-1 justify-center" to={`/p/${encodeURIComponent(ref)}`}>
          进入项目
        </Link>

        <div className="flex items-center gap-1.5 ml-auto">
          {mine && (
            <button type="button" className="icon-btn" title="编辑项目资料" aria-label="编辑项目资料"
                    onClick={() => setEditOpen(true)}>
              <Pencil size={14} />
            </button>
          )}
          {mine && hasData && (
            <button
              type="button"
              className="icon-btn"
              title={project.is_public ? '取消公开' : '设为公开'}
              aria-label={project.is_public ? '取消公开' : '设为公开'}
              onClick={() => setDialog('public')}
            >
              {project.is_public ? <Lock size={14} /> : <Globe size={14} />}
            </button>
          )}
          {/* ★★★ `B169`：**只有一个「拉取代码」按钮**（★ 所有者原话："拉了就解析"）
              ⚠★ 已定版才不给 —— ★ **未定版（含拉取/解析失败）都要给**（★ 失败还允许再发起） */}
          {mine && canFetch && (
            <button type="button" className="icon-btn" title="拉取代码" aria-label="拉取代码"
                    onClick={() => setDialog('fetch')}>
              <CloudDownload size={14} />
            </button>
          )}
          {mine && (
            <button type="button" className="icon-btn danger" title="删除项目" aria-label="删除项目"
                    onClick={() => setDialog('delete')}>
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>

      <ProjectEditModal open={editOpen} project={project} onClose={() => setEditOpen(false)} />

      <ConfirmDialog
        open={!!active}
        title={active?.title || ''}
        message={active?.message || ''}
        confirmText={active?.confirmText}
        danger={active?.danger}
        loading={pending}
        error={error}
        onCancel={close}
        onConfirm={() => active?.onConfirm()}
      />
    </div>
  )
}
