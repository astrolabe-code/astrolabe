import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { PackagePlus, Search, ServerCrash } from 'lucide-react'
import type { ProjectSummary } from '../api/types'
import { errorMessage } from '../api/errors'
import AppLayout from '../components/AppLayout'
import ProjectCard from '../components/ProjectCard'
import ProjectCreateModal from '../components/ProjectCreateModal'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import { useProjects } from '../query/projects'
import { useMe } from '../hooks/useMe'

/**
 * ★ 项目工作区（`B164` 改写）
 *
 * ⚠★ 与旧项目的差别：
 * - ❌ **删掉 `UploadPanel` 与"上传源码"整个流程** —— ★ 新设计源码由服务端从仓库拉取（`B109`）
 * - ★★ `p.key` ⇒ **`p.project_ref`**（★ 含 React 的 `key=` 与跳转路径）
 * - ★ 过滤字段里去掉 `category`（★ 新后端没有）
 *
 * ★ 工作区对游客开放（★ 只见公开项目）；★ 新建需登录 ✅
 */
export default function Workspace() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const q = params.get('q') || ''
  const [createOpen, setCreateOpen] = useState(false)

  const projects = useProjects()
  const me = useMe()
  const authed = !!me.data?.authenticated

  const list = useMemo<ProjectSummary[]>(() => {
    const all = projects.data || []
    const kw = q.trim().toLowerCase()
    if (!kw) return all
    return all.filter((p) =>
      [p.name, p.desc, p.owner, p.provider]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(kw)),
    )
  }, [projects.data, q])

  const setQuery = (v: string) => {
    const next = new URLSearchParams(params)
    if (v) next.set('q', v)
    else next.delete('q')
    setParams(next, { replace: true })
  }

  const goProject = (projectRef: string) => {
    setCreateOpen(false)
    navigate(`/p/${encodeURIComponent(projectRef)}`)
  }

  return (
    <>
      <AppLayout
        title="项目工作区"
        actions={
          <>
            <div className="relative">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-text-faint pointer-events-none"
              />
              <input
                className="input"
                style={{ paddingLeft: 32, width: 260 }}
                value={q}
                placeholder="按名称 / 简介 / 归属过滤"
                onChange={(e) => setQuery(e.target.value)}
                aria-label="过滤项目"
              />
            </div>
            {authed ? (
              <Button variant="primary" icon={<PackagePlus size={15} />} onClick={() => setCreateOpen(true)}>
                新建项目
              </Button>
            ) : (
              <Link className="btn primary" to="/login?next=%2Fworkspace">
                登录后新建
              </Link>
            )}
          </>
        }
      >
        {projects.isLoading && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="card p-5 animate-pulse" style={{ height: 186 }}>
                <div className="rounded-xl mb-4" style={{ width: 38, height: 38, background: 'var(--accent-dim)' }} />
                <div className="rounded mb-2" style={{ height: 10, width: '60%', background: 'var(--accent-dim)' }} />
                <div className="rounded" style={{ height: 8, width: '85%', background: 'var(--accent-dim)' }} />
              </div>
            ))}
          </div>
        )}

        {projects.isError && (
          <div className="card">
            <EmptyState
              tone="error"
              icon={<ServerCrash size={20} />}
              title="项目列表加载失败"
              hint={errorMessage(projects.error)}
              action={<Button onClick={() => projects.refetch()}>重新加载</Button>}
            />
          </div>
        )}

        {projects.isSuccess && list.length === 0 && (
          <div className="card">
            <EmptyState
              title={q ? '没有匹配的项目' : '还没有项目'}
              hint={
                q
                  ? `没有名称、简介或归属包含「${q}」的项目，试试换个关键词。`
                  : '新建一个项目并填写仓库地址，服务端会从仓库拉取源码、解析并生成代码图谱。'
              }
              action={
                q ? (
                  <Button onClick={() => setQuery('')}>清除过滤</Button>
                ) : authed ? (
                  <Button variant="primary" icon={<PackagePlus size={15} />} onClick={() => setCreateOpen(true)}>
                    新建第一个项目
                  </Button>
                ) : (
                  <Link className="btn primary" to="/login?next=%2Fworkspace">登录后新建项目</Link>
                )
              }
            />
          </div>
        )}

        {projects.isSuccess && list.length > 0 && (
          <>
            <div className="faint mb-3">
              共 {list.length} 个项目{q ? `（已按「${q}」过滤）` : ''}
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {list.map((p) => (
                <ProjectCard key={p.project_ref} project={p} canManage={authed} />
              ))}
            </div>
          </>
        )}
      </AppLayout>

      {/* ★ 右下悬浮新建入口（★ 移动端更好点按；★ 游客不显示） */}
      {authed && (
        <button
          type="button"
          aria-label="新建项目"
          onClick={() => setCreateOpen(true)}
          className="fixed z-[50] flex items-center justify-center rounded-full transition-transform hover:scale-105"
          style={{
            right: 26,
            bottom: 26,
            width: 52,
            height: 52,
            background: 'var(--accent)',
            color: '#fff',
            border: 'none',
            cursor: 'pointer',
            boxShadow: 'var(--shadow-btn-accent)',
          }}
        >
          <PackagePlus size={22} />
        </button>
      )}

      <ProjectCreateModal open={createOpen} onClose={() => setCreateOpen(false)} onCreated={goProject} />
    </>
  )
}
