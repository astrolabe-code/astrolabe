import { useMemo, useState } from 'react'
import { CornerDownRight, MessageSquare, Trash2 } from 'lucide-react'
import type { AnchorKind, Comment } from '../../api/types'
import { useComments, useDeleteComment } from '../../query/comments'
import { errorMessage } from '../../api/errors'
import ConfirmDialog from '../ui/ConfirmDialog'
import CommentComposer from './CommentComposer'
import { commentDeletable, type DeletePerm } from './perm'

/**
 * ★ 评论三件套（`F3` 建 · `B213`/`D94` 改平铺）
 *
 * ## ★★★ B站口径（* 所有者裁定，* 逐字）
 *
 * > 「**楼中楼回复的回复会缩进显示，不要这样，像B站那样有回复谁就行了，深度不限**」
 *
 * | 件 | 管什么 |
 * |---|---|
 * | `CommentItem` | **顶级**评论：正文 + 「N 条回复」折叠钮 + 回复 / 删除 |
 * | `ReplyThread` | 展开后的**平铺线程**：一次拿整棵子树（`?parent=`，`B213`） |
 * | `CommentRow` | 平铺里的**一行**：`回复 @谁` 前缀 + 正文 + 回复 / 删除 |
 *
 * ## ★★ 三条硬口径
 *
 * | # | 口径 |
 * |---|---|
 * | ① | ★★ **平铺不缩进**（* `D94`①）——* 所有回复同一层，* 按时间旧的在上 ✅ |
 * | ② | ★★ 每条带头「**回复 @谁**」（* 作者映射从「根 + 子树」里建，* ⛔ 不额外请求）✅ |
 * | ③ | ★★ **永无编辑入口**（* 只删不改，* `B201③`）✅ |
 *
 * ⚠ 「N 条回复」上的数字是**直接回复数**（* 后端 `reply_count` 口径）——
 *   · · ★ 展开后楼顶显示**真实条数**（* 子树 `total`）自愈（* `B213③`）⚠
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
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [delErr, setDelErr] = useState('')
  const del = useDeleteComment(noteId)
  const canDelete = commentDeletable(comment, perm)

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
      <CommentHead comment={comment} />
      {comment.quote && <Quote text={comment.quote} />}
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
            onClick={() => setOpen((v) => !v)}
          >
            <CornerDownRight size={11} />
            {open ? '收起回复' : `${comment.reply_count} 条回复`}
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
              setOpen(true)
            }}
          />
        </div>
      )}

      {open && (
        <ReplyThread root={comment} noteId={noteId} anchor={anchor} perm={perm} />
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

/**
 * ★★ **平铺线程**（* `B213` 的数据 + `D94` 的显示）⚠
 *
 * ★ 一次拿整棵子树（* `?parent=<根id>` ⇒ 全部后代，* 深度不限）✅
 * ★ 作者映射从「根 + 子树」建 ⇒* 每条都能解析「回复 @谁」，* ⛔ 不额外请求 ✅
 */
function ReplyThread({
  root,
  noteId,
  anchor,
  perm,
}: {
  root: Comment
  noteId: number
  anchor: AnchorKind
  perm: DeletePerm
}) {
  const replies = useComments(noteId, {
    anchor_kind: anchor,
    parent: root.id,
    limit: 200,
  })
  const items = replies.data?.items || []

  /** ★ 作者映射（根也在里 ——* 回复根评论的那条要能显示「回复 @根作者」）✅ */
  const authorOf = useMemo(() => {
    const m: Record<number, string> = { [root.id]: root.created_by }
    for (const r of items) m[r.id] = r.created_by
    return m
  }, [root.id, root.created_by, items])

  if (replies.isLoading) {
    return <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>加载中…</div>
  }
  if (items.length === 0) {
    return (
      <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
        还没有回复。
      </div>
    )
  }

  return (
    <div className="mt-2.5 flex flex-col gap-2.5">
      {/* ★★ 楼顶显示**真实条数**（子树 total）——* 未展开时按钮上是直接回复数（`B213③`）✅ */}
      <div className="faint" style={{ fontSize: 11 }}>
        共 {replies.data?.total ?? items.length} 条回复
      </div>
      {items.map((r) => (
        <CommentRow
          key={r.id}
          comment={r}
          noteId={noteId}
          anchor={anchor}
          perm={perm}
          parentAuthor={authorOf[r.parent_id ?? 0] ?? ''}
        />
      ))}
    </div>
  )
}

/**
 * ★ 平铺线程里的**一行**（* `D94`：* ⛔ 不缩进，* 带头「回复 @谁」）⚠
 *
 * ⚠ 与 `CommentItem` 的差别：* **没有**「N 条回复」折叠钮（* 它的回复本来就在
 *   同一棵平铺树里，* `B213`）——* ⛔ 不再有下一层 ✅
 */
function CommentRow({
  comment,
  noteId,
  anchor,
  perm,
  parentAuthor,
}: {
  comment: Comment
  noteId: number
  anchor: AnchorKind
  perm: DeletePerm
  parentAuthor: string
}) {
  const [replying, setReplying] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [delErr, setDelErr] = useState('')
  const del = useDeleteComment(noteId)
  const canDelete = commentDeletable(comment, perm)

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
        {/* ★★ `D94`②：回复谁（B站口径）✅ */}
        {parentAuthor && parentAuthor !== comment.created_by && (
          <span className="faint" style={{ fontSize: 11 }}>
            回复 @{parentAuthor}
          </span>
        )}
        <span className="faint" style={{ fontSize: 11 }}>
          {comment.created_at?.replace('T', ' ').slice(11, 16)}
        </span>
        {comment.orphaned && (
          <span className="tag" style={{ fontSize: 10, color: 'var(--warn)' }} title="原段落已变更或已删除">
            原段落已变更
          </span>
        )}
      </div>
      <div style={{ marginTop: 3, lineHeight: 1.75, whiteSpace: 'pre-wrap' }}>{comment.body}</div>

      <div className="flex items-center gap-3 mt-1" style={{ fontSize: 11.5 }}>
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
            parent={comment.id}
            parentAuthor={comment.created_by}
            autoFocus
            placeholder={`回复 @${comment.created_by || '某人'}……`}
            onCancelReply={() => setReplying(false)}
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

/* ---------------------------------------------------------------- 共用小件 */

/** ★ 评论头：作者 + 时间（顶级用全日期，平铺行用时刻）✅ */
function CommentHead({ comment }: { comment: Comment }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span style={{ fontWeight: 600, fontSize: 12.5 }}>{comment.created_by || '匿名'}</span>
      <span className="faint" style={{ fontSize: 11 }}>
        {comment.created_at?.replace('T', ' ').slice(0, 16)}
      </span>
      {comment.orphaned && (
        <span className="tag" style={{ fontSize: 10, color: 'var(--warn)' }} title="原段落已变更或已删除">
          原段落已变更
        </span>
      )}
    </div>
  )
}

/** ★ 段评的 quote 快照：那一刻的原文（`B203④`）✅ */
function Quote({ text }: { text: string }) {
  return (
    <div
      className="faint"
      style={{
        fontSize: 11.5,
        borderLeft: '2px solid var(--card-border)',
        paddingLeft: 8,
        marginTop: 4,
      }}
    >
      {text}
    </div>
  )
}
