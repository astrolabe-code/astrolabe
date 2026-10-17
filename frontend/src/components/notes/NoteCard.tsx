import { useNavigate } from 'react-router-dom'
import { EyeOff, MessageSquare, Pencil, ThumbsUp } from 'lucide-react'
import type { Note } from '../../api/types'
import { kindMeta } from './kindMeta'

/**
 * ★ 单篇笔记卡片（`F2` 建 · `F3` 改点击行为）
 *
 * ## ⚠★ `F3` 起的点击口径（* 与 F2 不同）
 *
 * | 动作 | 去哪 |
 * |---|---|
 * | ★ 点卡片 | ★★ **阅读页**（`/p/:ref/notes/:id`）——* 读评论、点赞、段评的地方 ✅ |
 * | ★ 点「编辑」 | 编辑器 Modal（* 顺手改一笔就走）✅ |
 *
 * ⚠ 为什么改：* F2 时「点开即编辑」是因为没有阅读页；* `F3` 阅读页出来后，
 *   * 「读」与「改」是两件事，* ⛔ 不该混同一个入口 ✅
 *
 * ## 三条显示口径
 *
 * | # | 口径 |
 * |---|---|
 * | ① | ★ 正文只显示**摘要**（前两行）—— 卡片不是阅读区 |
 * | ② | ★ `is_public=false` ⇒ 显示「私有」徽标 |
 * | ③ | ★ `state=hidden` ⇒ 显示「已被隐藏」徽标（只有 owner 看得到） |
 */
interface NoteCardProps {
  note: Note
  projectRef: string
  /** 当前用户能不能改它（作者 ∨ owner ∨ 协作者）—— 决定显不显示「编辑」 */
  canWrite: boolean
  onEdit: (note: Note) => void
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

export default function NoteCard({ note, projectRef, canWrite, onEdit }: NoteCardProps) {
  const navigate = useNavigate()
  const meta = kindMeta(note.kind)
  const Icon = meta.icon
  return (
    <div
      className="card w-full text-left"
      style={{ padding: '10px 12px', cursor: 'pointer', position: 'relative' }}
      onClick={() => navigate(`/p/${encodeURIComponent(projectRef)}/notes/${note.id}`)}
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
        {canWrite && (
          <button
            type="button"
            className="flex items-center gap-1"
            style={{ marginLeft: 'auto', color: 'var(--text-sub)', cursor: 'pointer' }}
            onClick={(e) => {
              // ⚠ 必须阻止冒泡 —— 否则会先跳阅读页 ⚠
              e.stopPropagation()
              onEdit(note)
            }}
          >
            <Pencil size={11} />
            编辑
          </button>
        )}
      </div>
    </div>
  )
}
