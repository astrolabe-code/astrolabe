import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { GripHorizontal, Link2, Trash2 } from 'lucide-react'
import type { BoardCard, BoardEdge, NoteItem } from '../../../shared/contract'

interface Props {
  cards: BoardCard[]
  edges: BoardEdge[]
  canvas: { w: number; h: number }
  zoom: number
  notes: NoteItem[]
  onChange: (cards: BoardCard[], edges: BoardEdge[]) => void
  onOpenNote: (ref: string, title: string) => void
}

export default function BoardCanvas({
  cards,
  edges,
  canvas,
  zoom,
  notes,
  onChange,
  onOpenNote,
}: Props) {
  const drag = useRef<{ id: string; sx: number; sy: number; x: number; y: number } | null>(null)
  const [linkFrom, setLinkFrom] = useState<string | null>(null)

  const patch = (id: string, fields: Partial<BoardCard>) => {
    onChange(
      cards.map((c) => (c.id === id ? { ...c, ...fields } : c)),
      edges,
    )
  }

  const onHandleDown = (e: ReactPointerEvent, card: BoardCard) => {
    e.stopPropagation()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    drag.current = { id: card.id, sx: e.clientX, sy: e.clientY, x: card.x, y: card.y }
  }

  const onHandleMove = (e: ReactPointerEvent) => {
    const d = drag.current
    if (!d) return
    patch(d.id, {
      x: Math.max(0, d.x + (e.clientX - d.sx) / zoom),
      y: Math.max(0, d.y + (e.clientY - d.sy) / zoom),
    })
  }

  const onHandleUp = (e: ReactPointerEvent) => {
    drag.current = null
    try {
      ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
    } catch {
      /* 指针已释放 */
    }
  }

  const onStageUp = (e: ReactPointerEvent) => {
    if (!linkFrom) return
    const el = document.elementFromPoint(e.clientX, e.clientY)?.closest('[data-card-id]') as HTMLElement | null
    const to = el?.dataset.cardId
    if (to && to !== linkFrom && !edges.some((x) => x.from === linkFrom && x.to === to)) {
      onChange(cards, [...edges, { from: linkFrom, to }])
    }
    setLinkFrom(null)
  }

  const center = (id: string) => {
    const c = cards.find((x) => x.id === id)
    return c ? { x: c.x + c.w / 2, y: c.y + c.h / 2 } : null
  }

  const removeCard = (id: string) => {
    onChange(
      cards.filter((c) => c.id !== id),
      edges.filter((x) => x.from !== id && x.to !== id),
    )
  }

  return (
    <div className="board-stage" onPointerUp={onStageUp}>
      <div className="board-canvas" style={{ width: canvas.w * zoom, height: canvas.h * zoom }}>
        <div
          className="board-layer"
          style={{ width: canvas.w, height: canvas.h, transform: `scale(${zoom})` }}
        >
          <svg className="board-links" width={canvas.w} height={canvas.h}>
            {edges.map((edge) => {
              const a = center(edge.from)
              const b = center(edge.to)
              if (!a || !b) return null
              const my = (a.y + b.y) / 2
              return (
                <path
                  key={`${edge.from}-${edge.to}`}
                  className="board-link"
                  d={`M${a.x},${a.y} C${a.x},${my} ${b.x},${my} ${b.x},${b.y}`}
                />
              )
            })}
          </svg>

          {cards.map((card) => (
            <div
              key={card.id}
              data-card-id={card.id}
              className="card board-card"
              style={{ left: card.x, top: card.y, width: card.w, height: card.h }}
            >
              <div
                className="board-card-handle"
                onPointerDown={(e) => onHandleDown(e, card)}
                onPointerMove={onHandleMove}
                onPointerUp={onHandleUp}
                onDoubleClick={() => {
                  if (card.noteRef) {
                    const n = notes.find((x) => x.ref === card.noteRef)
                    onOpenNote(card.noteRef, n?.title || '笔记')
                  }
                }}
                title={card.noteRef ? '双击打开关联笔记 · 按住拖动' : '按住拖动'}
              >
                <GripHorizontal size={13} />
                <span className="board-card-handle-text">
                  {card.noteRef
                    ? notes.find((n) => n.ref === card.noteRef)?.title || '关联笔记'
                    : '卡片'}
                </span>
                <button
                  type="button"
                  className={`board-link-handle${linkFrom === card.id ? ' active' : ''}`}
                  title="从这里拖到另一张卡片连线"
                  onPointerDown={(e) => {
                    e.stopPropagation()
                    setLinkFrom(card.id)
                  }}
                >
                  <Link2 size={12} />
                </button>
              </div>
              <textarea
                className="board-card-text"
                value={card.text}
                onChange={(e) => patch(card.id, { text: e.target.value })}
                placeholder="写点什么…"
              />
              <select
                className="board-note-select"
                value={card.noteRef || ''}
                onChange={(e) => patch(card.id, { noteRef: e.target.value || undefined })}
              >
                <option value="">不关联笔记</option>
                {notes.map((n) => (
                  <option key={n.ref} value={n.ref}>
                    {n.title || n.ref}
                  </option>
                ))}
              </select>
              <div className="board-card-footer">
                <button type="button" className="link-btn" onClick={() => removeCard(card.id)}>
                  <Trash2 size={11} /> 删除
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
      {linkFrom && <div className="board-hint">拖到另一张卡片上，松开完成连线</div>}
    </div>
  )
}
