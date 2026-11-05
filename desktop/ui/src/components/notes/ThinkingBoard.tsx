import { useCallback, useEffect, useRef, useState } from 'react'
import { X, MousePointer2, Plus, Check, Maximize2, Minimize2 } from 'lucide-react'
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
 * > 「笔记卡片要可以拖拽来改变卡片大小形状，画布也不要有界限」
 *
 * ## ★ 结构
 *
 * ```
 * ┌ 思考模式 ─────────────────────────────────────── ✕ ┐
 * │ [● 灵光一闪 2] [● 质疑 1] …（五个盒子，点开挑笔记）      │
 * ├──────────────────────────────────────────────────┤
 * │   ·   ·   ·   ·   （白布：**无边界**，拖到哪扩到哪）     │
 * │   ┌────────┐                                      │
 * │   │ 竖版卡片│◢  ← 右下角拖拽改大小                   │
 * │   └────────┘                                      │
 * └──────────────────────────────────────────────────┘
 * ```
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
interface Size {
  w: number
  h: number
}

const DEF_W = 200
const DEF_H = 240
const MIN_W = 140
const MIN_H = 120
const PAD = 24
const GAP = 16
/** ★ 画布初始尺寸（* 之后按卡片位置自动扩，* 不设上限）⚠ */
const INIT_W = 1600
const INIT_H = 1200
/** ★ 卡片拖到边缘时，画布一次扩多少 */
const GROW_STEP = 400

const posKey = (nodeId: number) => `thinking:${nodeId}`
const boardKey = (nodeId: number) => `thinking:${nodeId}:board`
const sizeKey = (nodeId: number) => `thinking:${nodeId}:size`
const canvasKey = (nodeId: number) => `thinking:${nodeId}:canvas`

export default function ThinkingBoard({
  open,
  projectRef,
  nodeId,
  notes,
  onClose,
}: ThinkingBoardProps) {
  const navigate = useNavigate()
  const [pos, setPos] = useState<Record<number, Pos>>({})
  const [sizes, setSizes] = useState<Record<number, Size>>({})
  const [canvas, setCanvas] = useState<Size>({ w: INIT_W, h: INIT_H })
  const [onBoard, setOnBoard] = useState<Set<number>>(new Set())
  const [openBox, setOpenBox] = useState<NoteKind | null>(null)
  // ★★ 思考模式**自身全屏**（* 去掉外框留白，* 白布铺满整个屏幕）⚠
  const [fullscreen, setFullscreen] = useState(false)

  const [draggingId, setDraggingId] = useState<number | null>(null)
  const [resizingId, setResizingId] = useState<number | null>(null)
  const dragRef = useRef<{ id: number; dx: number; dy: number } | null>(null)
  const resizeRef = useRef<{
    id: number
    startX: number
    startY: number
    startW: number
    startH: number
  } | null>(null)
  const boardRef = useRef<HTMLDivElement>(null)

  const sizeOf = (id: number): Size => sizes[id] ?? { w: DEF_W, h: DEF_H }

  // ---------------------------------------------------------- 读取已保存状态
  useEffect(() => {
    if (!open) return
    let savedPos: Record<number, Pos> | null = null
    let savedSize: Record<number, Size> | null = null
    let savedBoard: number[] | null = null
    let savedCanvas: Size | null = null
    try {
      const rp = localStorage.getItem(posKey(nodeId))
      if (rp) savedPos = JSON.parse(rp)
      const rs = localStorage.getItem(sizeKey(nodeId))
      if (rs) savedSize = JSON.parse(rs)
      const rb = localStorage.getItem(boardKey(nodeId))
      if (rb) savedBoard = JSON.parse(rb)
      const rc = localStorage.getItem(canvasKey(nodeId))
      if (rc) savedCanvas = JSON.parse(rc)
    } catch {
      /* 坏数据当没有 */
    }

    const board = new Set<number>(
      (savedBoard ?? []).filter((id) => notes.some((n) => n.id === id)),
    )
    setOnBoard(board)
    setSizes(savedSize ?? {})

    const next: Record<number, Pos> = {}
    let y = PAD
    for (const id of board) {
      const s = savedPos?.[id]
      const h = (savedSize?.[id] ?? { w: DEF_W, h: DEF_H }).h
      next[id] = s && Number.isFinite(s.x) && Number.isFinite(s.y) ? s : { x: PAD, y }
      y += h + GAP
    }
    setPos(next)

    // ★ 画布至少能装下所有卡片（* 老数据用默认尺寸兜底）⚠
    const maxX = Math.max(0, ...Object.values(next).map((p) => p.x))
    const maxY = Math.max(0, ...Object.values(next).map((p) => p.y))
    setCanvas({
      w: Math.max(INIT_W, savedCanvas?.w ?? 0, maxX + DEF_W + GROW_STEP),
      h: Math.max(INIT_H, savedCanvas?.h ?? 0, maxY + DEF_H + GROW_STEP),
    })
    setOpenBox(null)
  }, [open, nodeId, notes])

  // ---------------------------------------------------------- 持久化
  const save = (key: string, v: unknown) => {
    try {
      localStorage.setItem(key, JSON.stringify(v))
    } catch {
      /* 隐私模式忽略 */
    }
  }

  /** ★★ 画布**无边界**：卡片拖/缩到超出范围 ⇒ 自动扩（* 只增不减）⚠ */
  const growCanvas = useCallback((x: number, y: number, w: number, h: number) => {
    setCanvas((prev) => {
      const needW = x + w + GROW_STEP
      const needH = y + h + GROW_STEP
      if (needW <= prev.w && needH <= prev.h) return prev
      const next = { w: Math.max(prev.w, needW), h: Math.max(prev.h, needH) }
      save(canvasKey(nodeId), next)
      return next
    })
  }, [nodeId])

  // ---------------------------------------------------------- 加入 / 移除
  const addToBoard = (n: Note) => {
    setOnBoard((prev) => {
      if (prev.has(n.id)) return prev
      const next = new Set(prev)
      next.add(n.id)
      save(boardKey(nodeId), [...next])
      return next
    })
    setPos((prev) => {
      if (prev[n.id]) return prev
      // ★ 竖排一列：* 接在现有最低点下面（* 用各卡片真实高度算）⚠
      let maxBottom = PAD
      for (const [id, p] of Object.entries(prev)) {
        maxBottom = Math.max(maxBottom, p.y + sizeOf(Number(id)).h)
      }
      const y = Object.keys(prev).length ? maxBottom + GAP : PAD
      const next = { ...prev, [n.id]: { x: PAD, y } }
      save(posKey(nodeId), next)
      growCanvas(PAD, y, DEF_W, DEF_H)
      return next
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }

  const removeFromBoard = (id: number) => {
    setOnBoard((prev) => {
      const next = new Set(prev)
      next.delete(id)
      save(boardKey(nodeId), [...next])
      return next
    })
  }

  // ---------------------------------------------------------- 拖动（位置）
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

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      const d = dragRef.current
      const board = boardRef.current
      if (!d || !board) return
      const rect = board.getBoundingClientRect()
      // ★ 位置**不 clamp 上限**（* 只保留 0 下限）⇒* 拖到边缘会自动扩画布 ⚠
      const x = Math.max(0, e.clientX - rect.left - d.dx)
      const y = Math.max(0, e.clientY - rect.top - d.dy)
      setPos((prev) => ({ ...prev, [d.id]: { x, y } }))
      // ★★ **拖动过程中就扩**（* 不能等松手，* 否则拖出边界时卡片被裁、看不到）⚠
      growCanvas(x, y, DEF_W, DEF_H)
    },
    [growCanvas],
  )

  const onPointerUp = useCallback(() => {
    const d = dragRef.current
    dragRef.current = null
    setDraggingId(null)
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
    if (!d) return
    setPos((prev) => {
      save(posKey(nodeId), prev)
      const p = prev[d.id]
      if (p) growCanvas(p.x, p.y, DEF_W, DEF_H)
      return prev
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId, onPointerMove, growCanvas])

  // ---------------------------------------------------------- 拖拽改大小
  const onResizeDown = (e: React.PointerEvent, id: number) => {
    if (e.button != null && e.button !== 0) return
    e.stopPropagation()
    e.preventDefault()
    const s = sizeOf(id)
    resizeRef.current = {
      id,
      startX: e.clientX,
      startY: e.clientY,
      startW: s.w,
      startH: s.h,
    }
    setResizingId(id)
    window.addEventListener('pointermove', onResizeMove)
    window.addEventListener('pointerup', onResizeUp)
  }

  const onResizeMove = useCallback(
    (e: PointerEvent) => {
      const r = resizeRef.current
      if (!r) return
      const w = Math.max(MIN_W, r.startW + (e.clientX - r.startX))
      const h = Math.max(MIN_H, r.startH + (e.clientY - r.startY))
      setSizes((prev) => ({ ...prev, [r.id]: { w, h } }))
      const p = pos[r.id]
      if (p) growCanvas(p.x, p.y, w, h)
    },
    [pos, growCanvas],
  )

  const onResizeUp = useCallback(() => {
    const r = resizeRef.current
    resizeRef.current = null
    setResizingId(null)
    window.removeEventListener('pointermove', onResizeMove)
    window.removeEventListener('pointerup', onResizeUp)
    if (!r) return
    setSizes((prev) => {
      save(sizeKey(nodeId), prev)
      return prev
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId, onResizeMove])

  // ⚠⚠ **不要在这里做「依赖变化即清理」**：
  //   · · `onResizeMove` 依赖 `pos` ⇒ 拖动时 pos 每帧变 ⇒ 本 effect 反复执行清理
  //   · · ⇒ 把 window 上**正在生效**的 pointermove 监听器一并删掉 ⇒ 卡片拖不动 ⚠
  //   · · ★ 监听器由 down 绑定、up 自行解绑；卸载时残留也不会有副作用
  //     （回调里 `if (!dragRef.current || !boardRef.current) return`）✅

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

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 90,
        background: fullscreen ? 'var(--card)' : 'rgba(15,23,42,.45)',
        display: 'flex',
        flexDirection: 'column',
        padding: fullscreen ? 0 : 12,
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
          borderRadius: fullscreen ? 0 : 14,
          overflow: 'hidden',
          boxShadow: fullscreen ? 'none' : '0 24px 60px rgba(15,23,42,.35)',
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
            从下面五个盒子里挑笔记 · 拖动排布 · 右下角拖拽改大小 · 双击打开
          </span>
          {/* ★★ 全屏切换（* 与图谱页右上角同款圆形按钮）⚠ */}
          <button
            type="button"
            onClick={() => setFullscreen((v) => !v)}
            aria-label={fullscreen ? '退出全屏' : '全屏'}
            title={fullscreen ? '退出全屏' : '全屏（白布铺满屏幕）'}
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
            {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭思考模式"
            style={{
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
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {n.title || n.body.replace(/\s+/g, ' ').slice(0, 24)}
                      </span>
                    </button>
                  )
                })}
            </div>
          )}
        </div>

        {/* ---- 白布（点阵，**无边界**） ---- */}
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
          <div style={{ position: 'relative', width: canvas.w, height: canvas.h }}>
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
              const s = sizeOf(n.id)
              const active = draggingId === n.id || resizingId === n.id
              return (
                <div
                  key={n.id}
                  onPointerDown={(e) => onPointerDown(e, n.id)}
                  onDoubleClick={() =>
                    navigate(`/p/${encodeURIComponent(projectRef)}/notes/${n.ref}`)
                  }
                  title="拖动排布 · 右下角改大小 · 双击打开"
                  style={{
                    position: 'absolute',
                    left: p.x,
                    top: p.y,
                    width: s.w,
                    height: s.h,
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
                    overflow: 'hidden',
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
                      WebkitLineClamp: 4,
                      WebkitBoxOrient: 'vertical',
                    }}
                  >
                    {n.body.replace(/\s+/g, ' ').slice(0, 200)}
                  </div>

                  {/* ★★★ 右下角**改大小**手柄（* 拖它改宽高，* 形状随意）⚠ */}
                  <div
                    onPointerDown={(e) => onResizeDown(e, n.id)}
                    title="拖动改变大小"
                    style={{
                      position: 'absolute',
                      right: 0,
                      bottom: 0,
                      width: 16,
                      height: 16,
                      cursor: 'nwse-resize',
                      touchAction: 'none',
                      // ★ 两条斜线（* 一眼看出可拖）⚠
                      backgroundImage:
                        'linear-gradient(135deg, transparent 45%, rgba(16,29,51,.30) 45%, rgba(16,29,51,.30) 55%, transparent 55%), linear-gradient(135deg, transparent 68%, rgba(16,29,51,.22) 68%, rgba(16,29,51,.22) 78%, transparent 78%)',
                    }}
                  />
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
