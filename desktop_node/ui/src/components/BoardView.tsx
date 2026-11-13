import { useEffect, useState } from 'react'
import { invoke } from '../api'

interface Card {
  id: number
  x: number
  y: number
  text: string
}

interface Props {
  projectRef: string
  boardId: string
}

export default function BoardView({ projectRef, boardId }: Props) {
  const [name, setName] = useState('')
  const [cards, setCards] = useState<Card[]>([])
  const [status, setStatus] = useState('')

  useEffect(() => {
    invoke('boards.get', projectRef, boardId)
      .then((doc) => {
        setName(doc.name)
        const saved = doc.layout.cards
        setCards(Array.isArray(saved) ? (saved as Card[]) : [])
      })
      .catch((e) => setStatus(String(e)))
  }, [projectRef, boardId])

  const save = async () => {
    await invoke('boards.save', projectRef, boardId, { cards }, name)
    setStatus('已保存')
  }

  return (
    <div className="pane board-pane">
      <div className="pane-bar">
        <input className="note-title" value={name} onChange={(e) => setName(e.target.value)} />
        <span className="faint">{status}</span>
        <button type="button" className="btn ghost" onClick={() => setCards((c) => [...c, { id: Date.now(), x: 20 + c.length * 24, y: 20 + c.length * 24, text: '新卡片' }])}>
          加卡片
        </button>
        <button type="button" className="btn primary" onClick={() => void save()}>
          保存布局
        </button>
      </div>
      <div className="board-stage">
        {cards.map((c) => (
          <div key={c.id} className="card board-stage-card" style={{ left: c.x, top: c.y }}>
            {c.text}
          </div>
        ))}
      </div>
    </div>
  )
}
