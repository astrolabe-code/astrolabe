import { useCallback, useEffect, useRef, useState } from 'react'
import { X, MousePointer2, Plus, Check, Maximize2, Minimize2, GitBranch, Link2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { Note, NoteKind } from '../../api/types'
import { cardId, type CardInfo, type CardLink } from '../../api/code'
import { personalApi } from '../../api/personal'
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

/** ★ 外来卡用全局卡片 id 的稳定哈希做本地 id（⛔ 不与本节点数字主键冲突） */
function externalLocalId(card: string): number {
  let h = 2166136261
  for (let i = 0; i < card.length; i += 1) {
    h ^= card.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return -(Math.abs(h >>> 0) % 1000000) - 1
}

interface ExternalCard {
  id: number
  card: string
  info: CardInfo
}

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
  /** ★★ D139：卡片盒的链（跨节点、跨项目） */
  const [linkTable, setLinkTable] = useState<Record<string, CardLink>>({})
  const [external, setExternal] = useState<ExternalCard[]>([])
  const [linkMode, setLinkMode] = useState<'parent' | 'reference' | null>(null)
  const [linkFrom, setLinkFrom] = useState<string | null>(null)
  const [activeEdge, setActiveEdge] = useState<string | null>(null)
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

    // ★ 保留**所有**已存位置（含跨项目外来卡的负 id），否则重开白板时它们会被重置
    const next: Record<number, Pos> = { ...(savedPos ?? {}) }
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

  /** 本节点笔记 + 外来卡，统一用全局卡片 id 认人 */
  const globalIdOf = (local: number): string | null => {
    const n = notes.find((x) => x.id === local)
    if (n) return n.card_id || cardId(projectRef, n.ref)
    return external.find((x) => x.id === local)?.card ?? null
  }
  const localIdOf = (global: string): number | null => {
    const n = notes.find((x) => (x.card_id || cardId(projectRef, x.ref)) === global)
    if (n) return n.id
    return external.find((x) => x.card === global)?.id ?? null
  }

  const notesKey = notes.map((n) => n.card_id || cardId(projectRef, n.ref)).join('|')

  /** ★ 拉链：当前节点这批卡 + 与它们相连的所有卡（跨节点 / 跨项目） */
  const refreshLinks = useCallback(async () => {
    const ids = notes.map((n) => n.card_id || cardId(projectRef, n.ref))
    if (ids.length === 0) return
    try {
      const d = await personalApi.cardLinks(ids)
      setLinkTable(d.links)
      const all = Array.from(new Set([...ids, ...d.related]))
      const info = await personalApi.cardInfo(all)
      const ext: ExternalCard[] = all
        .filter((c) => !ids.includes(c) && info.cards[c])
        .map((c) => ({ id: externalLocalId(c), card: c, info: info.cards[c] }))
      setExternal(ext)
      // 外来卡自动上板；第一次出现放右侧空白处，之后位置由用户拖
      setOnBoard((prev) => {
        const next = new Set(prev)
        ext.forEach((e) => next.add(e.id))
        return next
      })
      setPos((prev) => {
        const next = { ...prev }
        let y = PAD
        ext.forEach((e) => {
          if (!next[e.id]) {
            next[e.id] = { x: PAD + (DEF_W + GAP) * 2, y }
            y += DEF_H + GAP
          }
        })
        return next
      })
    } catch {
      /* 拉不到链就只显示本节点卡片，不报错 */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notesKey, projectRef])

  useEffect(() => {
    if (open) void refreshLinks()
  }, [open, refreshLinks])

  /** ★ 两次点击连边：第一张 → 第二张（parent 时第一张是父） */
  const clickCard = async (global: string) => {
    if (!linkMode || !global) return
    if (!linkFrom) {
      setLinkFrom(global)
      return
    }
    if (linkFrom === global) return
    try {
      if (linkMode === 'parent') {
        await personalApi.setParent(global, linkFrom)
      } else {
        await personalApi.addReference(linkFrom, global)
      }
      await refreshLinks()
    } catch {
      /* 防环被拒等，静默 */
    }
    setLinkMode(null)
    setLinkFrom(null)
  }

  /** ★ 断边：不动卡片，只解关系 */
  const cutEdge = async (key: string) => {
    const [type, a, b] = key.split('|')
    try {
      if (type === 'parent') await personalApi.setParent(b, null)
      else await personalApi.removeReference(a, b)
      await refreshLinks()
    } catch {
      /* ignore */
    }
    setActiveEdge(null)
  }

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
  /** ★ 两种边：实线箭头 = 深入（parent），虚线 = 参见（引用） */
  const edges: { key: string; type: 'parent' | 'reference'; a: string; b: string }[] = []
  Object.entries(linkTable).forEach(([cid, rec]) => {
    if (rec.parent) {
      edges.push({ key: `parent|${rec.parent}|${cid}`, type: 'parent', a: rec.parent, b: cid })
    }
    rec.links.forEach((to) => {
      if (cid < to) {
        edges.push({ key: `reference|${cid}|${to}`, type: 'reference', a: cid, b: to })
      }
    })
  })

  const edgePoints = (e: (typeof edges)[number]) => {
    const la = localIdOf(e.a)
    const lb = localIdOf(e.b)
    if (la == null || lb == null) return null
    const pa = pos[la]
    const pb = pos[lb]
    if (!pa || !pb) return null
    const sa = sizeOf(la)
    const sb = sizeOf(lb)
    return {
      x1: pa.x + sa.w / 2,
      y1: pa.y + sa.h / 2,
      x2: pb.x + sb.w / 2,
      y2: pb.y + sb.h / 2,
    }
  }
  const activeEdgePts = activeEdge
    ? edgePoints({ key: activeEdge, ...(() => {
        const [type, a, b] = activeEdge.split('|')
        return { type: type as 'parent' | 'reference', a, b }
      })() })
    : null


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
          <button
            type="button"
            className="code-icon-btn"
            style={{
              marginLeft: 'auto',
              gap: 4,
              border: `1px solid ${linkMode === 'parent' ? 'var(--accent)' : 'var(--card-border)'}`,
              color: linkMode === 'parent' ? 'var(--accent)' : 'var(--text-sub)',
            }}
            title="连深入：先点父卡，再点子卡（实线）"
            onClick={() => {
              setLinkMode(linkMode === 'parent' ? null : 'parent')
              setLinkFrom(null)
            }}
          >
            <GitBranch size={13} /> 连深入
          </button>
          <button
            type="button"
            className="code-icon-btn"
            style={{
              gap: 4,
              border: `1px solid ${linkMode === 'reference' ? 'var(--accent)' : 'var(--card-border)'}`,
              color: linkMode === 'reference' ? 'var(--accent)' : 'var(--text-sub)',
            }}
            title="连参见：点两张已写好的卡（虚线）"
            onClick={() => {
              setLinkMode(linkMode === 'reference' ? null : 'reference')
              setLinkFrom(null)
            }}
          >
            <Link2 size={13} /> 连参见
          </button>
          {linkMode && (
            <span className="faint" style={{ fontSize: 11 }}>
              {linkFrom ? '再点第二张卡' : '先点第一张卡'} · <button
                type="button"
                className="code-icon-btn"
                onClick={() => {
                  setLinkMode(null)
                  setLinkFrom(null)
                }}
              >取消</button>
            </span>
          )}
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
            {/* ★★ 卡片盒的链：实线箭头 = 深入，虚线 = 参见 */}
            <svg
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                width: canvas.w,
                height: canvas.h,
                pointerEvents: 'none',
              }}
            >
              <defs>
                <marker id="tbArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                  <path d="M0,0 L8,4 L0,8 z" fill="rgba(16,29,51,.55)" />
                </marker>
              </defs>
              {edges.map((e) => {
                const q = edgePoints(e)
                if (!q) return null
                const on = activeEdge === e.key
                const common = {
                  x1: q.x1, y1: q.y1, x2: q.x2, y2: q.y2,
                  stroke: e.type === 'parent' ? 'rgba(16,29,51,.55)' : 'var(--accent, #2563eb)',
                  strokeWidth: on ? 3 : 1.6,
                  strokeDasharray: e.type === 'reference' ? '5 4' : undefined,
                  markerEnd: e.type === 'parent' ? 'url(#tbArrow)' : undefined,
                }
                return (
                  <g key={e.key}>
                    <line {...common} />
                    <line
                      x1={q.x1} y1={q.y1} x2={q.x2} y2={q.y2}
                      stroke="transparent"
                      strokeWidth={14}
                      style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
                      onClick={() => setActiveEdge(on ? null : e.key)}
                    />
                  </g>
                )
              })}
            </svg>

            {/* 点线后浮出 ×：点掉即断（不删卡） */}
            {activeEdge && activeEdgePts && (
              <button
                type="button"
                title="断掉这条链（卡片保留）"
                onClick={() => void cutEdge(activeEdge)}
                style={{
                  position: 'absolute',
                  left: (activeEdgePts.x1 + activeEdgePts.x2) / 2 - 11,
                  top: (activeEdgePts.y1 + activeEdgePts.y2) / 2 - 11,
                  width: 22,
                  height: 22,
                  borderRadius: '50%',
                  border: '1px solid var(--card-border)',
                  background: 'var(--card)',
                  color: 'var(--err)',
                  cursor: 'pointer',
                  zIndex: 3,
                }}
              >
                ×
              </button>
            )}

            {boardNotes.length === 0 && external.filter((e) => onBoard.has(e.id)).length === 0 && (
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
                  onPointerDown={(e) => {
                    if (linkMode) return
                    onPointerDown(e, n.id)
                  }}
                  onClick={() => {
                    if (linkMode) void clickCard(n.card_id || cardId(projectRef, n.ref))
                  }}
                  onDoubleClick={() => {
                    if (linkMode) return
                    navigate(`/p/${encodeURIComponent(projectRef)}/notes/${n.ref}`)
                  }}
                  title={linkMode ? '连线模式：点两张卡建立关系' : '拖动排布 · 右下角改大小 · 双击打开'}
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
                    cursor: linkMode ? 'pointer' : active ? 'grabbing' : 'grab',
                    outline:
                      linkFrom && linkFrom === (n.card_id || cardId(projectRef, n.ref))
                        ? '2px solid var(--accent)'
                        : undefined,
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

            {/* ★★ 跨节点 / 跨项目的卡：只读，能看、能拖、能连，双击回它自己的项目 */}
            {external
              .filter((e) => onBoard.has(e.id))
              .map((e) => {
                const p = pos[e.id] ?? { x: PAD, y: PAD }
                const selected = linkFrom === e.card
                return (
                  <div
                    key={e.id}
                    onPointerDown={(ev) => {
                      if (linkMode) return
                      onPointerDown(ev, e.id)
                    }}
                    onClick={() => {
                      if (linkMode) void clickCard(e.card)
                    }}
                    onDoubleClick={() => {
                      if (linkMode) return
                      navigate(
                        `/p/${encodeURIComponent(e.info.project_ref)}/notes/${e.info.ref}`,
                      )
                    }}
                    title="只读 · 双击打开它所在的项目"
                    style={{
                      position: 'absolute',
                      left: p.x,
                      top: p.y,
                      width: DEF_W,
                      minHeight: 90,
                      boxSizing: 'border-box',
                      padding: '8px 10px',
                      borderRadius: 10,
                      background: '#f8fafc',
                      border: '1px dashed rgba(15,23,42,.28)',
                      borderLeft: '4px solid var(--accent, #2563eb)',
                      boxShadow: '0 2px 8px rgba(15,23,42,.08)',
                      cursor: linkMode ? 'pointer' : 'grab',
                      outline: selected ? '2px solid var(--accent)' : undefined,
                      userSelect: 'none',
                      touchAction: 'none',
                      fontSize: 12,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 5,
                    }}
                  >
                    <div style={{ fontWeight: 600, lineHeight: 1.5 }}>
                      《{e.info.title || '无标题'}》
                    </div>
                    <div className="faint" style={{ fontSize: 11 }}>
                      {e.info.project} · {e.info.node || e.info.kind}
                    </div>
                    <div className="faint" style={{ fontSize: 10.5, marginTop: 'auto' }}>
                      只读 · 来自其它节点/项目
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
