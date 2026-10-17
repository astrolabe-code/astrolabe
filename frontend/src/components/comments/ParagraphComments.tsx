import { useState } from 'react'
import { MessageSquarePlus } from 'lucide-react'
import type { NoteBlock } from '../../api/types'
import { useComments } from '../../query/comments'
import { errorMessage } from '../../api/errors'
import LikeButton from '../likes/LikeButton'
import CommentComposer from './CommentComposer'
import CommentItem from './CommentItem'
import type { DeletePerm } from './perm'

/**
 * ★ 一段话 + 它的段评（`F3` · `B203④` 段评 · `B189` 失锚）
 *
 * ## ★★ 三条口径
 *
 * | # | 口径 |
 * |---|---|
 * | ① | ★ 段评**默认折叠**（* 「N 条段评」点开才加载）——* ⛔ 不给每段都常开列表（* 刷屏）⚠ |
 * | ② | ★ `quote` 后端快照 ⇒* 前端 **不传** ✅ |
 * | ③ | ★ 段赞与段评各是各的（* 同表不同锚，* `B187`）✅ |
 *
 * ⚠★ **代价如实记**：* 每段一条 `useComments` 查询（* 后端没有"整篇所有评论"端点）——
 *   · · ★ 折叠态**不发请求**（* 口径① 的附带好处：* 没点开就是 0 请求）✅
 *   · · ★ 展开几段就几发，* ⛔ 不是 N+1 全量 ✅
 */
interface ParagraphCommentsProps {
  noteId: number
  block: NoteBlock
  authed: boolean
  /** 删除判据上下文（逐条判） */
  perm: DeletePerm
}

export default function ParagraphComments({ noteId, block, authed, perm }: ParagraphCommentsProps) {
  const [open, setOpen] = useState(false)
  const [composing, setComposing] = useState(false)
  const comments = useComments(noteId, {
    anchor_kind: 'paragraph',
    block_id: block.id,
    limit: 50,
    // ⚠★ 折叠态不拉（口径①）
    enabled: false,
  })

  // ⚠ 上面的 enabled:false 会让 React Query 永不自动取 ⇒ 展开时手动 refetch
  //  （⛔ 不用 enabled: open —— 那会在关闭时也保留一次已取的数据，没必要）
  const load = () => {
    setOpen(true)
    void comments.refetch()
  }

  const items = comments.data?.items || []

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 flex-wrap">
        <LikeButton noteId={noteId} anchor="paragraph" blockId={block.id} size="sm" />
        {authed ? (
          <button
            type="button"
            className="flex items-center gap-1"
            style={{ fontSize: 11.5, color: 'var(--text-sub)', cursor: 'pointer' }}
            onClick={() => {
              setOpen(true)
              setComposing(true)
              if (!comments.data) void comments.refetch()
            }}
          >
            <MessageSquarePlus size={12} />
            写段评
          </button>
        ) : null}
        {block.comment_count > 0 && (
          <button
            type="button"
            style={{ fontSize: 11.5, color: 'var(--text-sub)', cursor: 'pointer' }}
            onClick={() => (open ? setOpen(false) : load())}
          >
            {open ? '收起段评' : `${block.comment_count} 条段评`}
          </button>
        )}
      </div>

      {open && (
        <div className="flex flex-col gap-3">
          {authed && composing && (
            <CommentComposer
              noteId={noteId}
              anchor="paragraph"
              blockId={block.id}
              autoFocus
              placeholder="就这一段说点什么……"
              onSent={() => setComposing(false)}
              onCancelReply={() => setComposing(false)}
            />
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
        </div>
      )}
    </div>
  )
}
