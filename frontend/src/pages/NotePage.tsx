import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EyeOff, Lock, Pencil, ShieldAlert } from 'lucide-react'
import { ApiRequestError, errorMessage } from '../api/errors'
import { useNote } from '../query/notes'
import { useProject } from '../query/projects'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import LikeButton from '../components/likes/LikeButton'
import CommentSection from '../components/comments/CommentSection'
import ParagraphComments from '../components/comments/ParagraphComments'
import MilkdownLazy from '../components/notes/MilkdownLazy'
import type { SelectionInfo } from '../components/notes/MilkdownView'
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
  // ★ 当前打开段评面板的那一段（* 由 Milkdown 里的气泡点击驱动）⚠
  const [activeFp, setActiveFp] = useState('')
  // ★ 右键「选中文字」小菜单 + 面板里预填的引用原文 ⚠
  const [sel, setSel] = useState<SelectionInfo | null>(null)
  const [panelQuote, setPanelQuote] = useState('')
  const [moderating, setModerating] = useState(false)

  const n = note.data?.note
  const blocks = note.data?.blocks || []
  const activeBlock = blocks.find((b) => b.fingerprint === activeFp)

  // ★ 点别处 / 滚动 / Esc 都关掉右键小菜单
  useEffect(() => {
    if (!sel) return
    const close = () => setSel(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSel(null)
    }
    document.addEventListener('click', close)
    document.addEventListener('scroll', close, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', close)
      document.removeEventListener('scroll', close, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [sel])
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
          {/* ★ 从搜索结果点进来时，索引可能比库慢半拍 ⇒ 明确告诉他"被移除了" ⚠ */}
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            {note.error instanceof ApiRequestError && note.error.status === 404
              ? '这篇笔记已经被移除了'
              : '不存在或无权访问'}
          </div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
            {note.error instanceof ApiRequestError && note.error.status === 404
              ? '可能是作者删除了，或者被管理员隐藏了。'
              : errorMessage(note.error)}
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
          {/* ★★★ 类型徽标：* **用该类型的专属色**（* 所有者：「这些还要有颜色呀，
              困惑这些有对应颜色的」）+ 图标文字同一行 ⚠
              · · ⛔ 不再套 .tag（* 中性灰边）——* 文字 / 边框取类型色，背景透明 ✅ */}
          <span
            style={{
              fontSize: 10.5,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 3,
              whiteSpace: 'nowrap',
              padding: '1px 8px',
              borderRadius: 999,
              lineHeight: '16px',
              color: meta.color,
              border: `1px solid ${meta.color}`,
              background: 'transparent',
            }}
          >
            <Icon size={11} />
            {meta.label}
          </span>
          {!n.is_public && (
            <span
              className="tag"
              style={{
                fontSize: 10.5,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 3,
                whiteSpace: 'nowrap',
              }}
              title="只有作者可见"
            >
              <Lock size={10} />
              私有
            </span>
          )}
          <span className="faint" style={{ fontSize: 11.5 }}>
            {n.created_by} · {n.created_at?.replace('T', ' ').slice(0, 16)}
          </span>
        </div>

        {/* ②③ 正文：**整篇** Milkdown 只读渲染（`D108` / `B242`）
            ★★ 段评气泡由 MilkdownView 用 ProseMirror Decoration 挂在段落末尾；
               点一下就打开下面那个面板 ✅ */}
        <div className="card flex flex-col gap-5" style={{ padding: '16px 18px' }}>
          <MilkdownLazy
            text={n.body || ''}
            blocks={blocks}
            authed={authed}
            onOpenBlock={(b) => {
              setPanelQuote('')
              setActiveFp(b.fingerprint)
            }}
            onSelection={(info) => setSel(info)}
          />
        </div>

        {/* ⑤ 右键小菜单：选中文字 ⇒ 写段评（* 番茄小说那种）⚠ */}
      {sel && (
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'fixed',
            left: sel.x,
            top: sel.y,
            zIndex: 90,
            background: 'var(--card)',
            border: '1px solid var(--card-border)',
            borderRadius: 8,
            boxShadow: 'var(--shadow-card-hover)',
            padding: 4,
          }}
        >
          <button
            type="button"
            disabled={!sel.block}
            title={sel.block ? '对选中的文字写段评' : '这段没能对上段落，暂不支持段评'}
            onClick={() => {
              if (!sel.block) return
              setPanelQuote(sel.quote)
              setActiveFp(sel.block.fingerprint)
              setSel(null)
            }}
            style={{
              display: 'block',
              padding: '6px 14px',
              fontSize: 12.5,
              fontFamily: 'var(--font-ui)',
              color: sel.block ? 'var(--text-main)' : 'var(--text-faint)',
              background: 'transparent',
              border: 'none',
              borderRadius: 6,
              cursor: sel.block ? 'pointer' : 'not-allowed',
            }}
          >
            写段评
          </button>
        </div>
      )}

      {/* ④ 段评面板（* 只渲染当前那一段，* 文字由上面的 Milkdown 画）⚠ */}
        {activeBlock && (
          <div className="card mt-4" style={{ padding: '12px 16px' }}>
            <ParagraphComments
              noteId={n.id}
              block={activeBlock}
              authed={authed}
              perm={perm}
              renderText={false}
              panelOpen
              quote={panelQuote}
              onPanelOpenChange={(o) => {
                if (!o) {
                  setActiveFp('')
                  setPanelQuote('')
                }
              }}
            />
          </div>
        )}

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
