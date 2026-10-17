import { useEffect, useState } from 'react'
import { Send } from 'lucide-react'
import type { AnchorKind } from '../../api/types'
import { useCreateComment } from '../../query/comments'
import { errorMessage } from '../../api/errors'
import Button from '../ui/Button'

/**
 * ★ 评论输入框（`F3` · 契约 §22.3）
 *
 * ## 三条口径
 *
 * | # | 口径 |
 * |---|---|
 * | ① | ★ `anchor_kind` **创建时定死**（`B203④`）—— 本组件由调用方给定，⛔ 不让用户选 |
 * | ② | ★ `quote` **后端自动快照**（`B203④`）—— 前端 ⛔ 不传 |
 * | ③ | ★ 发送后清空 + 通知调用方刷新（`onSent`） |
 *
 * ⚠ 回复模式（`parent` 非空）显示「回复 @谁」+ 取消按钮（`B201②` 楼中楼）✅
 */
interface CommentComposerProps {
  noteId: number
  anchor: AnchorKind
  /** 段评必填 */
  blockId?: number | null
  /** 楼中楼：回复哪条 */
  parent?: number | null
  /** 回复谁（展示用） */
  parentAuthor?: string
  onCancelReply?: () => void
  onSent?: () => void
  placeholder?: string
  autoFocus?: boolean
}

export default function CommentComposer({
  noteId,
  anchor,
  blockId,
  parent,
  parentAuthor,
  onCancelReply,
  onSent,
  placeholder = '说点什么……（评论只删不改，想好再发）',
  autoFocus,
}: CommentComposerProps) {
  const [text, setText] = useState('')
  const [err, setErr] = useState('')
  const create = useCreateComment(noteId)

  /** ★ 切换回复对象时清空（⛔ 不把上一条的草稿带到新回复里） */
  useEffect(() => {
    setText('')
    setErr('')
  }, [parent, anchor, blockId])

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
        ...(anchor === 'paragraph' && blockId != null ? { block_id: blockId } : {}),
        ...(parent != null ? { parent_id: parent } : {}),
      })
      setText('')
      onSent?.()
    } catch (e) {
      // ⚠ 后端文案原样显示（如「不能回复另一种类型的评论」）
      setErr(errorMessage(e))
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {parent != null && (
        <div className="flex items-center gap-2 faint" style={{ fontSize: 11.5 }}>
          回复 @{parentAuthor || '某人'}
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
          rows={2}
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
