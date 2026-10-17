import { useState } from 'react'
import { CornerDownRight, MessageSquare, Trash2 } from 'lucide-react'
import type { AnchorKind, Comment } from '../../api/types'
import { useComments, useDeleteComment } from '../../query/comments'
import { errorMessage } from '../../api/errors'
import ConfirmDialog from '../ui/ConfirmDialog'
import CommentComposer from './CommentComposer'
import { commentDeletable, type DeletePerm } from './perm'

/**
 * ★ 单条评论（`F3` · `B201`② 楼中楼 · `B201③` 只删不改）
 *
 * ## ★★ 楼中楼 = B站口径（* 逐字原话）
 *
 * > 「**楼中楼就是B站那样的，先显示评论，然后评论里面可以有评论，类似弹幕的形式**」
 *
 * | 数据上 | 显示上 |
 * |---|---|
 * | `parent_id` 成链，* **深度不限** | ★ **压成两级**：顶级评论 + 可折叠的回复列表 ✅ |
 *
 * ## 三条口径
 *
 * | # | 口径 |
 * |---|---|
 * | ① | ★★ **永无编辑入口**（* 只删不改，* `B201③`）✅ |
 * | ② | ★ 回复默认**折叠**（* 「N 条回复」点开才加载 + 展开）✅ |
 * | ③ | ★ 删除要确认（* 评论**没有**回收站 ——* `B210` 只给笔记做了）⇒* 文案「不可恢复」⚠ |
 */
interface CommentItemProps {
  comment: Comment
  noteId: number
  anchor: AnchorKind
  /**
   * ★★ 删除判据的**上下文**（* ⛔ 不是单个布尔）⚠
   *   · · ★ 删除权是**逐条**判的：* 评论作者本人 / 项目成员 / 管理员（* `B207`⑤）✅
   *   · · ★ 传布尔就会漏掉「我回复的我自己的评论」这种 ✅
   */
  perm: DeletePerm
}

export default function CommentItem({ comment, noteId, anchor, perm }: CommentItemProps) {
  const canDelete = commentDeletable(comment, perm)
  const [replying, setReplying] = useState(false)
  const [showReplies, setShowReplies] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [delErr, setDelErr] = useState('')
  const del = useDeleteComment(noteId)

  // ★ 折叠状态才发请求（口径②：默认不加载回复）
  const replies = useComments(noteId, {
    anchor_kind: anchor,
    parent: comment.id,
    limit: 50,
  })

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
        <span className="faint" style={{ fontSize: 11 }}>
          {comment.created_at?.replace('T', ' ').slice(0, 16)}
        </span>
        {/* 失锚段评：原段落已变更或已删除（`orphaned` 后端标好） */}
        {comment.orphaned && (
          <span className="tag" style={{ fontSize: 10, color: 'var(--warn)' }} title="原段落已变更或已删除">
            原段落已变更
          </span>
        )}
      </div>

      {/* 段评的 quote 快照：那一刻的原文（`B203④`） */}
      {comment.quote && (
        <div
          className="faint"
          style={{
            fontSize: 11.5,
            borderLeft: '2px solid var(--card-border)',
            paddingLeft: 8,
            marginTop: 4,
          }}
        >
          {comment.quote}
        </div>
      )}

      <div style={{ marginTop: 3, lineHeight: 1.75, whiteSpace: 'pre-wrap' }}>{comment.body}</div>

      <div className="flex items-center gap-3 mt-1.5" style={{ fontSize: 11.5 }}>
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
        {comment.reply_count > 0 && (
          <button
            type="button"
            className="flex items-center gap-1"
            style={{ color: 'var(--text-sub)', cursor: 'pointer' }}
            onClick={() => setShowReplies((v) => !v)}
          >
            <CornerDownRight size={11} />
            {showReplies ? '收起回复' : `${comment.reply_count} 条回复`}
          </button>
        )}
      </div>

      {replying && (
        <div className="mt-2">
          <CommentComposer
            noteId={noteId}
            anchor={anchor}
            blockId={comment.block_id}
            parent={comment.id}
            parentAuthor={comment.created_by}
            autoFocus
            placeholder={`回复 @${comment.created_by || '某人'}……`}
            onCancelReply={() => setReplying(false)}
            onSent={() => {
              setReplying(false)
              setShowReplies(true)
            }}
          />
        </div>
      )}

      {/* 回复列表（压成两级：这里不再显示「回复的回复」的再折叠） */}
      {showReplies && (
      <div className="mt-2 flex flex-col gap-2.5" style={{ paddingLeft: 14, borderLeft: '1px solid var(--card-border)' }}>
      {replies.isLoading ? (
        <div className="faint" style={{ fontSize: 11.5 }}>加载中…</div>
      ) : (
        (replies.data?.items || []).map((r) => (
          <CommentItem
            key={r.id}
            comment={r}
            noteId={noteId}
            anchor={anchor}
            perm={perm}
          />
        ))
      )}
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
