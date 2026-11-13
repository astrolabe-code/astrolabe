import { useEffect, useState } from 'react'
import { Minus, Plus, Save } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { invoke } from '../api'
import BoardCanvas from './BoardCanvas'
import type { BoardCard, BoardEdge, BoardLayoutData, NoteItem } from '../../../shared/contract'

interface Props {
  projectRef: string
  boardId: string
}

const EMPTY: BoardLayoutData = { cards: [], edges: [], canvas: { w: 1600, h: 1000 } }

function normalize(raw: Partial<BoardLayoutData> | null | undefined): BoardLayoutData {
  const cards: BoardCard[] = (Array.isArray(raw?.cards) ? raw.cards : []).map((c, i) => ({
    id: String(c.id ?? `c${i}`),
    x: Number(c.x) || 0,
    y: Number(c.y) || 0,
    w: Number(c.w) || 200,
    h: Number(c.h) || 150,
    text: String(c.text ?? ''),
    noteRef: c.noteRef,
  }))
  const edges: BoardEdge[] = (Array.isArray(raw?.edges) ? raw.edges : []).map((e) => ({
    from: String(e.from),
    to: String(e.to),
  }))
  return { cards, edges, canvas: raw?.canvas ?? EMPTY.canvas }
}

export default function BoardView({ projectRef, boardId }: Props) {
  const nav = useNavigate()
  const [name, setName] = useState('')
  const [layout, setLayout] = useState<BoardLayoutData>(EMPTY)
  const [notes, setNotes] = useState<NoteItem[]>([])
  const [zoom, setZoom] = useState(1)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')

  useEffect(() => {
    invoke('boards.get', projectRef, boardId)
      .then((doc) => {
        setName(doc.name)
        setLayout(normalize(doc.layout))
        setDirty(false)
        setStatus('')
      })
      .catch((e) => setStatus(String(e)))
  }, [projectRef, boardId])

  useEffect(() => {
    invoke('notes.list', projectRef)
      .then(setNotes)
      .catch(() => {})
  }, [projectRef])

  const update = (cards: BoardCard[], edges: BoardEdge[]) => {
    setLayout((l) => ({ ...l, cards, edges }))
    setDirty(true)
    setStatus('')
  }

  const addCard = () => {
    const i = layout.cards.length
    const card: BoardCard = {
      id: `c${Date.now()}`,
      x: 60 + i * 28,
      y: 60 + i * 28,
      w: 210,
      h: 170,
      text: '',
    }
    update([...layout.cards, card], layout.edges)
  }

  const save = async () => {
    try {
      await invoke('boards.save', projectRef, boardId, layout, name)
      setDirty(false)
      setStatus('已保存')
    } catch (e) {
      setStatus(String(e))
    }
  }

  const openNote = (ref: string, title: string) => {
    nav(`/p/${projectRef}/notes/${ref}`, { state: { title: title || '笔记' } })
  }

  return (
    <div className="pane board-pane">
      <div className="pane-bar">
        <input
          className="note-title"
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            setDirty(true)
          }}
          placeholder="白板名字"
        />
        <button type="button" className="btn ghost" onClick={addCard}>
          加卡片
        </button>
        <div className="board-zoom">
          <button type="button" title="缩小" onClick={() => setZoom((z) => Math.max(0.4, z - 0.1))}>
            <Minus size={12} />
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" title="放大" onClick={() => setZoom((z) => Math.min(2, z + 0.1))}>
            <Plus size={12} />
          </button>
        </div>
        <span className="faint">{status}</span>
        <button type="button" className="btn primary" disabled={!dirty} onClick={() => void save()}>
          <Save size={13} /> 保存布局
        </button>
      </div>
      <BoardCanvas
        cards={layout.cards}
        edges={layout.edges}
        canvas={layout.canvas}
        zoom={zoom}
        notes={notes}
        onChange={update}
        onOpenNote={openNote}
      />
    </div>
  )
}
