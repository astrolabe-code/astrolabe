import { useEffect, useState } from 'react'
import { Send } from 'lucide-react'
import type { AnchorKind, CommentKind } from '../../api/types'
import { useCreateComment } from '../../query/comments'
import { errorMessage } from '../../api/errors'
import Button from '../ui/Button'
import { countMentions } from './mention'

/**
 * ★ 评论输入框（`F3` 建 · `B214` 改「类型」口径 · 契约 §22.3）
 *
 * ## ★★ 三种口径
 *
 * | # | 口径 |
 * |---|---|
 * | ① | ★ `anchor_kind` **创建时定死**（`B203④`）—— 本组件由调用方给定，⛔ 不让用户选 |
 * | ② | ★ `quote` **后端自动快照**（`B203④`）—— 前端 ⛔ 不传 |
 * | ③ | ★★ **`kind` 由前端按正文算**（`B214`）：* `replyTo` 有 ⇒ `reply`；* 正文另有 @ ⇒ `both`；* 无 `replyTo` 但有 @ ⇒ `mention`；* 都没有 ⇒ `comment` ✅ |
 *
 * ⚠★ 回复模式（`replyTo` 非空）：* 正文**预填 `@某人 `** ——
 *   ★★ 「回复谁」就记在这段文本里（* ⛔ 没有 reply_to 列，* 见 `B214`）⚠
 */
interface CommentComposerProps {
  /** ★ 笔记的对外标识（* ref，⛔ 不是自增 pk）⚠ */
  noteId: string
  anchor: AnchorKind
  /** 段评必填 */
  /** ★ 段评锚点 = 段落指纹（`B235`）⚠ */
  fingerprint?: string | null
  /** ★ 回复谁（用户名）—— 非空即「回复模式」 */
  replyTo?: string | null
  /**
   * ★★ 被回复的**评论 id**（* 2026-10-20）——
   *   · · 后端用它把 `quote` 记成「那条评论的正文」，
   *     而不是整段原文（* 所有者反馈的那个 bug）⚠
   */
  replyToCommentId?: number | null
  onCancelReply?: () => void
  onSent?: () => void
  placeholder?: string
  autoFocus?: boolean
}

export default function CommentComposer({
  noteId,
  anchor,
  fingerprint,
  replyTo,
  replyToCommentId,
  onCancelReply,
  onSent,
  placeholder = '说点什么……（评论只删不改，想好再发）',
  autoFocus,
}: CommentComposerProps) {
  const [text, setText] = useState(() => (replyTo ? `@${replyTo} ` : ''))
  const [err, setErr] = useState('')

  // ★★★ **评论最多 300 字**（* 所有者：「超出限制，前端不允许发送，而且要有提示」）⚠
  //   · · ★ 前端：显示计数，超了变红、**禁用发送**；
  //   · · ★★ 后端：`_create` 也会 400 `comment_too_long`（* 双重保险）✅
  const BODY_MAX = 300
  const length = text.length
  const tooLong = length > BODY_MAX
  const create = useCreateComment(noteId)

  /** ★ 切换回复对象 ⇒ 重置正文（* 预填 @对方）——⛔ 不把上一条的草稿带过来 ⚠ */
  useEffect(() => {
    setText(replyTo ? `@${replyTo} ` : '')
    setErr('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replyTo])

  /** ★★ `kind` 按正文算（* 口径③）✅ */
  const kindOf = (body: string): CommentKind => {
    // ★ 回复某条评论 ⇒ 直接 reply（* 不再依赖正文里的 @）⚠
    if (replyToCommentId != null) return 'reply'
    const n = countMentions(body)
    if (replyTo) return n > 1 ? 'both' : 'reply'
    return n > 0 ? 'mention' : 'comment'
  }

  const send = async () => {
    const body = text.trim()
    if (!body) {
      setErr('评论不能为空')
      return
    }
    // ★ 超长直接拦下（* 后端也会拒，这里先给即时反馈）⚠
    if (body.length > BODY_MAX) {
      setErr(`评论最多 ${BODY_MAX} 字（当前 ${body.length} 字）`)
      return
    }
    setErr('')
    try {
      await create.mutateAsync({
        body,
        anchor_kind: anchor,
        kind: kindOf(body),
        ...(anchor === 'paragraph' && fingerprint ? { fingerprint } : {}),
        // ★★ 告诉后端「回复的是哪条评论」⇒ quote 取它的正文 ⚠
        ...(replyToCommentId != null ? { reply_to_comment_id: replyToCommentId } : {}),
      })
      setText('')
      onSent?.()
    } catch (e) {
      // ⚠ 后端文案原样显示（如「回复 / @ 的评论正文里必须带上 @某个用户」）
      setErr(errorMessage(e))
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {replyTo && (
        <div className="flex items-center gap-2 faint" style={{ fontSize: 11.5 }}>
          回复 @{replyTo}
          {onCancelReply && (
            <button type="button" onClick={onCancelReply} style={{ cursor: 'pointer' }}>
              取消
            </button>
          )}
        </div>
      )}
      <div className="flex gap-2 items-start">
        <textarea
          className="input"
          rows={replyTo ? 2 : 2}
          autoFocus={autoFocus}
          style={{ resize: 'vertical', fontSize: 13, lineHeight: 1.7 }}
          placeholder={placeholder}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // ★ Ctrl/Cmd + Enter 发送（⛔ 不拦纯 Enter —— 换行是正常需求）
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') void send()
          }}
        />
        <Button
          variant="primary"
          loading={create.isPending}
          icon={<Send size={13} />}
          onClick={send}
          // ★ 超长 / 空内容 ⇒ **不允许发送**（* 所有者要求）⚠
          disabled={tooLong || !text.trim()}
        >
          发送
        </Button>
      </div>

      {/* ★★ 字数计数 + 超限提示（* 超了变红、按钮禁用）⚠ */}
      <div
        className="flex items-center justify-between"
        style={{ fontSize: 11 }}
      >
        <span style={{ color: tooLong ? 'var(--err)' : 'var(--text-sub)' }}>
          {tooLong ? `超出 ${length - BODY_MAX} 字，最多 ${BODY_MAX} 字` : ''}
        </span>
        <span style={{ color: tooLong ? 'var(--err)' : 'var(--text-faint)' }}>
          {length}/{BODY_MAX}
        </span>
      </div>

      {err && (
        <div className="text-xs" style={{ color: 'var(--err)' }}>
          {err}
        </div>
      )}
    </div>
  )
}
