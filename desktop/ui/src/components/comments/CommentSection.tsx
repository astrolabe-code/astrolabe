import { useState } from 'react'
import type { Comment } from '../../api/types'
import { useComments } from '../../query/comments'
import { errorMessage } from '../../api/errors'
import CommentComposer from './CommentComposer'
import CommentItem from './CommentItem'
import type { DeletePerm } from './perm'

/**
 * ★ 章评区（`F3` 建 · `B214` 改平铺）
 *
 * ## ★★ 装什么
 *
 * ```
 * ★★ 章评（* anchor_kind=chapter）—— * 一列平铺，* 新的在前 ✅
 * ★★ **失锚的段评**也在这里（* 后端按策略并入，* 带 `orphaned=true`）✅
 *     · · ★ 前端照常渲染即可，* ⛔ 不自己过滤 ——* 策略是**项目级**的（* B189）⚠
 * ```
 *
 * ⚠ 写入口只对**登录用户**渲染（* 任何登录用户就能评，* `B207`⑤）✅
 */
interface CommentSectionProps {
  /** ★ 笔记的对外标识（* ref，⛔ 不是自增 pk）⚠ */
  noteId: string
  /** 登录用户才写得动 */
  authed: boolean
  /** 删除判据上下文（逐条判：评论作者/项目成员/管理员） */
  perm: DeletePerm
}

export default function CommentSection({ noteId, authed, perm }: CommentSectionProps) {
  // ★★ 排序：最新 / 最热（* 所有者：「评论要能按时间和热度排序」）⚠
  const [order, setOrder] = useState<'time' | 'hot'>('time')
  const comments = useComments(noteId, { anchor_kind: 'chapter', limit: 50, order })

  if (comments.isError) {
    return (
      <div className="text-sm" style={{ color: 'var(--err)' }}>
        评论加载失败：{errorMessage(comments.error)}
      </div>
    )
  }

  const items: Comment[] = comments.data?.items || []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <span style={{ fontSize: 13.5, fontWeight: 600 }}>评论</span>
        <span className="faint" style={{ fontSize: 11.5 }}>
          {comments.isLoading ? '…' : items.length}
        </span>

        {/* ★ 排序切换（* 最新 / 最热）⚠ */}
        <div
          style={{
            marginLeft: 'auto',
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

      {authed ? (
        <CommentComposer noteId={noteId} anchor="chapter" />
      ) : (
        <div className="faint" style={{ fontSize: 12 }}>
          登录后可评论。
        </div>
      )}

      {comments.isLoading ? (
        <div className="faint" style={{ fontSize: 12.5 }}>加载中…</div>
      ) : items.length === 0 ? (
        <div className="faint" style={{ fontSize: 12.5 }}>
          还没有人评论 —— 第一个说说的可能解开别人的困惑。
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {items.map((c) => (
            <CommentItem key={c.id} comment={c} noteId={noteId} anchor="chapter" perm={perm} />
          ))}
        </div>
      )}
    </div>
  )
}
