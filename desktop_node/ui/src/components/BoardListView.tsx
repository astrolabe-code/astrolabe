import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { invoke } from '../api'
import ConfirmDialog from './ConfirmDialog'
import type { BoardItem } from '../../../shared/contract'

interface Props {
  projectRef: string
  nodeVid: number
  onOpen: (id: string, name: string) => void
}

export default function BoardListView({ projectRef, nodeVid, onOpen }: Props) {
  const [items, setItems] = useState<BoardItem[]>([])
  const [pending, setPending] = useState<BoardItem | null>(null)

  const load = async () => {
    try {
      setItems(await invoke('boards.list', projectRef, nodeVid))
    } catch {
      setItems([])
    }
  }

  useEffect(() => {
    void load()
  }, [projectRef, nodeVid])

  const create = async () => {
    const b = await invoke('boards.create', projectRef, nodeVid, `白板 ${items.length + 1}`)
    await load()
    onOpen(b.id, b.name)
  }

  const remove = async () => {
    if (!pending) return
    await invoke('boards.remove', projectRef, pending.id)
    setPending(null)
    await load()
  }

  return (
    <div className="pane list-pane">
      <div className="pane-bar">
        <span>这个节点上的白板</span>
        <button type="button" className="btn ghost" onClick={() => void create()}>
          <Plus size={13} /> 新建
        </button>
      </div>
      <div className="card-list">
        {items.map((it) => (
          <div key={it.id} className="card board-card">
            <button type="button" className="list-card-main" onClick={() => onOpen(it.id, it.name)}>
              <div className="list-card-title">{it.name || '（未命名）'}</div>
              <div className="faint">{new Date(it.mtime * 1000).toLocaleString()}</div>
            </button>
            <div className="board-card-footer">
              <button type="button" className="link-btn" onClick={() => setPending(it)}>
                <Trash2 size={11} /> 删除
              </button>
            </div>
          </div>
        ))}
        {items.length === 0 && <div className="faint">这个节点还没有白板</div>}
      </div>
      <ConfirmDialog
        open={!!pending}
        title="删除白板"
        message={`删除「${pending?.name || '（未命名）'}」？删除后不可恢复。`}
        onConfirm={() => void remove()}
        onCancel={() => setPending(null)}
      />
    </div>
  )
}
