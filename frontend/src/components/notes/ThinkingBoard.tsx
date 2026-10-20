import { useCallback, useEffect, useRef, useState } from 'react'
import { X, MousePointer2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { Note } from '../../api/types'
import { kindMeta } from './kindMeta'

/**
 * ★★★ **思考模式**（`F2` 补充）—— 所有者原话：
 *
 * > 「笔记区有个思考模式按钮，可以提供一个白布，上面可以任意排布笔记卡片，
 * >   作为思考笔记之间联系的工具」
 *
 * ## ★ 口径
 * - ★ 一张**白布**（点阵格），卡片在上面**任意拖动**，用来摆出笔记之间的关系 ✅
 * - ★ 位置按 `thinking:<nodeId>` 存 localStorage ⇒* 关掉再开、刷新都还在 ⚠
 * - ★ 卡片保持各盒子的类型色（* 与笔记区一致）✅
 * - ★ 双击卡片 ⇒ 打开这篇笔记 ✅
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

const CARD_W = 190
const CARD_H = 96
const PAD = 24

const storeKey = (nodeId: number) => `thinking:${nodeId}`

export default function ThinkingBoard({
  open,
  projectRef,
  nodeId,
  notes,
  onClose,
}: ThinkingBoardProps) {
  const navigate = useNavigate()
  const [pos, setPos] = useState<Record<number, Pos>>({})
  const [draggingId, setDraggingId] = useState<number | null>(null)
  const dragRef = useRef<{ id: number; dx: number; dy: number } | null>(null)
  const boardRef = useRef<HTMLDivElement>(null)

  // ---------------------------------------------------------- 初始化位置
  useEffect(() => {
    if (!open) return
    let saved: Record<number, Pos> | null = null
    try {
      const raw = localStorage.getItem(storeKey(nodeId))
      if (raw) saved = JSON.parse(raw) as Record<number, Pos>
    } catch {
      saved = null
    }

    const next: Record<number, Pos> = {}
    notes.forEach((n, i) => {
      const s = saved?.[n.id]
      if (s && Number.isFinite(s.x) && Number.isFinite(s.y)) {
        next[n.id] = s
      } else {
        // ★ 没存过 ⇒ 按三列网格摆开（* 不重叠、* 一眼看全）
        const perRow = 3
        next[n.id] = {
          x: PAD + (i % perRow) * (CARD_W + 24),
          y: PAD + Math.floor(i / perRow) * (CARD_H + 24),
        }
      }
    })
    setPos(next)
  }, [open, nodeId, notes])

  // ---------------------------------------------------------- 拖动
  const onPointerDown = (e: React.PointerEvent, id: number) => {
    // 只响应主键 / 触摸
    if (e.button != null && e.button !== 0) return
    const board = boardRef.current
    if (!board) return
    e.preventDefault()
    const rect = board.getBoundingClientRect()
    const p = pos[id] ?? { x: PAD, y: PAD }
    dragRef.current = {
      id,
      dx: e.clientX - rect.left - p.x,
      dy: e.clientY - rect.top - p.y,
    }
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
    // ★ 松手才落盘（* 拖动过程不写 localStorage，避免每帧 IO）⚠
    setPos((prev) => {
      try {
        localStorage.setItem(storeKey(nodeId), JSON.stringify(prev))
      } catch {
        /* 隐私模式写不进去也无所谓 */
      }
      return prev
    })
  }, [nodeId, onPointerMove])

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
            拖动卡片摆出笔记之间的联系 · 双击打开 · 位置自动保存
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

        {/* ---- 白布（点阵） ---- */}
        <div
          ref={boardRef}
          style={{
            flex: 1,
            minHeight: 0,
            overflow: 'auto',
            position: 'relative',
            // ★★ **白布**：* 纯白 + 点阵格（* 以后要信纸花纹就改这里）⚠
            backgroundColor: '#ffffff',
            backgroundImage:
              'radial-gradient(circle, rgba(15,23,42,.13) 1px, transparent 1px)',
            backgroundSize: '22px 22px',
            backgroundPosition: '0 0',
            touchAction: 'none',
          }}
        >
          {/* 撑开一个足够大的可滚动区域（* 卡片才能摆得开）⚠ */}
          <div style={{ position: 'relative', width: 1200, height: 800 }}>
            {notes.map((n) => {
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
                    // ★ 先写 border 简写，* 再写 borderLeft ——* 顺序反了色条会被覆盖 ⚠
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
                    transition: active ? 'none' : 'box-shadow .15s',
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
                  </div>
                  <div
                    style={{
                      fontSize: 12.5,
                      fontWeight: 600,
                      color: '#101d33',
                      lineHeight: 1.35,
                      overflow: 'hidden',
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical',
                    }}
                  >
                    {n.title || n.body.slice(0, 40)}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: 'rgba(16,29,51,.55)',
                      overflow: 'hidden',
                      display: '-webkit-box',
                      WebkitLineClamp: 1,
                      WebkitBoxOrient: 'vertical',
                    }}
                  >
                    {n.body.replace(/\s+/g, ' ').slice(0, 60)}
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
