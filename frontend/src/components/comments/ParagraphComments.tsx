import { useEffect, useState } from 'react'
import { MessageCircle, MessageSquarePlus } from 'lucide-react'
import type { NoteBlock } from '../../api/types'
import { useQueryClient } from '@tanstack/react-query'
import { useComments } from '../../query/comments'
import { errorMessage } from '../../api/errors'
import CommentComposer from './CommentComposer'
import CommentItem from './CommentItem'
import Modal from '../ui/Modal'
import Markdown from '../notes/Markdown'
import type { DeletePerm } from './perm'

/**
 * ★★ 一段正文 + 它的段评（`F3` · `B203④`）
 *
 * ## ★★★ 交互（所有者原话）
 *
 * > 「打开笔记后，不是有段评和点赞嘛？现在直接写在一个段下面的，不好看。应该
 * >   选中文字，然后右键，弹出一个弹窗，里面写评论。就跟番茄小说里写评论的
 * >   行为一样。」
 *
 * ```
 * ┌ 正文段落 ──────────────────────── 💬3 ┐  ← 有段评才显示右上角气泡数字
 * │ 选中文字 → 右键 → 「💬 就这段写评论」  │
 * └───────────────────────────────────────┘
 *         ↓ 右键菜单 / 点气泡
 *    ┌ 弹窗：引用原文 + 段赞 + 评论列表 + 输入框 ┐
 *    └──────────────────────────────────────────┘
 * ```
 *
 * ★ 段落**下方不再常驻**「段赞 / 写段评 / N 条段评」那一排（* 原来嫌乱）⚠
 * ★ 未选中文字时右键 ⇒ **放行浏览器原生菜单**（* 复制 / 翻译照常可用）✅
 * ★ 未登录 ⇒ 不拦截右键（* 也就没有写段评入口）⚠
 */
interface ParagraphCommentsProps {
  noteId: number
  block: NoteBlock
  authed: boolean
  /** 删除判据上下文（逐条判） */
  perm: DeletePerm
}

interface MenuState {
  x: number
  y: number
}

export default function ParagraphComments({ noteId, block, authed, perm }: ParagraphCommentsProps) {
  /** ★ 右键小菜单（* 只有选中了文字才出现）⚠ */
  const [menu, setMenu] = useState<MenuState | null>(null)
  /** ★ 弹窗（* 写评论 / 看评论共用）⚠ */
  const [open, setOpen] = useState(false)
  /** ★ 弹窗顶部引用的原文（* 右键选中时的那段字）⚠ */
  const [quote, setQuote] = useState('')

  const qc = useQueryClient()
  const comments = useComments(noteId, {
    anchor_kind: 'paragraph',
    block_id: block.id,
    limit: 50,
    // ⚠ 折叠态不拉（口径①）
    enabled: false,
  })

  // ★ 右键菜单：点别处 / 滚动 / Esc 都关掉
  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenu(null)
    }
    document.addEventListener('click', close)
    document.addEventListener('scroll', close, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', close)
      document.removeEventListener('scroll', close, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [menu])

  const openPanel = () => {
    setOpen(true)
    if (!comments.data) void comments.refetch()
  }

  const onContextMenu = (e: React.MouseEvent) => {
    // ★ 未登录 ⇒ 不拦截（* 原生菜单照常）⚠
    if (!authed) return
    const sel = window.getSelection()?.toString().trim() ?? ''
    // ★ 没选中文字 ⇒ 放行原生菜单（* 复制 / 检查元素等照常）✅
    if (!sel) return
    e.preventDefault()
    setQuote(sel.length > 200 ? `${sel.slice(0, 200)}…` : sel)
    setMenu({ x: e.clientX, y: e.clientY })
  }

  const items = comments.data?.items || []
  const hasComments = block.comment_count > 0

  return (
    <div style={{ position: 'relative' }}>
      {/* ---- 正文 ---- */}
      <div
        onContextMenu={onContextMenu}
        style={{
          fontSize: 14,
          lineHeight: 1.9,
          // ★★ 正文按 **markdown 渲染**（* 所有者：「点击卡片后，要以markdown渲染，
          //   · · 你现在还是原来的文本」）——* 标题 / 粗体 / 列表 / 代码都出来 ⚠
          //   · · ⛔ 不再 `whiteSpace: 'pre-wrap'`（* 那会把 markdown 源码原样显示）⚠
          userSelect: 'text',
        }}
      >
        {/* ★★★ 段评气泡作为 **trailing** 跟在段落末尾（* 所有者：「段评的气泡要
            跟着相应段落之后呀。你现在放在最右边，自成一排了」）⚠ */}
        <Markdown
          text={block.text}
          trailing={
            hasComments ? (
              <button
                type="button"
                onClick={openPanel}
                title={`${block.comment_count} 条段评`}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 2,
                  padding: '0 6px',
                  height: 17,
                  borderRadius: 999,
                  fontSize: 10.5,
                  lineHeight: 1,
                  color: 'var(--accent)',
                  background: 'var(--accent-dim)',
                  border: '1px solid transparent',
                  cursor: 'pointer',
                  verticalAlign: 'middle',
                }}
              >
                <MessageCircle size={10} />
                {block.comment_count}
              </button>
            ) : null
          }
        />
      </div>

      {/* ---- 右键菜单 ---- */}
      {menu && (
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'fixed',
            left: Math.min(menu.x, window.innerWidth - 200),
            top: Math.min(menu.y, window.innerHeight - 90),
            zIndex: 120,
            minWidth: 168,
            padding: 4,
            borderRadius: 10,
            background: 'var(--card)',
            border: '1px solid var(--card-border)',
            boxShadow: '0 10px 28px rgba(15,23,42,.30)',
          }}
        >
          <button
            type="button"
            onClick={() => {
              setMenu(null)
              openPanel()
            }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 7,
              width: '100%',
              padding: '7px 10px',
              borderRadius: 7,
              border: 'none',
              background: 'transparent',
              color: 'var(--text-main)',
              fontSize: 12.5,
              cursor: 'pointer',
              textAlign: 'left',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--accent-dim)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            <MessageSquarePlus size={13} />
            就这段写评论
          </button>
        </div>
      )}

      {/* ---- 弹窗：引用 + 段赞 + 列表 + 输入框 ---- */}
      <Modal
        open={open}
        title="段评"
        width={520}
        onClose={() => {
          setOpen(false)
          setQuote('')
        }}
      >
        {/* 引用原文（* 只展示，* 后端自己存 quote 快照）⚠ */}
        {quote && (
          <div
            style={{
              marginBottom: 10,
              padding: '7px 10px',
              borderLeft: '3px solid var(--accent)',
              background: 'var(--accent-dim)',
              borderRadius: 4,
              fontSize: 12,
              lineHeight: 1.7,
              color: 'var(--text-sub)',
            }}
          >
            {quote}
          </div>
        )}

        {authed && (
          <div style={{ marginBottom: 12 }}>
            <CommentComposer
              noteId={noteId}
              anchor="paragraph"
              blockId={block.id}
              autoFocus
              placeholder="就这一段说点什么……"
              onSent={() => {
                setQuote('')
                void comments.refetch()
                // ★ 段评数在 note.blocks 里 ⇒* 必须刷新 note，* 否则气泡数字不涨 ⚠
                void qc.invalidateQueries({ queryKey: ['note', noteId] })
              }}
            />
          </div>
        )}

        {comments.isError ? (
          <div className="text-xs" style={{ color: 'var(--err)' }}>
            {errorMessage(comments.error)}
          </div>
        ) : items.length === 0 ? (
          <div className="faint" style={{ fontSize: 11.5 }}>
            这段还没有段评。
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {items.map((c) => (
              <CommentItem
                key={c.id}
                comment={c}
                noteId={noteId}
                anchor="paragraph"
                perm={perm}
              />
            ))}
          </div>
        )}
      </Modal>
    </div>
  )
}
