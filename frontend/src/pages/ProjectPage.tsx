import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EyeOff, Lock, Settings, ShieldAlert, Workflow } from 'lucide-react'
import type { GraphNode } from '../lib/mergeGraph'
import { errorMessage } from '../api/errors'
import { useProject } from '../query/projects'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import NodeList from '../components/node/NodeList'
import NodePanel from '../components/node/NodePanel'
import ModeratePanel from '../components/admin/ModeratePanel'

/**
 * ★ 项目页（`F2` · D92）——* 双栏：左节点列表 + 右笔记面板
 *
 * ## ⚠★ 与"图谱画布页"的关系（先划清界）
 *
 * | | 本页 | 画布页（2b，未做） |
 * |---|---|---|
 * | 节点呈现 | **列表**（搜索 + 过滤 + 分页） | 画布（布局 + 拖拽 + 缩放） |
 * | 解决的 | 「**怎么走到某个节点**」 | 「**看清结构关系**」 |
 *
 * ⚠★ 所以本页**刻意简单** ——* 它不是画布的临时替代，* 是笔记层的家 ✅
 *
 * ## ★★ 三条状态口径
 *
 * | # | 状态 | 前端表现 |
 * |---|---|---|
 * | ① | `state=hidden`（管理员隐藏） | ★★ **只有 owner 打得开**（后端 404 其余人）⇒ 顶部横幅显示 `moderation_reason` ✅ |
 * | ② | 私有项目 / 无权 | 404 文案「不存在或无权访问」——* ⛔ 不区分、* ⛔ 不提示"其实存在" ✅ |
 * | ③ | 未定版（图还没解析） | 节点列表空态引导去工作区拉取 ✅ |
 */
export default function ProjectPage() {
  const { projectRef = '' } = useParams<{ projectRef: string }>()
  const project = useProject(projectRef)
  const me = useMe()
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [moderating, setModerating] = useState(false)

  const p = project.data
  const canWrite = !!p?.can_edit
  const meUsername = me.data?.username

  if (project.isError) {
    return (
      <AppLayout title="项目">
        <div className="card" style={{ padding: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>不存在或无权访问</div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
            {errorMessage(project.error)}
          </div>
          <div className="mt-4">
            <Link to="/workspace">
              <Button>回工作区</Button>
            </Link>
          </div>
        </div>
      </AppLayout>
    )
  }

  if (project.isLoading || !p) {
    return (
      <AppLayout title="项目">
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      </AppLayout>
    )
  }

  return (
    <AppLayout
      page={false}
      title={
        <span className="flex items-center gap-2">
          {p.name || '未命名项目'}
          {!p.is_public && (
            <span className="tag" style={{ fontSize: 10.5 }} title="私有项目：只有项目成员可见">
              <Lock size={10} style={{ marginRight: 3, verticalAlign: -1 }} />
              私有
            </span>
          )}
        </span>
      }
      actions={
        <div className="flex items-center gap-2">
          {/* ★★ `D98`：图谱入口 ——* 谁都能看（读权限由后端判）✅ */}
          <Link to={`/p/${encodeURIComponent(projectRef)}/graph`}>
            <Button icon={<Workflow size={14} />}>图谱</Button>
          </Link>
          {canWrite && (
            <Link to={`/p/${encodeURIComponent(projectRef)}/settings`}>
              <Button icon={<Settings size={14} />}>设置</Button>
            </Link>
          )}
          {/* ★★ `F4`：**管理处置入口** ——* 只有 staff 才渲染（`B208`）⚠
              · · ⚠ 这里只决定"显不显示"；* 真正的拦截在后端 `@staff_only` ✅ */}
          {me.data?.is_staff && (
            <Button icon={<ShieldAlert size={14} />} onClick={() => setModerating(true)}>
              管理
            </Button>
          )}
        </div>
      }
    >
      {/* ① 隐藏横幅：只有 owner 看得到（后端把其余人挡在 404） */}
      {p.state === 'hidden' && (
        <div
          className="card"
          style={{
            padding: '10px 14px',
            marginBottom: 12,
            borderColor: 'var(--err)',
            display: 'flex',
            gap: 8,
            alignItems: 'flex-start',
          }}
        >
          <EyeOff size={15} style={{ color: 'var(--err)', marginTop: 2 }} />
          <div style={{ fontSize: 12.5, lineHeight: 1.7 }}>
            <b>这个项目已被管理员隐藏</b>
            {p.moderation_reason ? `：${p.moderation_reason}` : ''}
            <div className="faint" style={{ fontSize: 11.5 }}>
              隐藏期间只有你（作者）能看到它，别人无法访问。恢复请联系管理员。
            </div>
          </div>
        </div>
      )}

      {p.desc && (
        <div className="faint" style={{ fontSize: 12.5, marginBottom: 12 }}>
          {p.desc}
        </div>
      )}

      {/* 双栏 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(240px, 320px) minmax(0, 1fr)',
          gap: 14,
          alignItems: 'start',
        }}
      >
        <div className="card" style={{ padding: 12, position: 'sticky', top: 76 }}>
          <div className="flex items-center justify-between mb-2.5">
            <span style={{ fontSize: 12.5, fontWeight: 600 }}>节点</span>
            <span className="faint" style={{ fontSize: 11 }}>
              {p.node_count ?? 0} 个
            </span>
          </div>
          <NodeList projectRef={projectRef} selectedUid={selected?.uid ?? null} onSelect={setSelected} />
        </div>

        <NodePanel projectRef={projectRef} node={selected} canWrite={canWrite} meUsername={meUsername} />
      </div>

      {/* ★★ `F4`：管理处置（隐藏 / 下架 / 恢复）—— 仅 staff 能打开 */}
      <ModeratePanel
        open={moderating}
        kind="project"
        target={projectRef}
        currentState={p.state}
        onClose={() => setModerating(false)}
      />
    </AppLayout>
  )
}
