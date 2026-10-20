import { useState } from 'react'
import { MessageSquare, ThumbsUp, Trash2 } from 'lucide-react'
import type { AnchorKind, Comment } from '../../api/types'
import { useCommentLike, useDeleteComment } from '../../query/comments'
import { errorMessage } from '../../api/errors'
import ConfirmDialog from '../ui/ConfirmDialog'
import CommentComposer from './CommentComposer'
import { commentDeletable, type DeletePerm } from './perm'
import { bodyAfterReplyHead, firstMention, splitByMentions } from './mention'

/**
 * ★ 一条评论（`F3` 建 · `B214` 改「平铺 + 类型」）
 *
 * ## ★★★ 两种视觉，由 `kind` 一列决定（* 所有者原话）
 *
 * > 「**回复和@是两种不同的东西，嗯，视觉效果不一样，底层记录这两种不同类型就行**」
 *
 * | `kind` | 视觉 |
 * |---|---|
 * | `comment` | 普通评论 —— 没头没高亮 |
 * | `reply` | ★ 头部「**回复 @X**」（X 取正文第一个 @，* 正文里那个 @ 已提到头部） |
 * | `mention` | ★ 正文里的 @ **高亮**（行内提及） |
 * | `both` | ★ 两者都渲染 |
 *
 * ⚠★ 「回复谁」**记在正文的 @ 里**（* 没有 reply_to 列，* `B214`③）——
 *   · · ★ 所以这里是「从正文提第一个 @ 当回复头」+「其余 @ 按类型高亮」✅
 * ⚠★ 永无编辑入口（* 只删不改，* `B201③`）✅
 */
interface CommentItemProps {
  comment: Comment
  noteId: number
  anchor: AnchorKind
  /** 删除判据上下文（逐条判：评论作者本人 / 项目成员 / 管理员） */
  perm: DeletePerm
}

export default function CommentItem({ comment, noteId, anchor, perm }: CommentItemProps) {
  const [replying, setReplying] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [delErr, setDelErr] = useState('')
  const del = useDeleteComment(noteId)
  const canDelete = commentDeletable(comment, perm)
  // ★★ 评论赞：* 每条评论自己的计数（* 不需要 block_id）⚠
  const like = useCommentLike()
  const [likes, setLikes] = useState(comment.like_count ?? 0)

  const onLike = async () => {
    // ★ 乐观 +1，回包校正；失败回滚（* 后端只有计数，* 没有可回滚的持久状态）⚠
    setLikes((c) => c + 1)
    try {
      const r = await like.mutateAsync(comment.id)
      setLikes(r.like_count)
    } catch {
      setLikes((c) => Math.max(0, c - 1))
    }
  }

  const isReply = comment.kind === 'reply' || comment.kind === 'both'
  const highlight = comment.kind === 'mention' || comment.kind === 'both'
  const replyTarget = isReply ? firstMention(comment.body) : null
  // ★ `reply` 的那个 @ 已经进头部 ⇒ 正文去掉它（B站口径）；`both` 同理，只去第一个
  const shown = isReply ? bodyAfterReplyHead(comment.body) : comment.body

  const doDelete = async () => {
    setDelErr('')
    try {
      await del.mutateAsync(comment.id)
      setConfirming(false)
    } catch (e) {
      setDelErr(errorMessage(e))
    }
  }

  return (
    <div style={{ fontSize: 13 }}>
      <div className="flex items-center gap-2 flex-wrap">
        <span style={{ fontWeight: 600, fontSize: 12.5 }}>{comment.created_by || '匿名'}</span>
        {/* ★★ 视觉一：回复头（`reply` / `both`） */}
        {isReply && replyTarget && (
          <span className="faint" style={{ fontSize: 11 }}>
            回复 @{replyTarget}
          </span>
        )}
        <span className="faint" style={{ fontSize: 11 }}>
          {comment.created_at?.replace('T', ' ').slice(0, 16)}
        </span>
        {comment.orphaned && (
          <span className="tag" style={{ fontSize: 10, color: 'var(--warn)' }} title="原段落已变更或已删除">
            原段落已变更
          </span>
        )}
      </div>

      {comment.quote && (
        <div
          className="faint"
          style={{ fontSize: 11.5, borderLeft: '2px solid var(--card-border)', paddingLeft: 8, marginTop: 4 }}
        >
          {comment.quote}
        </div>
      )}

      {/* ★★ 视觉二：@ 高亮（`mention` / `both`）；其余类型纯文本 */}
      <div style={{ marginTop: 3, lineHeight: 1.75, whiteSpace: 'pre-wrap' }}>
        {highlight ? <HighlightedBody text={shown} /> : shown}
      </div>

      <div className="flex items-center gap-3 mt-1.5" style={{ fontSize: 11.5 }}>
        {/* ★★ 评论赞（* 所有者：「段评里面每个评论旁边有个评论赞」）⚠ */}
        <button
          type="button"
          className="flex items-center gap-1"
          style={{ color: likes > 0 ? 'var(--err)' : 'var(--text-sub)', cursor: 'pointer' }}
          title="给这条评论点赞"
          onClick={onLike}
        >
          <ThumbsUp size={11} fill={likes > 0 ? 'currentColor' : 'none'} />
          {likes}
        </button>
        <button
          type="button"
          className="flex items-center gap-1"
          style={{ color: 'var(--text-sub)', cursor: 'pointer' }}
          onClick={() => setReplying((v) => !v)}
        >
          <MessageSquare size={11} />
          回复
        </button>
        {canDelete && (
          <button
            type="button"
            className="flex items-center gap-1"
            style={{ color: 'var(--text-sub)', cursor: 'pointer' }}
            onClick={() => setConfirming(true)}
          >
            <Trash2 size={11} />
            删除
          </button>
        )}
      </div>

      {replying && (
        <div className="mt-2">
          <CommentComposer
            noteId={noteId}
            anchor={anchor}
            blockId={comment.block_id}
            replyTo={comment.created_by}
            autoFocus
            placeholder={`回复 @${comment.created_by || '某人'}……`}
            onCancelReply={() => setReplying(false)}
            onSent={() => setReplying(false)}
          />
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        title="删除评论"
        danger
        loading={del.isPending}
        error={delErr}
        confirmText="删除"
        message="删除后不可恢复，确定吗？"
        onConfirm={doDelete}
        onCancel={() => {
          setConfirming(false)
          setDelErr('')
        }}
      />
    </div>
  )
}

/** ★ 正文里的 @ 高亮（* 片段数组渲染，⛔ 不拼 HTML ——* 正文是用户输入）✅ */
function HighlightedBody({ text }: { text: string }) {
  return (
    <>
      {splitByMentions(text).map((p, i) =>
        p.mention ? (
          <span
            key={i}
            style={{ color: 'var(--accent)', fontWeight: 500 }}
          >
            {p.text}
          </span>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  )
}
