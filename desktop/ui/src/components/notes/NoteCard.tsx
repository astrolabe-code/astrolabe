import { Link, useNavigate } from 'react-router-dom'
import { EyeOff, Lock, LockOpen, MessageSquare, Pencil, ThumbsUp, Trash2 } from 'lucide-react'
import type { Note } from '../../api/types'
import { useUpdateNote } from '../../query/notes'
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
  /** ★★ 删除（* 与编辑弹窗里的「删除」联动：* 同一个确认框、同一条软删路径）⚠ */
  onDelete?: (note: Note) => void
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

export default function NoteCard({
  note,
  projectRef,
  canWrite,
  onEdit,
  onDelete,
}: NoteCardProps) {
  const navigate = useNavigate()
  const meta = kindMeta(note.kind)
  const Icon = meta.icon
  // ★★ 「公开 / 私有」开关：* 与编辑弹窗里的同一个字段（`is_public`）联动 ⚠
  const update = useUpdateNote(note.ref)
  return (
    <div
      className="card w-full text-left"
      style={{ padding: '10px 12px', cursor: 'pointer', position: 'relative' }}
      onClick={() => navigate(`/p/${encodeURIComponent(projectRef)}/notes/${note.ref}`)}
    >
      <div className="flex items-center gap-2 flex-wrap">
        {/* ★★ 类型标签用**该 kind 的专属色**（* 文字 / 边框 / 淡底同色系）⚠ */}
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 3,
            fontSize: 10.5,
            lineHeight: '16px',
            padding: '1px 8px',
            borderRadius: 999,
            color: meta.color,
            border: `1px solid ${meta.color}66`,
            background: `${meta.color}1a`,
          }}
        >
          <Icon size={11} />
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
          {/* ★ 显示昵称（* 为空回落用户名），* 点名字进 TA 的空间（⛔ 不触发卡片跳转）⚠ */}
          {note.created_by ? (
            <Link
              to={`/u/${encodeURIComponent(note.created_by)}`}
              onClick={(e) => e.stopPropagation()}
              style={{ color: 'inherit' }}
            >
              {note.created_by_display || note.created_by}
            </Link>
          ) : (
            note.created_by_display || ''
          )}{' '}
          · {note.created_at?.slice(0, 10)}
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
          <div
            className="flex items-center gap-3"
            style={{ marginLeft: 'auto' }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* ★★ 公开 / 私有开关（* 与弹窗里的同一字段联动）⚠
                · · ⛔ 不跳阅读页 —— 这个容器统一 stopPropagation ✅ */}
            <button
              type="button"
              className="flex items-center gap-1"
              disabled={update.isPending}
              title={note.is_public ? '当前公开，点击改为私有' : '当前私有，点击改为公开'}
              style={{ color: 'var(--text-sub)', cursor: 'pointer' }}
              onClick={() => {
                // ★ 整份 PATCH（* 后端按字段更新；带上其余字段避免误清空）⚠
                update.mutate({
                  kind: note.kind,
                  title: note.title,
                  body: note.body,
                  is_public: !note.is_public,
                })
              }}
            >
              {note.is_public ? <LockOpen size={11} /> : <Lock size={11} />}
              {note.is_public ? '公开' : '私有'}
            </button>

            <button
              type="button"
              className="flex items-center gap-1"
              style={{ color: 'var(--text-sub)', cursor: 'pointer' }}
              onClick={() => {
                // ★★ 与弹窗里的删除**同一条路径**（* 父组件的确认框 + 软删）⚠
                onDelete?.(note)
              }}
            >
              <Trash2 size={11} />
              删除
            </button>

            <button
              type="button"
              className="flex items-center gap-1"
              style={{ color: 'var(--text-sub)', cursor: 'pointer' }}
              onClick={() => onEdit(note)}
            >
              <Pencil size={11} />
              编辑
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
