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
  noteId: number
  anchor: AnchorKind
  /** 段评必填 */
  blockId?: number | null
  /** ★ 回复谁（用户名）—— 非空即「回复模式」 */
  replyTo?: string | null
  onCancelReply?: () => void
  onSent?: () => void
  placeholder?: string
  autoFocus?: boolean
}

export default function CommentComposer({
  noteId,
  anchor,
  blockId,
  replyTo,
  onCancelReply,
  onSent,
  placeholder = '说点什么……（评论只删不改，想好再发）',
  autoFocus,
}: CommentComposerProps) {
  const [text, setText] = useState(() => (replyTo ? `@${replyTo} ` : ''))
  const [err, setErr] = useState('')
  const create = useCreateComment(noteId)

  /** ★ 切换回复对象 ⇒ 重置正文（* 预填 @对方）——⛔ 不把上一条的草稿带过来 ⚠ */
  useEffect(() => {
    setText(replyTo ? `@${replyTo} ` : '')
    setErr('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replyTo])

  /** ★★ `kind` 按正文算（* 口径③）✅ */
  const kindOf = (body: string): CommentKind => {
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
    setErr('')
    try {
      await create.mutateAsync({
        body,
        anchor_kind: anchor,
        kind: kindOf(body),
        ...(anchor === 'paragraph' && blockId != null ? { block_id: blockId } : {}),
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
        >
          发送
        </Button>
      </div>
      {err && (
        <div className="text-xs" style={{ color: 'var(--err)' }}>
          {err}
        </div>
      )}
    </div>
  )
}
