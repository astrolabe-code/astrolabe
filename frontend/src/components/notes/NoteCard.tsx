import { EyeOff, MessageSquare, ThumbsUp } from 'lucide-react'
import type { Note } from '../../api/types'
import { kindMeta } from './kindMeta'

/**
 * ★ 单篇笔记卡片（`F2` · D92）
 *
 * ⚠★ 三条显示口径：
 * | # | 口径 |
 * |---|---|
 * | ① | ★ 正文只显示**摘要**（前两行）—— 卡片不是阅读区，点开才是 |
 * | ② | ★ `is_public=false` ⇒ 显示「私有」徽标（作者自己可见的提醒） |
 * | ③ | ★ `state=hidden` ⇒ 显示「已被隐藏」徽标（只有 owner 看得到，见 D92⑤） |
 */
interface NoteCardProps {
  note: Note
  /** 当前用户能不能改它（作者 ∨ owner ∨ 协作者）—— 决定点开是编辑还是只读 */
  canWrite: boolean
  onOpen: (note: Note) => void
}

/** ★ 摘要：取前两行非空内容，超过 160 字截断 */
function preview(body: string): string {
  const lines = body
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  const text = lines.slice(0, 2).join(' ')
  return text.length > 160 ? `${text.slice(0, 160)}…` : text
}

export default function NoteCard({ note, canWrite, onOpen }: NoteCardProps) {
  const meta = kindMeta(note.kind)
  const Icon = meta.icon
  return (
    <button
      type="button"
      className="card w-full text-left"
      style={{ padding: '10px 12px', cursor: 'pointer' }}
      onClick={() => onOpen(note)}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="tag" style={{ fontSize: 10.5 }}>
          <Icon size={11} style={{ marginRight: 3, verticalAlign: -1 }} />
          {meta.label}
        </span>
        {!note.is_public && (
          <span className="tag" style={{ fontSize: 10.5 }} title="只有作者可见">
            <EyeOff size={10} style={{ marginRight: 3, verticalAlign: -1 }} />
            私有
          </span>
        )}
        {note.state === 'hidden' && (
          <span className="tag" style={{ fontSize: 10.5, color: 'var(--err)' }} title={note.moderation_reason}>
            已被隐藏
          </span>
        )}
        <span className="faint" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {note.created_by} · {note.created_at?.slice(0, 10)}
        </span>
      </div>
      <div style={{ fontSize: 13.5, marginTop: 6, fontWeight: 500 }}>{note.title || '（无标题）'}</div>
      {note.body && (
        <div className="faint" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.6 }}>
          {preview(note.body)}
        </div>
      )}
      <div className="flex items-center gap-3 mt-2 faint" style={{ fontSize: 11 }}>
        <span className="flex items-center gap-1">
          <ThumbsUp size={11} /> {note.like_count}
        </span>
        <span className="flex items-center gap-1">
          <MessageSquare size={11} /> {note.comment_count}
        </span>
        <span style={{ marginLeft: 'auto' }}>{canWrite ? '点击编辑' : '点击查看'}</span>
      </div>
    </button>
  )
}
