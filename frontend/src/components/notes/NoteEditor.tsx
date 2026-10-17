import { useEffect, useState } from 'react'
import { Lock, LockOpen, Trash2 } from 'lucide-react'
import type { Note, NoteKind } from '../../api/types'
import {
  useCreateNote,
  useUpdateNote,
} from '../../query/notes'
import { errorMessage } from '../../api/errors'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import { NOTE_KINDS, KIND_META, kindMeta } from './kindMeta'

/**
 * ★ 笔记编辑器（`F2` · D92）—— Modal 形态
 *
 * ## ⚠★ 四条口径
 *
 * | # | 口径 | 依据 |
 * |---|---|---|
 * | ① | ★ `kind` **五选一固定**（⛔ 不让用户自定义） | `B201` |
 * | ② | ★ 标题可留空（后端会自动取正文前几字） | `B187` |
 * | ③ | ★ 「私有」开关默认**开**（即公开）—— 与后端 `is_public` 默认 true 对齐 | `B187` |
 * | ④ | ★★ 保存后**段落由后端重算**，前端刷新 note + comments 查询 | `B203③` |
 *
 * ⚠★ 保存失败要把后端文案**原样**显示（`errorMessage` 不二次改写）——
 *   ★ 例如 400 `bad_kind` / 空正文 / 节点不存在 ✅
 */
interface NoteEditorProps {
  open: boolean
  /** 传了 = 编辑模式；不传 = 新建模式 */
  note?: Note | null
  projectRef: string
  nodeId: number
  /** ★★ 只读模式（`F2`）：给没权限的人看正文用 —— 控件全禁、只给「关闭」⚠ */
  readOnly?: boolean
  /** ★★ 删除回调（`F2`）：编辑模式 + 可写时才渲染删除按钮 ⚠ */
  onDelete?: () => void
  onClose: () => void
  /** 保存成功（调用方负责刷新 / 关窗） */
  onSaved?: (note: Note) => void
}

export default function NoteEditor({
  open,
  note,
  projectRef,
  nodeId,
  readOnly = false,
  onDelete,
  onClose,
  onSaved,
}: NoteEditorProps) {
  const editing = !!note
  const [kind, setKind] = useState<NoteKind>('flash')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [isPublic, setIsPublic] = useState(true)
  const [err, setErr] = useState('')

  const create = useCreateNote(projectRef)
  const update = useUpdateNote(note?.id ?? null)

  /** ★ 打开时把初值填好（编辑模式带入原值；新建模式给默认） */
  useEffect(() => {
    if (!open) return
    setErr('')
    setKind(note?.kind ?? 'flash')
    setTitle(note?.title ?? '')
    setBody(note?.body ?? '')
    setIsPublic(note?.is_public ?? true)
  }, [open, note])

  const busy = create.isPending || update.isPending

  const save = async () => {
    setErr('')
    if (!body.trim()) {
      setErr('正文不能为空')
      return
    }
    try {
      if (editing) {
        const data = await update.mutateAsync({ kind, title, body, is_public: isPublic })
        onSaved?.(data.note)
      } else {
        const data = await create.mutateAsync({ kind, title, body, node_id: nodeId, is_public: isPublic })
        onSaved?.(data.note)
      }
      onClose()
    } catch (e) {
      // ⚠ 后端文案原样显示（不二次改写）
      setErr(errorMessage(e))
    }
  }

  return (
    <Modal
      open={open}
      title={editing ? '编辑笔记' : '写笔记'}
      width={620}
      onClose={onClose}
      footer={
        readOnly ? (
          <Button onClick={onClose}>关闭</Button>
        ) : (
          <>
            {/* ★★ 删除入口（`F2`）：编辑 + 可写才出现 ⚠
                · 文案在 `NodePanel` 的确认框里（「可从回收站恢复」）✅ */}
            {editing && onDelete && (
              <Button
                variant="danger"
                icon={<Trash2 size={13} />}
                disabled={busy}
                onClick={onDelete}
                style={{ marginRight: 'auto' }}
              >
                删除
              </Button>
            )}
            <Button onClick={onClose} disabled={busy}>
              取消
            </Button>
            <Button variant="primary" loading={busy} onClick={save}>
              {editing ? '保存' : '写下'}
            </Button>
          </>
        )
      }
    >
      {/* ① kind 五选一（固定） */}
      <div className="mb-4">
        <div className="text-xs font-medium tracking-wide text-text-sub mb-1.5">类型</div>
        <div className="flex flex-wrap gap-1.5">
          {NOTE_KINDS.map((k) => {
            const m = KIND_META[k]
            const active = kind === k
            return (
              <button
                key={k}
                type="button"
                disabled={readOnly}
                onClick={() => setKind(k)}
                title={m.hint}
                style={{
                  padding: '5px 10px',
                  borderRadius: 999,
                  fontSize: 12.5,
                  cursor: readOnly ? 'default' : 'pointer',
                  border: `1px solid ${active ? 'var(--brand)' : 'var(--card-border)'}`,
                  background: active ? 'var(--brand-weak, rgba(99,102,241,.08))' : 'transparent',
                  color: active ? 'var(--brand)' : 'var(--text-sub)',
                }}
              >
                {m.label}
              </button>
            )
          })}
        </div>
        <div className="faint mt-1.5" style={{ fontSize: 11.5 }}>
          {kindMeta(kind).hint}
        </div>
      </div>

      {/* ② 标题（可空） */}
      <div className="mb-4">
        <label className="block text-xs font-medium tracking-wide text-text-sub mb-1.5" htmlFor="note-title">
          标题（可空）
        </label>
        <input
          id="note-title"
          className="input"
          maxLength={120}
          disabled={readOnly}
          placeholder="不填就自动取正文前几字"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>

      {/* ③ 正文 */}
      <div className="mb-4">
        <label className="block text-xs font-medium tracking-wide text-text-sub mb-1.5" htmlFor="note-body">
          正文（markdown）
        </label>
        <textarea
          id="note-body"
          className="input"
          rows={9}
          disabled={readOnly}
          style={{ resize: readOnly ? 'none' : 'vertical', lineHeight: 1.8, fontSize: 13.5 }}
          placeholder="想到了什么就写什么 —— 段落之间空一行即可分段"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </div>

      {/* ④ 私有开关 */}
      <button
        type="button"
        disabled={readOnly}
        onClick={() => setIsPublic((v) => !v)}
        className="flex items-center gap-2 w-full text-left"
        style={{
          padding: '8px 10px',
          borderRadius: 8,
          border: '1px solid var(--card-border)',
          background: 'transparent',
          cursor: readOnly ? 'default' : 'pointer',
          opacity: readOnly ? 0.7 : 1,
        }}
      >
        {isPublic ? <LockOpen size={14} /> : <Lock size={14} />}
        <span style={{ fontSize: 12.5 }}>{isPublic ? '公开' : '私有'}</span>
        <span className="faint" style={{ fontSize: 11.5 }}>
          {isPublic ? '项目里其他人能看到这篇' : '只有作者本人能看到这篇'}
        </span>
      </button>

      {err && (
        <div className="text-xs mt-3" style={{ color: 'var(--err)' }}>
          {err}
        </div>
      )}
    </Modal>
  )
}
