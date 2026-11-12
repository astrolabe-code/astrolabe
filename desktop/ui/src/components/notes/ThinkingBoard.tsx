import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  X,
  Plus,
  Check,
  GitBranch,
  GitFork,
  Link2,
  ChevronUp,
  ChevronDown,
  Undo2,
  FolderOpen,
  FilePlus2,
  Save,
} from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import type { Note, NoteKind } from '../../api/types'
import { cardId, type CardInfo, type CardLink, type CardSearchHit } from '../../api/code'
import { personalApi } from '../../api/personal'
import type { BoardLayout } from '../../api/personal'
import { ribbonActions } from '../../lib/ribbonBus'
import { openTab, setTabTitle } from '../../lib/tabBus'
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
  /** ★ 白板 id（一个节点可挂多块；默认白板就是 String(nodeId)） */
  boardId: string
  notes: Note[]
  /** ★ 从卡片「链」进来：自动展示这张卡的父代 / 子代 / 引用，⛔ 不用用户自己加 */
  focusCardId?: string
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

export default function ThinkingBoard({
  open,
  projectRef,
  nodeId,
  boardId,
  notes,
  focusCardId,
  onClose,
}: ThinkingBoardProps) {
  const navigate = useNavigate()
  const loc = useLocation()
  const [pos, setPos] = useState<Record<number, Pos>>({})
  const [sizes, setSizes] = useState<Record<number, Size>>({})
  const [canvas, setCanvas] = useState<Size>({ w: INIT_W, h: INIT_H })
  const [onBoard, setOnBoard] = useState<Set<number>>(new Set())
  /** ★ Obsidian 式取笔记：顶部搜索框 + 平铺笔记列表（⛔ 不再先分五个盒子） */
  const [pickQuery, setPickQuery] = useState('')
  /** ★ 搜索结果（null=未搜，用默认前 N 条）；输入即走后端 FTS 按需取，不一次性拉全量 */
  const [searchHits, setSearchHits] = useState<CardSearchHit[] | null>(null)
  useEffect(() => {
    const q = pickQuery.trim()
    if (!q) {
      setSearchHits(null)
      return
    }
    const t = setTimeout(() => {
      personalApi
        .searchCards(q, projectRef)
        .then((r) => setSearchHits(r.notes || []))
        .catch(() => setSearchHits([]))
    }, 250)
    return () => clearTimeout(t)
  }, [pickQuery, projectRef])


  // ★★ 思考模式**自身全屏**（* 去掉外框留白，* 白布铺满整个屏幕）⚠

  const [draggingId, setDraggingId] = useState<number | null>(null)
  const [resizingId, setResizingId] = useState<number | null>(null)
  const dragRef = useRef<{ id: number; dx: number; dy: number } | null>(null)
  /** ★★ D139：卡片盒的链（跨节点、跨项目） */
  const [linkTable, setLinkTable] = useState<Record<string, CardLink>>({})
  const [external, setExternal] = useState<ExternalCard[]>([])
  const [linkMode, setLinkMode] = useState<'parent' | 'reference' | null>(null)
  const [linkFrom, setLinkFrom] = useState<string | null>(null)
  const [activeEdge, setActiveEdge] = useState<string | null>(null)
  /** ★ 底部图标打开「取笔记」浮层（⛔ 五个盒子不再常驻顶部） */
  const [pickerOpen, setPickerOpen] = useState(false)

  // ★ 点击浮层与按钮之外任意处关闭取笔记浮层
  const pickerRef = useRef<HTMLDivElement>(null)
  const pickerBtnRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!pickerOpen) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement
      if (pickerRef.current?.contains(t)) return
      if (pickerBtnRef.current?.contains(t)) return
      setPickerOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [pickerOpen])
  useEffect(() => {
    if (open) ribbonActions().closePanel?.()
  }, [open])
  /** ★ 点「上一张 / 下一张」逐张展开的卡；开始为空 ⇒ 只显示进入的那一张 */
  const [expanded, setExpanded] = useState<string[]>([])
  /** ★★ 当前选中的卡片：「上一张 / 下一张」相对它，而不是相对进入时的那张 */
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null)
  const expandedRef = useRef<string[]>([])
  const resizeRef = useRef<{
    id: number
    startX: number
    startY: number
    startW: number
    startH: number
  } | null>(null)
  const boardRef = useRef<HTMLDivElement>(null)

  const sizeOf = (id: number): Size => sizes[id] ?? { w: DEF_W, h: DEF_H }

  // ---------------------------------------------------------- 读取已保存状态（后端）
  const loadedRef = useRef(false)
  // ★ 白板名字：不在工具条里写，跟笔记一样在「保存」弹窗里确认（可改，有默认名）
  const [boardName, setBoardName] = useState('')

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [saved, setSaved] = useState(false)

  /** ★ 点保存按钮：先弹窗，预填当前 / 默认名字，让人看一眼、可改 */
  const handleSave = () => {
    setDraftTitle(boardName)
    setConfirmOpen(true)
  }

  /** ★ 弹窗确认：名字 + 布局一起写回后端 */
  const doSave = () => {
    const name = draftTitle.trim() || boardName
    setBoardName(name)
    personalApi
      .saveBoard(projectRef, boardId, {
        pos, board: [...onBoard], sizes, canvas,
        ...(name ? { name } : {}),
      })
      .then(() => {
        // ★★ 保存后把弹窗里改过的名字同步给这条白板标签
        if (name) setTabTitle(loc.pathname, name)
        setSaved(true)
        window.setTimeout(() => setSaved(false), 1600)
      })
      .catch(() => {})
    setConfirmOpen(false)
  }
  useEffect(() => {
    if (!open) return
    loadedRef.current = false
    let alive = true
    ;(async () => {
      let layout: BoardLayout | null = null
      try {
        layout = await personalApi.board(projectRef, boardId)
      } catch {
        layout = null
      }
      if (!alive) return
      setBoardName(layout?.name ?? '')
      const savedPos = layout?.pos ?? null
      const savedSize = layout?.sizes ?? null
      const savedBoard = layout?.board ?? null
      const savedCanvas = layout?.canvas ?? null

      const board = new Set<number>(
        (savedBoard ?? []).filter((id) => notes.some((n) => n.id === id)),
      )
      // ★ 负 id = 跨项目外来卡（自动上板，⛔ 不被恢复逻辑清掉）；
      //   点「链」进来时全部自动卡都保留
      setOnBoard((prev) => {
        const next = new Set(board)
        prev.forEach((id) => {
          if (!focusCardId && id < 0) next.add(id)
        })
        return next
      })
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
      setPickQuery('')
      loadedRef.current = true
    })()
    return () => {
      alive = false
    }
  }, [open, nodeId, notes, boardId])

  // ★★★ 布局 / 名字变更后防抖写回后端（替代原 localStorage 即时写）
  useEffect(() => {
    if (!loadedRef.current) return
    const t = setTimeout(() => {
      const name = boardName.trim()
      personalApi
        .saveBoard(projectRef, boardId, {
          pos, board: [...onBoard], sizes, canvas,
          ...(name ? { name } : {}),
        })
        .catch(() => {})
    }, 400)
    return () => clearTimeout(t)
  }, [pos, sizes, onBoard, canvas, projectRef, boardId, boardName])

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

  /** ★ 拉链：点「链」进来时只围绕**那一张卡**，自动把父 / 子 / 引用全放上板 */
  const refreshLinks = useCallback(async () => {
    const mine = notes.map((n) => ({ id: n.id, card: n.card_id || cardId(projectRef, n.ref) }))
    const seed = focusCardId ? [focusCardId] : mine.map((m) => m.card)
    if (seed.length === 0) return
    try {
      const d = await personalApi.cardLinks(seed)
      setLinkTable(d.links)
      const all = Array.from(
        new Set([...seed, ...d.related, ...expandedRef.current]),
      )
      const info = await personalApi.cardInfo(all)
      const ext: ExternalCard[] = all
        .filter((c) => !mine.some((m) => m.card === c) && info.cards[c])
        .map((c) => ({ id: externalLocalId(c), card: c, info: info.cards[c] }))
      setExternal(ext)

      const localOf = (card: string): number => {
        const m = mine.find((x) => x.card === card)
        if (m) return m.id
        // ★ 孙辈 / 跨项目卡即使还没进 ext，也能按全局 id 算出稳定位置
        return ext.find((e) => e.card === card)?.id ?? externalLocalId(card)
      }

      // ★★ 点「链」进来：**开始只显示这一张卡**；父代 / 子代由顶栏按钮逐张展开
      const autoCards = focusCardId
        ? [focusCardId, ...expandedRef.current]
        : ext.map((e) => e.card)
      const autoIds = autoCards.map(localOf)
      setOnBoard((prev) => {
        const next = focusCardId ? new Set<number>() : new Set(prev)
        autoIds.forEach((id) => next.add(id))
        return next
      })
      setPos((prev) => {
        const next = { ...prev }
        autoIds.forEach((id, i) => {
          if (!next[id]) {
            next[id] = {
              x: PAD + (DEF_W + GAP) * (i % 3),
              y: PAD + Math.floor(i / 3) * (DEF_H + GAP),
            }
          }
        })
        return next
      })
    } catch {
      /* 拉不到链就只显示本节点卡片，不报错 */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notesKey, projectRef, focusCardId])

  useEffect(() => {
    expandedRef.current = []
    setExpanded([])
    setSelectedCardId(focusCardId || null)
  }, [focusCardId, open])

  useEffect(() => {
    if (open) void refreshLinks()
  }, [open, refreshLinks])

  /** ★ 上一张 / 下一张：把**这一张**卡摆上板，并拉它自己的父/子关系
      （⛔ 否则展开一张子卡后，点它的「下一张」就没有孙辈数据了） */
  const showCard = async (card: string) => {
    const mineCard = notes.find(
      (n) => (n.card_id || cardId(projectRef, n.ref)) === card,
    )
    const local =
      mineCard?.id ??
      external.find((e) => e.card === card)?.id ??
      externalLocalId(card)

    const next = expandedRef.current.includes(card)
      ? expandedRef.current
      : [...expandedRef.current, card]
    expandedRef.current = next
    setExpanded(next)
    setOnBoard((prev) => {
      const s2 = new Set(prev)
      s2.add(local)
      return s2
    })
    setPos((prev) => {
      if (prev[local]) return prev
      const i = Object.keys(prev).length
      return {
        ...prev,
        [local]: {
          x: PAD + (DEF_W + GAP) * (i % 3),
          y: PAD + Math.floor(i / 3) * (DEF_H + GAP),
        },
      }
    })

    try {
      const d = await personalApi.cardLinks([card])
      setLinkTable((prev) => ({ ...prev, ...d.links }))
      const all = Array.from(new Set([card, ...d.related]))
      const info = await personalApi.cardInfo(all)
      setExternal((prev) => {
        const have = new Set(prev.map((e) => e.card))
        const mineIds = new Set(
          notes.map((n) => n.card_id || cardId(projectRef, n.ref)),
        )
        const add: ExternalCard[] = all
          .filter((c) => !have.has(c) && !mineIds.has(c) && info.cards[c])
          .map((c) => ({ id: externalLocalId(c), card: c, info: info.cards[c] }))
        return add.length ? [...prev, ...add] : prev
      })
    } catch {
      /* 拉不到就只显示这张卡 */
    }
  }

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

  /** ★★ 画布**无边界**：卡片拖/缩到超出范围 ⇒ 自动扩（* 只增不减）⚠ */
  const growCanvas = useCallback((x: number, y: number, w: number, h: number) => {
    setCanvas((prev) => {
      const needW = x + w + GROW_STEP
      const needH = y + h + GROW_STEP
      if (needW <= prev.w && needH <= prev.h) return prev
      const next = { w: Math.max(prev.w, needW), h: Math.max(prev.h, needH) }
      return next
    })
  }, [nodeId])

  // ---------------------------------------------------------- 加入 / 移除
  const addToBoard = (n: Note) => {
    setOnBoard((prev) => {
      if (prev.has(n.id)) return prev
      const next = new Set(prev)
      next.add(n.id)
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
      growCanvas(PAD, y, DEF_W, DEF_H)
      return next
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }

  const removeFromBoard = (id: number) => {
    setOnBoard((prev) => {
      const next = new Set(prev)
      next.delete(id)
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
    setSizes((prev) => prev)
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
  /** ★ 选中谁，按钮就对谁；没选中时回落到进入的那张卡 */
  const navTarget = selectedCardId || focusCardId || ''
  const kids = linkTable[navTarget]?.children ?? []
  const refs = linkTable[navTarget]?.links ?? []
  const pendingKids = kids.filter((c) => !expanded.includes(c))
  const pendingRefs = refs.filter((c) => !expanded.includes(c))
  const titleOf = (card: string) => {
    const n = notes.find((x) => (x.card_id || cardId(projectRef, x.ref)) === card)
    if (n) return n.title || n.ref
    return (
      external.find((e) => e.card === card)?.info.title ||
      card.split('/').pop() ||
      card
    )
  }
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
    // ★ 两张卡都真的在板上才画线 —— 否则点「链」进来会凭旧坐标画出幽灵线
    if (!onBoard.has(la) || !onBoard.has(lb)) return null
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


  return createPortal(
    <div
      style={{
        position: 'fixed',
        // ★ 从全局顶栏下面开始，铺满其余视口（⛔ 不再只占右栏半边）
        inset: 'var(--nav-h, 40px) 0 0 0',
        zIndex: 90,
        background: 'var(--card)',
        display: 'flex',
        flexDirection: 'column',
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
          borderRadius: 0,
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {/* ★★★ 顶部零工具行：功能全部浮动到右侧 / 底部 / 右下角
            所有者：「只有一个问题，那就是顶部标题行太多，
                    obsidian取文件是从下面三个图标里取的」 */}

        {/* 右侧浮动竖栏：上一张 / 下一张 / 参见 / 连深入 / 连参见 / 取消 / 关闭 */}
        <div
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            zIndex: 5,
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
            padding: 4,
            borderRadius: 10,
            border: '1px solid var(--card-border)',
            background: 'var(--card)',
          }}
        >
          {[
            {
              icon: <ChevronUp size={16} strokeWidth={1.5} />,
              title: '上一张：显示选中卡片的父代',
              disabled: !navTarget || !linkTable[navTarget]?.parent,
              onClick: () => {
                const p = linkTable[navTarget]?.parent
                if (p) void showCard(p)
              },
            },
            {
              icon: <ChevronDown size={16} strokeWidth={1.5} />,
              title: '下一张：逐张展开选中卡片的子代',
              disabled: !navTarget || pendingKids.length === 0,
              onClick: () => {
                if (pendingKids[0]) void showCard(pendingKids[0])
              },
            },
            {
              icon: <Link2 size={16} strokeWidth={1.5} />,
              title: '参见：逐张展开引用的卡片',
              disabled: !navTarget || pendingRefs.length === 0,
              onClick: () => {
                if (pendingRefs[0]) void showCard(pendingRefs[0])
              },
            },
            {
              icon: <GitBranch size={16} strokeWidth={1.5} />,
              title: '连深入：先点父卡，再点子卡',
              active: linkMode === 'parent',
              onClick: () => {
                setLinkMode(linkMode === 'parent' ? null : 'parent')
                setLinkFrom(null)
              },
            },
            {
              icon: <GitFork size={16} strokeWidth={1.5} />,
              title: '连参见：点两张已写好的卡',
              active: linkMode === 'reference',
              onClick: () => {
                setLinkMode(linkMode === 'reference' ? null : 'reference')
                setLinkFrom(null)
              },
            },
            ...(linkMode
              ? [{
                  icon: <Undo2 size={16} strokeWidth={1.5} />,
                  title: '取消连线',
                  onClick: () => {
                    setLinkMode(null)
                    setLinkFrom(null)
                  },
                }]
              : []),
            {
              icon: <X size={16} strokeWidth={1.5} />,
              title: '关闭思考模式',
              onClick: onClose,
            },
          ].map((b, i) => (
            <button
              key={i}
              type="button"
              title={b.title}
              aria-label={b.title}
              disabled={b.disabled}
              onClick={b.onClick}
              style={{
                display: 'grid',
                placeItems: 'center',
                width: 30,
                height: 30,
                padding: 0,
                border: 0,
                borderRadius: 6,
                background: b.active ? 'var(--accent-dim, rgba(37,99,235,.08))' : 'transparent',
                color: b.active ? 'var(--accent, #2563eb)' : 'var(--text-sub)',
                opacity: b.disabled ? 0.35 : 1,
                cursor: b.disabled ? 'not-allowed' : 'pointer',
              }}
            >
              {b.icon}
            </button>
          ))}
        </div>

        {/* 底部中间：从图标「取笔记 / 新建笔记」（⛔ 不再占顶部一排） */}
        <div
          style={{
            position: 'absolute',
            bottom: 16,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 5,
            display: 'flex',
            gap: 4,
            padding: 4,
            borderRadius: 10,
            border: '1px solid var(--card-border)',
            background: 'var(--card)',
          }}
        >
          <button
            type="button"
            title="取笔记：搜索并挑选"
            aria-label="取笔记"
            ref={pickerBtnRef}
            onClick={() => {
              setPickerOpen((v) => !v)
              setPickQuery('')
            }}
            style={{
              display: 'grid', placeItems: 'center', width: 32, height: 32,
              border: 0, borderRadius: 6,
              background: pickerOpen ? 'var(--accent-dim, rgba(37,99,235,.08))' : 'transparent',
              color: pickerOpen ? 'var(--accent, #2563eb)' : 'var(--text-sub)',
              cursor: 'pointer',
            }}
          >
            <FolderOpen size={17} strokeWidth={1.5} />
          </button>
          <button
            type="button"
            title="新建笔记"
            aria-label="新建笔记"
            onClick={() => {
              // ★ 白板路由下 NoteSection 没挂载 ⇒ createNote 回调不可用，直接走真实路由
              const vid = nodeId || ribbonActions().currentNodeVid || 0
              const path = `/p/${encodeURIComponent(projectRef)}/notes/new?node=${vid}`
              openTab(path.split('?')[0], '新笔记')
              navigate(path)
            }}
            style={{
              display: 'grid', placeItems: 'center', width: 32, height: 32,
              border: 0, borderRadius: 6, background: 'transparent',
              color: 'var(--text-sub)', cursor: 'pointer',
            }}
          >
            <FilePlus2 size={17} strokeWidth={1.5} />
          </button>
          <button
            type="button"
            title={saved ? '已保存' : '保存布局'}
            aria-label="保存布局"
            onClick={handleSave}
            style={{
              display: 'grid', placeItems: 'center', width: 32, height: 32,
              border: 0, borderRadius: 6, background: 'transparent',
              color: saved ? 'var(--accent, #2563eb)' : 'var(--text-sub)',
              cursor: 'pointer',
            }}
          >
            {saved ? <Check size={17} strokeWidth={1.5} /> : <Save size={17} strokeWidth={1.5} />}
          </button>
        </div>

        {/* 取笔记浮层：Obsidian 式「＋」—— 顶部搜索框 + 平铺笔记列表（点一条上板） */}
        {pickerOpen && (
          <div
            ref={pickerRef}
            style={{
              position: 'absolute',
              bottom: 62,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 6,
              width: 440,
              maxWidth: '90vw',
              maxHeight: '48vh',
              overflow: 'auto',
              padding: 10,
              borderRadius: 12,
              border: '1px solid var(--card-border)',
              background: 'var(--card)',
              boxShadow: '0 12px 32px rgba(15,23,42,.16)',
            }}
          >
            <input
              autoFocus
              value={pickQuery}
              onChange={(e) => setPickQuery(e.target.value)}
              placeholder="搜索…"
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '6px 10px',
                borderRadius: 8,
                border: '1px solid var(--card-border)',
                background: 'var(--card)',
                color: 'var(--text-main)',
                fontSize: 13,
                outline: 'none',
              }}
            />
            <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column' }}>
              {(() => {
                // ★ 默认：本节点优先排序后取前 15 条；搜索：用后端 FTS 命中（可搜正文，按需取）
                const items = searchHits
                  ? searchHits.map((h) => {
                      const note = notes.find((n) => n.ref === h.ref) || null
                      return {
                        key: h.ref,
                        note,
                        inBoard: note ? onBoard.has(note.id) : false,
                        color: kindMeta(h.kind as NoteKind).color,
                        label: h.title || h.snippet,
                      }
                    })
                  : notes
                      .slice()
                      .sort((a, b) => {
                        const am = a.node_id === nodeId ? 0 : 1
                        const bm = b.node_id === nodeId ? 0 : 1
                        return am !== bm ? am - bm : (a.title || '').localeCompare(b.title || '')
                      })
                      .slice(0, 15)
                      .map((n) => ({
                        key: String(n.id),
                        note: n,
                        inBoard: onBoard.has(n.id),
                        color: kindMeta(n.kind).color,
                        label: n.title || n.body.replace(/\s+/g, ' ').slice(0, 32),
                      }))
                if (items.length === 0) {
                  return (
                    <span className="faint" style={{ fontSize: 11.5, padding: '8px 4px' }}>
                      {searchHits ? '没有匹配的笔记' : '这个节点下还没有笔记'}
                    </span>
                  )
                }
                return items.map((it) => {
                  if (!it.note) return null
                  const n = it.note
                  const inBoard = it.inBoard
                  const c = it.color
                  return (
                    <button
                      key={it.key}
                      type="button"
                      onClick={() => (inBoard ? removeFromBoard(n.id) : addToBoard(n))}
                      title={inBoard ? '从白布移除' : '放到白布'}
                      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(15,23,42,.06)' }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        width: '100%',
                        padding: '6px 8px',
                        borderRadius: 8,
                        border: 0,
                        background: 'transparent',
                        color: 'var(--text-main)',
                        fontSize: 12.5,
                        cursor: 'pointer',
                        textAlign: 'left',
                      }}
                    >
                      <span style={{ width: 7, height: 7, borderRadius: 4, flexShrink: 0, background: c, opacity: inBoard ? 1 : 0.55 }} />
                      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {it.label}
                      </span>
                      {inBoard ? (
                        <Check size={13} style={{ flexShrink: 0, color: c }} />
                      ) : (
                        <Plus size={13} style={{ flexShrink: 0, color: 'var(--text-sub)' }} />
                      )}
                    </button>
                  )
                })
              })()}
            </div>
          </div>
        )}

        {/* 右下角：当前选中状态（不占顶部行） */}
        {focusCardId && (
          <div
            className="faint"
            style={{ position: 'absolute', bottom: 12, right: 14, fontSize: 11, zIndex: 4 }}
          >
            选中《{titleOf(navTarget)}》· 父代 {linkTable[navTarget]?.parent ? 1 : 0}
            · 子代 {kids.length} · 引用 {refs.length} · 已展开 {expanded.length}
            {linkMode ? ` · ${linkFrom ? '再点第二张卡' : '先点第一张卡'}` : ''}
          </div>
        )}

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
                    const gid = n.card_id || cardId(projectRef, n.ref)
                    if (linkMode) void clickCard(gid)
                    else setSelectedCardId(gid)
                  }}
                  onDoubleClick={() => {
                    if (linkMode) return
                    const path = `/p/${encodeURIComponent(projectRef)}/notes/${n.ref}`
                    openTab(path, n.title || '笔记')
                    navigate(path)
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
                      selectedCardId === (n.card_id || cardId(projectRef, n.ref))
                        ? '2px solid var(--accent)'
                        : linkFrom === (n.card_id || cardId(projectRef, n.ref))
                          ? '2px dashed var(--accent)'
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
                const selected = selectedCardId === e.card
                const linkPicked = linkFrom === e.card
                return (
                  <div
                    key={e.id}
                    onPointerDown={(ev) => {
                      if (linkMode) return
                      onPointerDown(ev, e.id)
                    }}
                    onClick={() => {
                      if (linkMode) void clickCard(e.card)
                      else setSelectedCardId(e.card)
                    }}
                    onDoubleClick={() => {
                      if (linkMode) return
                      const path = `/p/${encodeURIComponent(e.info.project_ref)}/notes/${e.info.ref}`
                      openTab(path, e.info.title || '笔记')
                      navigate(path)
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
                      outline: selected
                        ? '2px solid var(--accent)'
                        : linkPicked
                          ? '2px dashed var(--accent)'
                          : undefined,
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

      {/* ★★ 保存白板弹窗（跟笔记「保存这篇笔记」同款）：点保存后才弹，
          预填默认名 / 已有名字，可改；留空就用默认名 ⚠ */}
      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="保存白板"
        width={480}
        footer={
          <div className="flex items-center gap-2">
            <div style={{ marginLeft: 'auto' }} />
            <Button onClick={() => setConfirmOpen(false)}>再改改</Button>
            <Button variant="primary" onClick={doSave}>确认保存</Button>
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <div>
            <label
              className="block text-xs font-medium tracking-wide text-text-sub mb-1.5"
              htmlFor="board-save-title"
            >
              名字（可改）
            </label>
            <input
              id="board-save-title"
              className="input"
              maxLength={60}
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  doSave()
                }
              }}
            />
          </div>
          <div
            style={{
              fontSize: 11.5,
              padding: '6px 10px',
              borderRadius: 8,
              background: 'var(--accent-dim)',
              color: 'var(--text-sub)',
              lineHeight: 1.7,
            }}
          >
            留空则使用默认名：
            <b style={{ color: 'var(--text-main)', marginLeft: 4 }}>{boardName}</b>
          </div>
        </div>
      </Modal>
    </div>,
    document.body,
  )
}
