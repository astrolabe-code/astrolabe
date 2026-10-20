import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EyeOff, Lock, Pencil, ShieldAlert } from 'lucide-react'
import { errorMessage } from '../api/errors'
import { useNote } from '../query/notes'
import { useProject } from '../query/projects'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import LikeButton from '../components/likes/LikeButton'
import CommentSection from '../components/comments/CommentSection'
import ParagraphComments from '../components/comments/ParagraphComments'
import NoteEditor from '../components/notes/NoteEditor'
import ModeratePanel from '../components/admin/ModeratePanel'
import { kindMeta } from '../components/notes/kindMeta'

/**
 * ★ 笔记阅读页（`F3` · `/p/:projectRef/notes/:noteId`）
 *
 * ## ★★ 为什么必须是独立页（* ⛔ 不是抽屉 / 弹窗）
 *
 * ```
 * ★★ 评论 / 点赞 / 段评都挂在**笔记**上（* 不是节点）⇒* 它需要一个
 *   「能停下来读」的地方：* 可分享的 URL + 足够的纵向空间 ✅
 * ★★ 而 F2 的编辑器是 **Modal**（* 顺手改一笔就走）—— * 两件事形态不同，
 *   * ⛔ 不硬塞进同一个容器 ✅
 * ```
 *
 * ## ★★ 页面结构（* 自上而下）
 *
 * | 块 | 内容 |
 * |---|---|
 * | ① | 头部：* 返回项目 ·* kind 徽标 ·* 标题 ·* 作者/时间 ·* **章赞** ·* 编辑入口 |
 * | ② | 正文：* 按**后端 blocks** 逐段渲染（* `B188`：* 段落按空行分隔）✅ |
 * | ③ | 每段：* 段赞 + 写段评 + 该段的段评（* 默认折叠） |
 * | ④ | 章评区：* 输入框 + 列表（* 含失锚段评，* 后端已按策略并入） |
 *
 * ⚠★ 隐藏态（* `state=hidden`）：* **只有作者看得见** ⇒* 这里看到就打横幅 ✅
 * ⚠★ markdown 渲染**本批不做**（* 按段纯文）——* 段评锚点本来就在段上，* 不影响使用；
 *   * 上 markdown 渲染是后面一件独立的小事 ✅
 */
export default function NotePage() {
  const { projectRef = '', noteId = '' } = useParams<{ projectRef: string; noteId: string }>()
  const id = Number(noteId)
  const note = useNote(Number.isFinite(id) ? id : null)
  const project = useProject(projectRef)
  const me = useMe()
  const [editing, setEditing] = useState(false)
  const [moderating, setModerating] = useState(false)

  const n = note.data?.note
  const blocks = note.data?.blocks || []
  const authed = !!me.data?.authenticated
  const canEdit = !!project.data?.can_edit
  const meUsername = me.data?.username
  const isStaff = !!me.data?.is_staff
  // ★★ 可写 = 作者 ∨ 项目成员（* `B207`③）✅
  const canWrite = !!n && (n.created_by === meUsername || canEdit)
  // ★★ 删除判据上下文（* 逐条判：* 评论作者本人 / 项目成员 / 管理员，* `B207`⑤）✅
  const perm = { meUsername, canEdit, isStaff }

  if (note.isError) {
    return (
      <AppLayout title="笔记">
        <div className="card" style={{ padding: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>不存在或无权访问</div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
            {errorMessage(note.error)}
          </div>
          <div className="mt-4">
            <Link to={`/p/${encodeURIComponent(projectRef)}`}>
              <Button>回项目</Button>
            </Link>
          </div>
        </div>
      </AppLayout>
    )
  }

  if (note.isLoading || !n) {
    return (
      <AppLayout title="笔记">
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      </AppLayout>
    )
  }

  const meta = kindMeta(n.kind)
  const Icon = meta.icon

  return (
    <AppLayout
      title={n.title || '（无标题）'}
      actions={
        <div className="flex items-center gap-2">
          {/* ① 章赞 */}
          <LikeButton noteId={n.id} anchor="chapter" />
          {canWrite && (
            <Button icon={<Pencil size={13} />} onClick={() => setEditing(true)}>
              编辑
            </Button>
          )}
          {/* ★★ `F4`：管理处置入口（仅 staff；`B208`） */}
          {isStaff && (
            <Button icon={<ShieldAlert size={13} />} onClick={() => setModerating(true)}>
              管理
            </Button>
          )}
        </div>
      }
    >
      <div style={{ maxWidth: 760, margin: '0 auto' }}>
        {/* 隐藏横幅：只有作者看得到 */}
        {n.state === 'hidden' && (
          <div
            className="card flex items-start gap-2"
            style={{ padding: '10px 14px', marginBottom: 14, borderColor: 'var(--err)' }}
          >
            <EyeOff size={15} style={{ color: 'var(--err)', marginTop: 2 }} />
            <div style={{ fontSize: 12.5, lineHeight: 1.7 }}>
              <b>这篇笔记已被管理员隐藏</b>
              {n.moderation_reason ? `：${n.moderation_reason}` : ''}
              <div className="faint" style={{ fontSize: 11.5 }}>
                隐藏期间只有你（作者）能看到它。恢复请联系管理员。
              </div>
            </div>
          </div>
        )}

        {/* 头部信息 */}
        <div className="flex items-center gap-2 flex-wrap mb-3">
          <span className="tag" style={{ fontSize: 10.5 }}>
            <Icon size={11} style={{ marginRight: 3, verticalAlign: -1 }} />
            {meta.label}
          </span>
          {!n.is_public && (
            <span className="tag" style={{ fontSize: 10.5 }} title="只有作者可见">
              <Lock size={10} style={{ marginRight: 3, verticalAlign: -1 }} />
              私有
            </span>
          )}
          <span className="faint" style={{ fontSize: 11.5 }}>
            {n.created_by} · {n.created_at?.replace('T', ' ').slice(0, 16)}
          </span>
        </div>

        {/* ②③ 正文：按后端 blocks 逐段 */}
        <div className="card flex flex-col gap-5" style={{ padding: '16px 18px' }}>
          {blocks.map((b) => (
            <div key={b.id}>
              <div style={{ fontSize: 14, lineHeight: 1.9, whiteSpace: 'pre-wrap' }}>{b.text}</div>
              <div className="mt-1.5">
                <ParagraphComments noteId={n.id} block={b} authed={authed} perm={perm} />
              </div>
            </div>
          ))}
        </div>

        {/* ④ 章评区 */}
        <div className="card mt-4" style={{ padding: '16px 18px' }}>
          <CommentSection noteId={n.id} authed={authed} perm={perm} />
        </div>
      </div>

      {/* 编辑器（本页自持一份 Modal —— 与 NodePanel 那个各管各的入口） */}
      <NoteEditor
        open={editing}
        note={n}
        projectRef={projectRef}
        nodeId={n.node_id}
        onClose={() => setEditing(false)}
      />

      {/* ★★ `F4`：管理处置（隐藏 / 下架 / 恢复）—— 仅 staff 能打开 */}
      <ModeratePanel
        open={moderating}
        kind="note"
        target={n.id}
        currentState={n.state}
        onClose={() => setModerating(false)}
      />
    </AppLayout>
  )
}
