import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { invoke } from '../api'
import ConfirmDialog from './ConfirmDialog'
import type { NoteItem } from '../../../shared/contract'

interface Props {
  projectRef: string
  onOpen: (ref: string, title: string) => void
}

export default function NoteListView({ projectRef, onOpen }: Props) {
  const [items, setItems] = useState<NoteItem[]>([])
  const [pending, setPending] = useState<NoteItem | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      setItems(await invoke('notes.list', projectRef))
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    void load()
  }, [projectRef])

  const create = async () => {
    try {
      const n = await invoke('notes.save', projectRef, '', '', '未命名笔记', 0)
      await load()
      onOpen(n.ref, n.title || '未命名笔记')
    } catch (e) {
      setError(String(e))
    }
  }

  const remove = async () => {
    if (!pending) return
    await invoke('notes.remove', projectRef, pending.ref)
    setPending(null)
    await load()
  }

  return (
    <div className="pane list-pane">
      <div className="pane-bar">
        <span>笔记</span>
        <button type="button" className="btn ghost" onClick={() => void create()}>
          <Plus size={13} /> 新建
        </button>
      </div>
      {error && <div className="pane-error">{error}</div>}
      <div className="card-list">
        {items.map((it) => (
          <div key={it.ref} className="card list-card">
            <button type="button" className="list-card-main" onClick={() => onOpen(it.ref, it.title)}>
              <div className="list-card-title">{it.title || '（无标题）'}</div>
              <div className="faint">{new Date(it.mtime * 1000).toLocaleString()}</div>
            </button>
            <div className="list-card-footer">
              <button
                type="button"
                className="link-btn"
                onClick={() => setPending(it)}
              >
                <Trash2 size={11} /> 删除
              </button>
            </div>
          </div>
        ))}
        {items.length === 0 && <div className="faint">这个节点还没有笔记</div>}
      </div>
      <ConfirmDialog
        open={!!pending}
        title="删除笔记"
        message={`删除「${pending?.title || '（无标题）'}」？删除后不可恢复。`}
        onConfirm={() => void remove()}
        onCancel={() => setPending(null)}
      />
    </div>
  )
}
