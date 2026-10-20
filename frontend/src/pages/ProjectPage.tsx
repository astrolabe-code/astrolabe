import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EyeOff, Lock, Settings, ShieldAlert, Workflow } from 'lucide-react'
import type { GraphNode } from '../lib/mergeGraph'
import { errorMessage } from '../api/errors'
import { useProject } from '../query/projects'
import { useMe } from '../hooks/useMe'
import { useMediaQuery } from '../hooks/useMediaQuery'
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
  // ★★ 窄屏 ⇒ 单列（* 否则 320px 列表 + 60px 正文，挤成一长条）⚠
  const isNarrow = useMediaQuery('(max-width: 900px)')

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
      // ★★★ 不再传 title（* 所有者：「不要在这个页面左上部位显示项目名称了，
      //   一个黑色大字，还挤在左边了，太怪了」）⚠
      //   · · ★ 同时用回 `.page` 容器 ⇒* 内容有左右留白，* 不再贴着屏幕边缘 ⚠
      actions={
        <div className="flex items-center gap-2" style={{ marginLeft: 'auto' }}>
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

      {/* ★★★ 双栏（* 窄屏单列）：
          · · 所有者：「这个页面的左边没有列表之类的，完全平铺很长，导致页面看起来
            很怪」——* 列表有 137 个节点却没限高 ⇒ 左栏 5977px，整页被拉成一条长列 ⚠
          · · ★ 左栏**独立滚动**（sticky + maxHeight）⇒ 页面高度只由右栏决定 ✅ */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: isNarrow ? '1fr' : 'minmax(240px, 320px) minmax(0, 1fr)',
          gap: 14,
          alignItems: 'start',
        }}
      >
        <div
          className="card"
          style={{
            padding: 12,
            display: 'flex',
            flexDirection: 'column',
            // ★ 桌面：粘在视口内、自己滚；* 窄屏：只占 42vh，避免把页面撑长 ⚠
            position: isNarrow ? 'static' : 'sticky',
            top: isNarrow ? undefined : 76,
            maxHeight: isNarrow ? '42vh' : 'calc(100vh - 96px)',
            overflow: 'hidden',
          }}
        >
          <div className="flex items-center justify-between mb-2.5" style={{ flexShrink: 0 }}>
            <span style={{ fontSize: 12.5, fontWeight: 600 }}>节点</span>
            <span className="faint" style={{ fontSize: 11 }}>
              {p.node_count ?? 0} 个
            </span>
          </div>
          {/* ★ 列表区**独立滚动**（* minHeight:0 是关键，否则 flex 子项不肯缩）⚠ */}
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
            <NodeList
              projectRef={projectRef}
              selectedUid={selected?.uid ?? null}
              onSelect={setSelected}
            />
          </div>
        </div>

        {/* ★★★ 右侧**始终是一整块白色面板**（* 所有者：「右边的写作区也没有白色
            背景填满，而且没有一开始就出现」）——
            · · ⛔ 不再依赖 NodePanel 自己画卡：* 没选节点时它返回空态、没有背景 ⚠
            · · ★ 背景/边框/最小高度由这层统一给，* NodePanel 传 `flat` ✅ */}
        <div
          className="card"
          style={{
            minHeight: isNarrow ? 320 : 480,
            display: 'flex',
            flexDirection: 'column',
            padding: 0,
            overflow: 'hidden',
          }}
        >
          <NodePanel
            projectRef={projectRef}
            node={selected}
            canWrite={canWrite}
            meUsername={meUsername}
            flat
          />
        </div>
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
