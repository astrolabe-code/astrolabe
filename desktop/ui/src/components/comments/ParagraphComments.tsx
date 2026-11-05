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
  /** ★ 笔记的对外标识（* ref，⛔ 不是自增 pk）⚠ */
  noteId: string
  block: NoteBlock
  authed: boolean
  /** 删除判据上下文（逐条判） */
  perm: DeletePerm
  /**
   * ★ 是否渲染段落文字（* `D108` 整篇渲染后由 MilkdownView 画，
   *   这里只留面板 ⇒ 传 false）⚠
   */
  renderText?: boolean
  /** ★ 面板开关（* 受控：由外层的段评气泡点击驱动）⚠ */
  panelOpen?: boolean
  onPanelOpenChange?: (open: boolean) => void
  /**
   * ★ 预填的「引用原文」（* 整篇渲染后，右键选中文字由外层传来）⚠
   *   · · 变化时同步进内部状态；* 传空串 = 不带引用 ✅
   */
  quote?: string
}

interface MenuState {
  x: number
  y: number
}

export default function ParagraphComments({
  noteId,
  block,
  authed,
  perm,
  renderText = true,
  panelOpen,
  onPanelOpenChange,
  quote: quoteProp,
}: ParagraphCommentsProps) {
  /** ★ 右键小菜单（* 只有选中了文字才出现）⚠ */
  const [menu, setMenu] = useState<MenuState | null>(null)
  /** ★ 弹窗（* 写评论 / 看评论共用）⚠
      · · 受控（panelOpen 传入）优先；* 没传才用内部状态 ✅ */
  const [openInner, setOpenInner] = useState(false)
  const open = panelOpen ?? openInner
  const setOpen = (v: boolean) => {
    onPanelOpenChange?.(v)
    if (panelOpen === undefined) setOpenInner(v)
  }
  /** ★ 弹窗顶部引用的原文（* 右键选中时的那段字）⚠ */
  const [quote, setQuote] = useState('')
  // ★ 外层传入的引用文字 ⇒ 同步进来（* 右键选中那几下）⚠
  useEffect(() => {
    if (quoteProp !== undefined) setQuote(quoteProp)
  }, [quoteProp])

  const qc = useQueryClient()
  // ★★ 排序：最新 / 最热（* 段评也要能按热度看）⚠
  const [order, setOrder] = useState<'time' | 'hot'>('time')

  const comments = useComments(noteId, {
    anchor_kind: 'paragraph',
    fingerprint: block.fingerprint,
    limit: 50,
    order,
    // ⚠ 折叠态不拉（口径①）
    // ★★ 2026-10-24：**面板打开时才拉** —— 原来固定 false，
    //    靠组件内部的 openPanel() 手动 refetch；面板改成外部受控后
    //    那条链路断了 ⇒ 打开面板看不到原有段评（所有者实测）⚠
    enabled: open,
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

  // ★ 外部受控打开（`panelOpen`）时，* 也把数据拉起来 ⚠
  useEffect(() => {
    if (open && !comments.data && !comments.isFetching) void comments.refetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

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
      {/* ---- 正文（* 整篇渲染时关掉，* 由 MilkdownView 画 + 挂气泡）---- */}
      {renderText && (
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
      )}

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
        // ★ 内容区不滚 ——* 里面「列表滚动 + 输入框固定」自己控制 ⚠
        noScroll
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


        {/* ★ 排序切换（* 最新 / 最热）⚠ */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            marginBottom: 8,
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              gap: 2,
              padding: 2,
              borderRadius: 999,
              background: 'var(--bg-deep)',
            }}
          >
            {(['time', 'hot'] as const).map((o) => (
              <button
                key={o}
                type="button"
                onClick={() => setOrder(o)}
                style={{
                  padding: '2px 10px',
                  borderRadius: 999,
                  fontSize: 11,
                  lineHeight: '17px',
                  border: 'none',
                  cursor: 'pointer',
                  background: order === o ? 'var(--card)' : 'transparent',
                  color: order === o ? 'var(--text-main)' : 'var(--text-sub)',
                  boxShadow: order === o ? '0 1px 3px rgba(15,23,42,.12)' : 'none',
                }}
              >
                {o === 'time' ? '最新' : '最热'}
              </button>
            ))}
          </div>
        </div>

        {/* ★★★ **评论列表 = 滚动区**（* 所有者：「段评论区应该是有滑块的」）⚠
            · · 固定最大高度 44vh，超出就在**列表内部**滚动；
            · · 输入框固定在下面，不跟着一起滚 ✅ */}
        <div
          style={{
            maxHeight: '44vh',
            overflowY: 'auto',
            paddingRight: 4,
            // ★ 滚动条样式（* 细一点，不抢眼）⚠
            scrollbarWidth: 'thin',
          }}
        >
          {comments.isError ? (
            <div className="text-xs" style={{ color: 'var(--err)' }}>
              {errorMessage(comments.error)}
            </div>
          ) : items.length === 0 ? (
            <div className="faint" style={{ fontSize: 11.5 }}>
              这段还没有段评 —— 在下面写第一条。
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
        </div>

        {/* ★★★ **写评论 = 固定在列表下面**（* 所有者：「写窗口和发送按钮应该在
            评论的下面」）⚠ */}
        {authed && (
          <div
            style={{
              marginTop: 12,
              paddingTop: 10,
              borderTop: '1px solid var(--card-border)',
              flexShrink: 0,
            }}
          >
            <CommentComposer
              noteId={noteId}
              anchor="paragraph"
              fingerprint={block.fingerprint}
              autoFocus={false}
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
      </Modal>
    </div>
  )
}
