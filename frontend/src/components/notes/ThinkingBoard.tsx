import { useCallback, useEffect, useRef, useState } from 'react'
import { X, MousePointer2, Plus, Check } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { Note, NoteKind } from '../../api/types'
import { NOTE_KINDS, kindMeta } from './kindMeta'

/**
 * ★★★ **思考模式**（`F2` 补充）—— 所有者原话：
 *
 * > 「笔记区有个思考模式按钮，可以提供一个白布，上面可以任意排布笔记卡片，
 * >   作为思考笔记之间联系的工具」
 * > 「卡片要竖排，不要横排。还有呀，画布上面要有五个盒子，用户可以打开盒子，
 * >   去选要放到白布区的笔记，不然，笔记一多，全部一股脑放到白布区，那就完全
 * >   分不清了」
 *
 * ## ★ 结构
 *
 * ```
 * ┌ 思考模式 ─────────────────────────────────────── ✕ ┐
 * │ [● 灵光一闪 2] [● 质疑 1] [● 困惑 0] …（五个盒子）     │ ← 点开看该盒子的笔记
 * │   ┌ 展开的条目：点「＋」放到白板 / 已放的点「✓」移除 ┐  │
 * ├──────────────────────────────────────────────────┤
 * │   ·   ·   ·   ·   （白布，点阵）                     │
 * │   ┌────────┐                                      │
 * │   │ 卡片 1  │   ← 竖排一列，可拖动                    │
 * │   └────────┘                                      │
 * │   ┌────────┐                                      │
 * │   │ 卡片 2  │                                      │
 * │   └────────┘                                      │
 * └──────────────────────────────────────────────────┘
 * ```
 *
 * ★ 白板**默认是空的** ——* 只放用户从盒子里挑出来的笔记，* ⛔ 不是全部倒上去 ⚠
 */
interface ThinkingBoardProps {
  open: boolean
  projectRef: string
  nodeId: number
  notes: Note[]
  onClose: () => void
}

interface Pos {
  x: number
  y: number
}

// ★★★ 卡片**竖版**：* 高度 > 宽度（* 所有者：「横着方向的长度比竖着方向的
//   长度长」⇒ 原来是 220×96 的横卡，改成 200×240 的竖卡）⚠
const CARD_W = 200
const CARD_H = 240
const PAD = 24
const GAP = 16

const posKey = (nodeId: number) => `thinking:${nodeId}`
const boardKey = (nodeId: number) => `thinking:${nodeId}:board`

export default function ThinkingBoard({
  open,
  projectRef,
  nodeId,
  notes,
  onClose,
}: ThinkingBoardProps) {
  const navigate = useNavigate()
  const [pos, setPos] = useState<Record<number, Pos>>({})
  /** ★★ 白板上放了哪些笔记（* 默认空）⚠ */
  const [onBoard, setOnBoard] = useState<Set<number>>(new Set())
  /** ★ 当前展开的盒子 */
  const [openBox, setOpenBox] = useState<NoteKind | null>(null)
  const [draggingId, setDraggingId] = useState<number | null>(null)
  const dragRef = useRef<{ id: number; dx: number; dy: number } | null>(null)
  const boardRef = useRef<HTMLDivElement>(null)

  // ---------------------------------------------------------- 读取已保存的状态
  useEffect(() => {
    if (!open) return
    let savedPos: Record<number, Pos> | null = null
    let savedBoard: number[] | null = null
    try {
      const raw = localStorage.getItem(posKey(nodeId))
      if (raw) savedPos = JSON.parse(raw) as Record<number, Pos>
      const rawB = localStorage.getItem(boardKey(nodeId))
      if (rawB) savedBoard = JSON.parse(rawB) as number[]
    } catch {
      savedPos = null
      savedBoard = null
    }

    const board = new Set<number>((savedBoard ?? []).filter((id) => notes.some((n) => n.id === id)))
    setOnBoard(board)

    // ★ 只给**在白板上的**卡片恢复位置；其余等用户加入时再摆 ⚠
    const next: Record<number, Pos> = {}
    let y = PAD
    for (const id of board) {
      const s = savedPos?.[id]
      next[id] = s && Number.isFinite(s.x) && Number.isFinite(s.y) ? s : { x: PAD, y }
      y += CARD_H + GAP
    }
    setPos(next)
    setOpenBox(null)
  }, [open, nodeId, notes])

  // ---------------------------------------------------------- 加入 / 移除
  const persistBoard = (set: Set<number>) => {
    try {
      localStorage.setItem(boardKey(nodeId), JSON.stringify([...set]))
    } catch {
      /* 隐私模式忽略 */
    }
  }
  const persistPos = (p: Record<number, Pos>) => {
    try {
      localStorage.setItem(posKey(nodeId), JSON.stringify(p))
    } catch {
      /* 隐私模式忽略 */
    }
  }

  const addToBoard = (n: Note) => {
    setOnBoard((prev) => {
      if (prev.has(n.id)) return prev
      const next = new Set(prev)
      next.add(n.id)
      persistBoard(next)
      return next
    })
    setPos((prev) => {
      if (prev[n.id]) return prev
      // ★★ **竖排一列**：* 新卡片接在现有最下方（* 所有者：「卡片要竖排，不要横排」）⚠
      const ys = Object.values(prev).map((p) => p.y)
      const y = ys.length ? Math.max(...ys) + CARD_H + GAP : PAD
      const next = { ...prev, [n.id]: { x: PAD, y } }
      persistPos(next)
      return next
    })
  }

  const removeFromBoard = (id: number) => {
    setOnBoard((prev) => {
      const next = new Set(prev)
      next.delete(id)
      persistBoard(next)
      return next
    })
  }

  // ---------------------------------------------------------- 拖动
  const onPointerDown = (e: React.PointerEvent, id: number) => {
    if (e.button != null && e.button !== 0) return
    const board = boardRef.current
    if (!board) return
    e.preventDefault()
    const rect = board.getBoundingClientRect()
    const p = pos[id] ?? { x: PAD, y: PAD }
    dragRef.current = { id, dx: e.clientX - rect.left - p.x, dy: e.clientY - rect.top - p.y }
    setDraggingId(id)
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
  }

  const onPointerMove = useCallback((e: PointerEvent) => {
    const d = dragRef.current
    const board = boardRef.current
    if (!d || !board) return
    const rect = board.getBoundingClientRect()
    const maxX = Math.max(0, board.scrollWidth - CARD_W - 8)
    const maxY = Math.max(0, board.scrollHeight - CARD_H - 8)
    const x = Math.min(maxX, Math.max(0, e.clientX - rect.left - d.dx))
    const y = Math.min(maxY, Math.max(0, e.clientY - rect.top - d.dy))
    setPos((prev) => ({ ...prev, [d.id]: { x, y } }))
  }, [])

  const onPointerUp = useCallback(() => {
    const d = dragRef.current
    dragRef.current = null
    setDraggingId(null)
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
    if (!d) return
    setPos((prev) => {
      persistPos(prev)
      return prev
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onPointerMove])

  useEffect(
    () => () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
    },
    [onPointerMove, onPointerUp],
  )

  // ★ Esc 关闭
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const boardNotes = notes.filter((n) => onBoard.has(n.id))
  const boardH = Math.max(680, PAD * 2 + Math.max(1, boardNotes.length) * (CARD_H + GAP) + 40)

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 90,
        background: 'rgba(15,23,42,.45)',
        display: 'flex',
        flexDirection: 'column',
        padding: 12,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--card)',
          borderRadius: 14,
          overflow: 'hidden',
          boxShadow: '0 24px 60px rgba(15,23,42,.35)',
        }}
      >
        {/* ---- 顶栏 ---- */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 14px',
            borderBottom: '1px solid var(--card-border)',
            flexShrink: 0,
          }}
        >
          <MousePointer2 size={15} style={{ color: 'var(--accent)' }} />
          <span style={{ fontSize: 13.5, fontWeight: 650 }}>思考模式</span>
          <span className="faint" style={{ fontSize: 11.5 }}>
            从下面五个盒子里挑笔记放到白布 · 拖动排布 · 双击打开
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭思考模式"
            style={{
              marginLeft: 'auto',
              display: 'grid',
              placeItems: 'center',
              width: 28,
              height: 28,
              borderRadius: 8,
              border: '1px solid var(--card-border)',
              background: 'transparent',
              color: 'var(--text-sub)',
              cursor: 'pointer',
            }}
          >
            <X size={15} />
          </button>
        </div>

        {/* ---- 五个盒子（点开选笔记） ---- */}
        <div
          style={{
            padding: '8px 14px 10px',
            borderBottom: '1px solid var(--card-border)',
            flexShrink: 0,
            background: 'var(--bg)',
          }}
        >
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {NOTE_KINDS.map((k) => {
              const m = kindMeta(k)
              const items = notes.filter((n) => n.kind === k)
              const active = openBox === k
              return (
                <button
                  key={k}
                  type="button"
                  onClick={() => setOpenBox(active ? null : k)}
                  title={`打开「${m.label}」盒子`}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 5,
                    padding: '3px 10px',
                    borderRadius: 999,
                    fontSize: 11.5,
                    lineHeight: '18px',
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    border: `1px solid ${active ? m.color : 'var(--card-border)'}`,
                    background: active ? `${m.color}1f` : 'var(--card)',
                    color: active ? m.color : 'var(--text-sub)',
                  }}
                >
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: 4,
                      background: m.color,
                      opacity: active ? 1 : 0.6,
                    }}
                  />
                  {m.label}
                  <span style={{ opacity: 0.65 }}>{items.length}</span>
                </button>
              )
            })}
          </div>

          {/* ---- 展开的盒子条目 ---- */}
          {openBox && (
            <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {notes.filter((n) => n.kind === openBox).length === 0 && (
                <span className="faint" style={{ fontSize: 11.5 }}>
                  这个盒子里还没有笔记
                </span>
              )}
              {notes
                .filter((n) => n.kind === openBox)
                .map((n) => {
                  const inBoard = onBoard.has(n.id)
                  const c = kindMeta(n.kind).color
                  return (
                    <button
                      key={n.id}
                      type="button"
                      onClick={() => (inBoard ? removeFromBoard(n.id) : addToBoard(n))}
                      title={inBoard ? '从白布移除' : '放到白布'}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        maxWidth: 260,
                        padding: '3px 9px',
                        borderRadius: 8,
                        fontSize: 11.5,
                        lineHeight: '18px',
                        cursor: 'pointer',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        border: `1px solid ${inBoard ? c : 'var(--card-border)'}`,
                        background: inBoard ? `${c}14` : 'var(--card)',
                        color: inBoard ? c : 'var(--text-main)',
                      }}
                    >
                      {inBoard ? <Check size={12} /> : <Plus size={12} />}
                      <span
                        style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}
                      >
                        {n.title || n.body.replace(/\s+/g, ' ').slice(0, 24)}
                      </span>
                    </button>
                  )
                })}
            </div>
          )}
        </div>

        {/* ---- 白布（点阵） ---- */}
        <div
          ref={boardRef}
          style={{
            flex: 1,
            minHeight: 0,
            overflow: 'auto',
            position: 'relative',
            backgroundColor: '#ffffff',
            backgroundImage:
              'radial-gradient(circle, rgba(15,23,42,.13) 1px, transparent 1px)',
            backgroundSize: '22px 22px',
            touchAction: 'none',
          }}
        >
          <div style={{ position: 'relative', width: 1200, height: boardH }}>
            {boardNotes.length === 0 && (
              <div
                style={{
                  position: 'absolute',
                  left: PAD,
                  top: PAD,
                  fontSize: 12.5,
                  color: 'rgba(16,29,51,.45)',
                }}
              >
                白布还是空的 —— 点上面的盒子，挑几篇笔记放上来
              </div>
            )}

            {boardNotes.map((n) => {
              const m = kindMeta(n.kind)
              const p = pos[n.id] ?? { x: PAD, y: PAD }
              const active = draggingId === n.id
              return (
                <div
                  key={n.id}
                  onPointerDown={(e) => onPointerDown(e, n.id)}
                  onDoubleClick={() =>
                    navigate(`/p/${encodeURIComponent(projectRef)}/notes/${n.id}`)
                  }
                  title="拖动排布 · 双击打开"
                  style={{
                    position: 'absolute',
                    left: p.x,
                    top: p.y,
                    width: CARD_W,
                    height: CARD_H,
                    boxSizing: 'border-box',
                    padding: '8px 10px',
                    borderRadius: 10,
                    background: '#ffffff',
                    border: '1px solid rgba(15,23,42,.12)',
                    borderLeft: `4px solid ${m.color}`,
                    boxShadow: active
                      ? '0 10px 24px rgba(15,23,42,.22)'
                      : '0 2px 8px rgba(15,23,42,.10)',
                    cursor: active ? 'grabbing' : 'grab',
                    userSelect: 'none',
                    touchAction: 'none',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 3,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <span
                      style={{
                        fontSize: 10,
                        lineHeight: '15px',
                        padding: '0 6px',
                        borderRadius: 999,
                        color: m.color,
                        border: `1px solid ${m.color}66`,
                      }}
                    >
                      {m.label}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeFromBoard(n.id)
                      }}
                      title="从白布移除"
                      style={{
                        marginLeft: 'auto',
                        display: 'grid',
                        placeItems: 'center',
                        width: 16,
                        height: 16,
                        borderRadius: 4,
                        border: 'none',
                        background: 'transparent',
                        color: 'rgba(16,29,51,.4)',
                        cursor: 'pointer',
                      }}
                    >
                      <X size={11} />
                    </button>
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: '#101d33',
                      lineHeight: 1.4,
                      overflow: 'hidden',
                      display: '-webkit-box',
                      // ★ 竖版卡片：* 标题给 3 行 ⚠
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: 'vertical',
                    }}
                  >
                    {n.title || n.body.slice(0, 40)}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: 'rgba(16,29,51,.55)',
                      lineHeight: 1.6,
                      overflow: 'hidden',
                      display: '-webkit-box',
                      // ★ 竖版卡片：* 摘要给 4 行，* 把竖向空间填起来 ⚠
                      WebkitLineClamp: 4,
                      WebkitBoxOrient: 'vertical',
                    }}
                  >
                    {n.body.replace(/\s+/g, ' ').slice(0, 200)}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
