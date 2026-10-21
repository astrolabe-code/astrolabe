import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { MessageSquare, ThumbsUp, Trash2 } from 'lucide-react'
import type { AnchorKind, Comment } from '../../api/types'
import { useCommentLike, useComments, useDeleteComment } from '../../query/comments'
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
  /** ★ 是不是「楼中楼里的回复」（* 子项不再显示 N 条回复）⚠ */
  isChild?: boolean
}

export default function CommentItem({
  comment,
  noteId,
  anchor,
  perm,
  isChild,
}: CommentItemProps) {
  const [replying, setReplying] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [delErr, setDelErr] = useState('')
  // ★★★ **楼中楼（最多两层）**：* 拉这条评论的子回复 ⚠
  //   · · 默认不拉（`enabled:false`），点「N 条回复」才 refetch ✅
  const [repliesOpen, setRepliesOpen] = useState(false)
  const replies = useComments(noteId, {
    anchor_kind: anchor,
    ...(anchor === 'paragraph' && comment.fingerprint
      ? { fingerprint: comment.fingerprint }
      : {}),
    parent: comment.id,
    limit: 100,
    enabled: false,
  })

  const qc = useQueryClient()
  const del = useDeleteComment(noteId)
  const canDelete = commentDeletable(comment, perm)
  // ★★ 评论赞：* 每条评论自己的计数（* 不需要 block_id）⚠
  const like = useCommentLike()
  // ★★ 点一下赞、再点一下取消（* 红 = 我赞过）⚠
  const [liked, setLiked] = useState(!!comment.liked)
  const [likes, setLikes] = useState(comment.like_count ?? 0)

  // ★★★ **连续点击防抖 1 秒**（* 所有者：「连续点击，之后，应该等一秒，用户不再
  //   点点赞按钮后，再把用户的行为，即是否点赞传回后端记录呀，不要点一次就传一次，
  //   疯狂改记录呀」）⚠
  //   · · ★ 只记**最终状态**（`pending`），到点才发一次 ⚠
  const pending = useRef<boolean | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const flush = useRef(async () => {
    const want = pending.current
    if (want == null) return
    pending.current = null
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
    try {
      const r = await like.mutateAsync({ id: comment.id, liked: want })
      setLiked(r.liked)
      setLikes(r.like_count)
    } catch {
      // ★ 失败回滚到相反状态（* 后端没记住，* 本地也要退回来）⚠
      setLiked(!want)
      setLikes((c) => Math.max(0, c + (want ? -1 : 1)))
    }
  }).current

  const onLike = () => {
    const next = !liked
    // ★ 乐观：* 图标与计数同时翻，到点由回包校正 ⚠
    setLiked(next)
    setLikes((c) => Math.max(0, c + (next ? 1 : -1)))
    pending.current = next
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => void flush(), 1000)
  }

  // ★ 卸载时把待发的那一次补发（* 别让用户点的赞白点）⚠
  useEffect(
    () => () => {
      if (pending.current != null) void flush()
    },
    [flush],
  )

  const isReply = comment.kind === 'reply' || comment.kind === 'both'
  // ⚠★ 2026-10-20：**@ 高亮先注释掉**（* 同上：@ 提及暂不启用）——
  //   · · 正文一律按纯文本渲染（* 恢复时改回下面的表达式即可）⚠
  // const highlight = comment.kind === 'mention' || comment.kind === 'both'
  const highlight = false
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
          style={{
            // ★ 红 = **我赞过**（* 不是"有人赞过"）⚠
            color: liked ? 'var(--err)' : 'var(--text-sub)',
            cursor: 'pointer',
          }}
          title={liked ? '取消赞' : '给这条评论点赞'}
          onClick={onLike}
        >
          <ThumbsUp size={11} fill={liked ? 'currentColor' : 'none'} />
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

      {/* ★★★ 子回复列表（* 缩进一层，⛔ 不再嵌套第三层）⚠ */}
      {!isChild && comment.reply_count > 0 && (
        <button
          type="button"
          onClick={() => {
            const next = !repliesOpen
            setRepliesOpen(next)
            if (next && !replies.data) void replies.refetch()
          }}
          style={{
            marginTop: 6,
            fontSize: 11.5,
            color: 'var(--accent)',
            cursor: 'pointer',
            background: 'none',
            border: 'none',
            padding: 0,
          }}
        >
          {repliesOpen ? '收起回复' : `${comment.reply_count} 条回复`}
        </button>
      )}

      {repliesOpen && (
        <div
          style={{
            marginTop: 8,
            marginLeft: 10,
            paddingLeft: 10,
            borderLeft: '2px solid var(--card-border)',
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          {(replies.data?.items || []).map((r) => (
            <CommentItem
              key={r.id}
              comment={r}
              noteId={noteId}
              anchor={anchor}
              perm={perm}
              // ★ 子项不再显示「N 条回复」（* 只有两层）⚠
              isChild
            />
          ))}
          {replies.isLoading && (
            <span className="faint" style={{ fontSize: 11.5 }}>
              加载中…
            </span>
          )}
        </div>
      )}

      {replying && (
        <div className="mt-2">
          <CommentComposer
            noteId={noteId}
            anchor={anchor}
            fingerprint={comment.fingerprint}
            // ⚠★ 2026-10-20：**@ 提及先注释掉**（* 所有者：「回复里不要 @ 的功能，
            //   先注释掉」）⇒ 回复不再自动预填 `@某人 `，恢复时取消注释即可 ⚠
            // replyTo={comment.created_by}
            // ★★ 用 id 告诉后端「回复的是哪条」⇒ 引用显示它的正文（* 不是整段原文）⚠
            replyToCommentId={comment.id}
            autoFocus
            placeholder={`回复 @${comment.created_by || '某人'}……`}
            onCancelReply={() => setReplying(false)}
            onSent={() => {
              setReplying(false)
              // ★★ 让父评论的「N 条回复」立刻更新（* 否则数字不动）⚠
              void qc.invalidateQueries({ queryKey: ['comments', noteId] })
              if (repliesOpen) void replies.refetch()
            }}
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
