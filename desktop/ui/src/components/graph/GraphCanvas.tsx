import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Sigma from 'sigma'
import { NodeCircleProgram, EdgeArrowProgram } from 'sigma/rendering'
import DirectedGraph from 'graphology'
import forceAtlas2 from 'graphology-layout-forceatlas2'
import { startMeteor } from '../../lib/meteorFx'
import { graphLog, n1 } from '../../lib/graphLog'
import type { EffectiveGraph, GraphEdge, GraphNode } from '../../lib/mergeGraph'
import { kindColor } from '../../lib/kindLabel'
import NodeHoverCard from '../node/NodeHoverCard'
import { useAiBusy } from '../../lib/aiBusy'
import EdgeHoverCard from './EdgeHoverCard'

/**
 * ★★ 图谱画布（sigma.js 3 + graphology，2026-11-22 从头重写）
 *
 * 设计原则：
 * 1. sigma 实例只建一次（依赖只有 graph）——主题/选中/高亮都走属性 + refresh
 * 2. sigma 挂专用 host div —— kill() 会清空容器，绝不挂 React 管理的 box
 * 3. hover 用 sigma 原生 enterNode/leaveNode，不自己 hit-test
 * 4. 纯逻辑拆 helper，effect 只负责调用 + 清理
 */

// ---------------------------------------------------------------- 常量 / 工具

const LABEL_MAX_NAME = 16
const LABEL_MAX_FILE = 22
const RING = 1                  // 初始圆环半径（与 ForceAtlas2 同尺度：1 不是 70px）
const SETTLE_MS = 2000          // 布局 + 适配时间
const HOVER_LINGER_MS = 800     // 浮窗滞留（给鼠标跨过去点按钮的时间）
const RING_GEO = { c: 48, r1: 24, r2: 42 }
const LABEL_ZOOM_THRESHOLD = 0.7
const LABEL_MIN_NODES = 30
const LABEL_TOP_DEGREE = 12

const truncate = (s: string, max: number) => {
  const t = (s || '').trim()
  return t.length > max ? `${t.slice(0, max)}…` : t
}
const labelMax = (n: GraphNode) =>
  n.kind === 'file' || n.kind === 'dir' ? LABEL_MAX_FILE : LABEL_MAX_NAME
const colorOf = (n: GraphNode) => kindColor(n.kind)

function ringArcPath(a1: number, a2: number): string {
  const { c, r1, r2 } = RING_GEO
  const pt = (r: number, a: number) => [c + r * Math.cos(a), c + r * Math.sin(a)] as const
  const [x1, y1] = pt(r2, a1), [x2, y2] = pt(r2, a2)
  const [x3, y3] = pt(r1, a2), [x4, y4] = pt(r1, a1)
  const large = a2 - a1 > Math.PI ? 1 : 0
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r2} ${r2} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} L ${x3.toFixed(2)} ${y3.toFixed(2)} A ${r1} ${r1} 0 ${large} 0 ${x4.toFixed(2)} ${y4.toFixed(2)} Z`
}

// ---------------------------------------------------------------- Props

interface GraphCanvasProps {
  graph?: EffectiveGraph
  fullGraph?: EffectiveGraph
  selectedVid?: number | null
  highlightVids?: number[]
  focusVid?: number | null
  onSelect: (vid: number) => void
  onDeselect?: () => void
  onPhase?: (phase: string) => void
  onGraphChanged?: () => void
  meteors?: boolean
  meteorSpeed?: number
  meteorSizeRatio?: number
  nodeSizePx?: number
}

// ---------------------------------------------------------------- 节点属性构造

/** 构造 graphology 节点属性（建图 / 展开邻居共用） */
function nodeAttrs(n: GraphNode, x: number, y: number, sizePx: number, labelColor: string) {
  const patched = !!n.patched
  return {
    x, y,
    size: n.origin === 'manual' ? Math.round(sizePx * 1.15) : sizePx,
    color: colorOf(n),
    label: truncate(n.name, labelMax(n)),
    labelColor,
    border: patched ? '#fbbf24' : '#ffffff',
    borderWidth: patched ? 2.5 : 2,
    kind: n.kind,
    origin: n.origin,
    patched,
    flow: false,
    selected: false,
    active: false,
    hideLabel: false,
  }
}

/** 构造 graphology 边属性 */
function edgeAttrs(e: GraphEdge, src: GraphNode | undefined) {
  return {
    color: src ? colorOf(src) : '#94a3b8',
    size: 1,
    manual: e.origin === 'manual',
    active: false,
  }
}

// ---------------------------------------------------------------- 组件

export default function GraphCanvas({
  graph,
  fullGraph,
  selectedVid,
  highlightVids,
  focusVid,
  onSelect,
  onDeselect,
  onPhase,
  onGraphChanged,
  meteors = true,
  meteorSpeed,
  meteorSizeRatio,
  nodeSizePx = 28,
}: GraphCanvasProps) {
  const boxRef = useRef<HTMLDivElement>(null)
  /** sigma 专用容器：kill() 会清空它，绝不挂 React 管理的 box */
  const sigmaHostRef = useRef<HTMLDivElement>(null)
  const sigmaRef = useRef<Sigma | null>(null)
  const graphRef = useRef<DirectedGraph | null>(null)
  const infoRef = useRef<Map<string, GraphNode>>(new Map())
  const activeRef = useRef<string[]>([])
  const wasSelectedRef = useRef<number | null>(null)
  const [ring, setRing] = useState<{ id: string; x: number; y: number } | null>(null)
  const [ringScale, setRingScale] = useState(1)
  const ringRef = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<{ node: GraphNode; x: number; y: number } | null>(null)
  const [edgeHover, setEdgeHover] = useState<{ edge: GraphEdge; x: number; y: number } | null>(null)
  const hoverRef = useRef<typeof hover>(null)
  const cardHoverRef = useRef(false)
  const leaveTimerRef = useRef(0)
  const [dataVersion, setDataVersion] = useState(0)
  const readyRef = useRef(0)
  const aiBusy = useAiBusy()

  // 标签颜色（读 CSS 变量，只更新属性不重建图）
  const readLabelColor = () =>
    getComputedStyle(document.documentElement).getPropertyValue('--text-main').trim() || '#000000'
  const [labelColor, setLabelColor] = useState(() => readLabelColor())

  useEffect(() => {
    const sync = () => setLabelColor(readLabelColor())
    const mo = new MutationObserver(sync)
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const t1 = window.setTimeout(sync, 50)
    const t2 = window.setTimeout(sync, 200)
    return () => { mo.disconnect(); clearTimeout(t1); clearTimeout(t2) }
  }, [])

  const nodeById = useMemo(
    () => new Map((graph?.nodes ?? []).map((n) => [String(n.vid), n])),
    [graph],
  )
  useEffect(() => { hoverRef.current = hover }, [hover])

  // ------------------------------------------------------------ 建图（只一次）
  useEffect(() => {
    const box = boxRef.current
    const host = sigmaHostRef.current
    if (!box || !host || !graph) return

    const W = box.clientWidth || 900
    const H = box.clientHeight || 600
    graphLog('build:start', { nodes: graph.nodes.length, edges: graph.edges.length, W, H })

    const G = new DirectedGraph({ type: 'directed' })
    graph.nodes.forEach((n, i) => {
      const ang = (i / Math.max(1, graph.nodes.length)) * Math.PI * 2
      G.addNode(String(n.vid), nodeAttrs(n, Math.cos(ang) * RING, Math.sin(ang) * RING, nodeSizePx, labelColor))
    })
    graph.edges.forEach((e) => {
      if (!G.hasNode(String(e.from)) || !G.hasNode(String(e.to))) return
      G.addEdge(String(e.from), String(e.to), edgeAttrs(e, nodeById.get(String(e.from))))
    })
    infoRef.current = new Map(graph.nodes.map((n) => [String(n.vid), n]))

    const sigma = new Sigma(G, host, {
      nodeProgramClasses: { circle: NodeCircleProgram },
      edgeProgramClasses: { arrow: EdgeArrowProgram },
      defaultNodeType: 'circle',
      defaultEdgeType: 'arrow',
      labelColor: { attribute: 'labelColor', color: '#94a3b8' },
      labelRenderedSizeThreshold: 0,
      renderEdgeLabels: false,
      // 状态样式全走 reducer（读节点/边属性），不重建图
      nodeReducer: (_id, a) => ({
        ...a,
        size: a.selected ? Number(a.size) * 1.25
            : a.flow ? Number(a.size) * 1.18
            : a.active ? Number(a.size) * 1.08
            : a.size,
        borderWidth: a.selected || a.flow ? 3 : a.active ? 3.5 : a.borderWidth,
        label: a.hideLabel ? '' : a.label,
      }),
      edgeReducer: (_id, a) => ({
        ...a,
        color: a.active ? '#22d3ee' : a.color,
        size: a.active ? 2.5 : a.size,
      }),
    })
    sigmaRef.current = sigma
    graphRef.current = G
    const dim = sigma.getDimensions()
    graphLog('sigma:created', { nodes: G.order, edges: G.size, canvas: `${dim.width}×${dim.height}` })
    onPhase?.('布局动画中…')

    // ★★★ 布局动画：分帧跑 ForceAtlas2，每帧 refresh + camera 跟随
    //   节点从中心小圆环**逐渐散开**（像 GitNexus），不是 2 秒后突然跳变。
    //   ⚠ 每帧都更新 camera ⇒ 节点始终在视口内，不会跑出去导致空白。
    const t0 = performance.now()
    const TOTAL_ITER = 120
    const ITER_PER_FRAME = 3
    const settings = forceAtlas2.inferSettings(G)
    let doneIter = 0
    let raf = 0
    let finished = false

    /**
     * ★ 仿 GitNexus（Cytoscape fcose）的动画口径：
     *   布局过程中**只动节点坐标**（每帧 refresh 看散开），camera 不动；
     *   结束后 fit 一次（animate 250ms）。⛔ 绝不每帧 setState camera ——
     *   那等于每帧「突然跳」，不是平滑动画。
     */
    const fitOnce = () => {
      const xs: number[] = [], ys: number[] = []
      G.forEachNode((_id, a) => { xs.push(a.x); ys.push(a.y) })
      if (!xs.length) return
      const minX = Math.min(...xs), maxX = Math.max(...xs)
      const minY = Math.min(...ys), maxY = Math.max(...ys)
      const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
      const bw = Math.max(1, maxX - minX), bh = Math.max(1, maxY - minY)
      const pad = 60
      // ★ 不 clamp 上限 —— FA2 尺度下 bbox 只有几个单位，
      //   clamp 到 1.6 会让图缩成中心一小团（GitNexus 的 fit:true 是撑满视口）
      const z = Math.min((W - pad * 2) / bw, (H - pad * 2) / bh)
      sigma.getCamera().animate(
        { ratio: 1 / Math.max(0.001, z), x: cx, y: cy },
        { duration: 250 },   // ★ 只 fit 一次，平滑收尾
      )
    }

    const tick = () => {
      if (sigmaRef.current !== sigma || finished) return
      try {
        forceAtlas2.assign(G, { iterations: ITER_PER_FRAME, settings })
        doneIter += ITER_PER_FRAME
        // ★ 动画期间平滑跟随 bbox（GitNexus fit:true 的口径）：
        //   用 setState 但 ratio 带阻尼（每帧只靠近目标 15%），不是硬跳。
        const xs: number[] = [], ys: number[] = []
        G.forEachNode((_id, a) => { xs.push(a.x); ys.push(a.y) })
        if (xs.length) {
          const minX = Math.min(...xs), maxX = Math.max(...xs)
          const minY = Math.min(...ys), maxY = Math.max(...ys)
          const bw = Math.max(1, maxX - minX), bh = Math.max(1, maxY - minY)
          const targetRatio = Math.min(1 / 0.001, Math.min((W - 120) / bw, (H - 120) / bh))
          const cur = sigma.getCamera().getState()
          const eased = {
            x: cur.x + ((minX + maxX) / 2 - cur.x) * 0.15,
            y: cur.y + ((minY + maxY) / 2 - cur.y) * 0.15,
            ratio: cur.ratio + (1 / targetRatio - cur.ratio) * 0.15,
          }
          sigma.getCamera().setState(eased)
        }
        sigma.refresh()
      } catch (e) {
        graphLog('layout:ERROR', { err: String(e) })
        finished = true
      }
      if (doneIter < TOTAL_ITER) {
        raf = requestAnimationFrame(tick)
      } else {
        finished = true
        graphLog('layout:done', { ms: Math.round(performance.now() - t0), iterations: doneIter })
        fitOnce()         // ★ 结束后 fit 一次（GitNexus 的 fit:true）
        readyRef.current = Date.now()
        const dim = sigma.getDimensions()
        graphLog('ready', { nodes: G.order, canvas: `${dim.width}×${dim.height}` })
        onPhase?.('布局完成')
      }
    }

    // ★ 初始 camera 对准初始圆环中心（节点散开时不用移动视口）
    sigma.getCamera().setState({ x: 0, y: 0, ratio: 1 })
    raf = requestAnimationFrame(tick)

    // 清理时取消动画帧
    const settle = window.setTimeout(() => {
      if (sigmaRef.current !== sigma) return
      graphLog('settle:noop', { nodes: G.order })
    }, SETTLE_MS)

    // sigma 原生事件
    sigma.on('clickNode', ({ node }) => {
      const a = G.getNodeAttributes(node)
      const v = sigma.graphToViewport({ x: a.x, y: a.y })
      setRing({ id: node, x: v.x, y: v.y })
      setRingScale(Math.max(1, Math.min(1 / sigma.getCamera().getState().ratio, 1.6)))
      onSelect(Number(node))
    })
    sigma.on('clickStage', () => setRing(null))

    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(settle)
      sigmaRef.current = null
      graphRef.current = null
      readyRef.current = 0
      sigma.kill()   // 只清 sigmaHost，不碰 React 的 box
    }
    // ★ 只依赖 graph —— 主题/选中/高亮都走属性更新，不重建
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph])

  // ------------------------------------------------------------ 主题色：只更新属性
  useEffect(() => {
    const G = graphRef.current
    if (!G) return
    let changed = false
    G.forEachNode((id) => {
      if (G.getNodeAttribute(id, 'labelColor') !== labelColor) {
        G.updateNodeAttribute(id, 'labelColor', () => labelColor)
        changed = true
      }
    })
    if (changed) { sigmaRef.current?.refresh(); graphLog('theme', { labelColor }) }
  }, [labelColor])

  // ------------------------------------------------------------ 选中态
  useEffect(() => {
    const G = graphRef.current
    if (!G) return
    const cur = selectedVid ?? null
    const prev = wasSelectedRef.current
    const paint = (vid: number, on: boolean) => {
      const id = String(vid)
      if (!G.hasNode(id)) return
      G.updateNodeAttribute(id, 'selected', () => on)
    }
    if (prev != null && prev !== cur) paint(prev, false)
    if (cur != null) paint(cur, true)
    wasSelectedRef.current = cur
    sigmaRef.current?.refresh()
  }, [selectedVid, graph])

  // ------------------------------------------------------------ 执行流高亮
  useEffect(() => {
    const G = graphRef.current
    if (!G) return
    for (const id of activeRef.current) if (G.hasNode(id)) G.updateNodeAttribute(id, 'flow', () => false)
    activeRef.current = []
    for (const v of highlightVids ?? []) {
      const id = String(v)
      if (!G.hasNode(id)) continue
      G.updateNodeAttribute(id, 'flow', () => true)
      activeRef.current.push(id)
    }
    sigmaRef.current?.refresh()
  }, [highlightVids, graph])

  // ------------------------------------------------------------ hover（sigma 原生 + 邻居高亮）
  const clearActive = useCallback(() => {
    const G = graphRef.current
    if (!G) return
    for (const id of activeRef.current) {
      if (G.hasNode(id)) {
        G.updateNodeAttribute(id, 'active', () => false)
        G.forEachEdge(id, (e) => G.updateEdgeAttribute(e, 'active', () => false))
      }
    }
    activeRef.current = []
    sigmaRef.current?.refresh()
  }, [])

  useEffect(() => {
    const sigma = sigmaRef.current
    const G = graphRef.current
    if (!sigma || !G) return

    const onEnter = ({ node }: { node: string }) => {
      clearTimeout(leaveTimerRef.current)
      // 高亮自己 + 一度邻居 + 相连边
      clearActive()
      G.updateNodeAttribute(node, 'active', () => true)
      activeRef.current = [node]
      G.forEachEdge(node, (e) => {
        G.updateEdgeAttribute(e, 'active', () => true)
        const [s, t] = G.extremities(e)
        const other = s === node ? t : s
        if (G.hasNode(other) && !activeRef.current.includes(other)) {
          G.updateNodeAttribute(other, 'active', () => true)
          activeRef.current.push(other)
        }
      })
      sigma.refresh()
      const a = G.getNodeAttributes(node)
      const v = sigma.graphToViewport({ x: a.x, y: a.y })
      const n = infoRef.current.get(node)
      if (n) {
        setHover({ node: n, x: v.x, y: v.y })
        graphLog('hover:enter', { node, name: n.name })
      }
      setEdgeHover(null)
    }

    const onLeave = () => {
      clearTimeout(leaveTimerRef.current)
      leaveTimerRef.current = window.setTimeout(() => {
        if (cardHoverRef.current) return
        setHover(null)
        clearActive()
      }, HOVER_LINGER_MS)
    }

    sigma.on('enterNode', onEnter)
    sigma.on('leaveNode', onLeave)
    return () => {
      sigma.off('enterNode', onEnter)
      sigma.off('leaveNode', onLeave)
      clearTimeout(leaveTimerRef.current)
    }
  }, [graph, clearActive])

  // ------------------------------------------------------------ 浮窗跟随（鼠标位置，右下定住）
  useEffect(() => {
    const box = boxRef.current
    if (!box || !hover) return
    let raf = 0
    let last = { x: 0, y: 0 }
    const onMove = (ev: PointerEvent) => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = 0
        const cur = { x: ev.clientX, y: ev.clientY }
        const moving = cur.x !== last.x || cur.y !== last.y
        const cardOnLeft = cur.x + 14 + 440 > window.innerWidth
        const toward = moving && (cardOnLeft ? cur.x <= last.x : cur.x >= last.x)
        last = cur
        // 朝浮窗方向 ⇒ 定住；其余方向 ⇒ 跟随
        if (!toward) {
          setHover((h) => h ? { ...h, x: cur.x, y: cur.y } : h)
        }
      })
    }
    window.addEventListener('pointermove', onMove)
    return () => { window.removeEventListener('pointermove', onMove); if (raf) cancelAnimationFrame(raf) }
  }, [!!hover])

  // ------------------------------------------------------------ 环形按钮跟随节点
  useEffect(() => {
    if (!ring) return
    let raf = 0
    const tick = () => {
      const sigma = sigmaRef.current
      const G = graphRef.current
      const el = ringRef.current
      if (!G?.hasNode(ring.id)) { setRing(null); return }
      if (sigma && G && el) {
        const a = G.getNodeAttributes(ring.id)
        const v = sigma.graphToViewport({ x: a.x, y: a.y })
        const z = Math.max(1, Math.min(1 / sigma.getCamera().getState().ratio, 1.6))
        el.style.left = `${v.x}px`
        el.style.top = `${v.y}px`
        el.style.transform = `translate(-50%, -50%) scale(${z})`
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [ring?.id])

  // ------------------------------------------------------------ 标签疏密
  useEffect(() => {
    const sigma = sigmaRef.current
    const G = graphRef.current
    if (!sigma || !G || (graph?.nodes.length ?? 0) < LABEL_MIN_NODES) return
    const full = new Map((graph?.nodes ?? []).map((n) => [String(n.vid), truncate(n.name, labelMax(n))]))
    let dense: boolean | null = null
    const apply = () => {
      const d = 1 / sigma.getCamera().getState().ratio < LABEL_ZOOM_THRESHOLD
      if (d === dense) return
      dense = d
      const keep = new Set<string>()
      if (d) {
        const deg: [string, number][] = []
        G.forEachNode((id) => deg.push([id, G.degree(id)]))
        deg.sort((a, b) => b[1] - a[1])
        deg.slice(0, LABEL_TOP_DEGREE).forEach(([id]) => keep.add(id))
        if (selectedVid != null) {
          keep.add(String(selectedVid))
          G.forEachEdge(String(selectedVid), (e) => {
            const [s, t] = G.extremities(e)
            keep.add(s === String(selectedVid) ? t : s)
          })
        }
      }
      G.forEachNode((id) => G.updateNodeAttribute(id, 'hideLabel', () => d && !keep.has(id)))
      sigma.refresh()
    }
    sigma.getCamera().on('updated', apply)
    apply()
    return () => { sigma.getCamera().off('updated', apply) }
  }, [graph, selectedVid])

  // ------------------------------------------------------------ 尺寸变化
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const ro = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        const sigma = sigmaRef.current
        if (!sigma || !box.clientWidth || !box.clientHeight) return
        sigma.resize()
        sigma.refresh()
      })
    })
    ro.observe(box)
    return () => ro.disconnect()
  }, [])

  // ------------------------------------------------------------ 聚焦
  useEffect(() => {
    if (focusVid == null) return
    const sigma = sigmaRef.current
    const G = graphRef.current
    if (!sigma || !G?.hasNode(String(focusVid))) return
    const a = G.getNodeAttributes(String(focusVid))
    sigma.getCamera().animate({ x: a.x, y: a.y }, { duration: 300 })
  }, [focusVid])

  // ------------------------------------------------------------ 流星
  useEffect(() => {
    const box = boxRef.current
    if (!box || !graph || !meteors) return
    let stop: (() => void) | null = null
    let timer = 0
    let cancelled = false
    const wait = () => {
      if (cancelled) return
      if (!readyRef.current) { timer = window.setTimeout(wait, 150); return }
      const sigma = sigmaRef.current
      const G = graphRef.current
      if (!sigma || !G) return
      const edges = G.edges().map((e) => {
        const [f, t] = G.extremities(e)
        return {
          from: f, to: t,
          size: Number(G.getNodeAttribute(f, 'size')) || 14,
          color: String(G.getNodeAttribute(f, 'color') || '#94a3b8'),
          toSize: Number(G.getNodeAttribute(t, 'size')) || 14,
        }
      })
      stop = startMeteor(sigma, G, box, edges, { speed: meteorSpeed, sizeRatio: meteorSizeRatio })
      onPhase?.('流星已启动')
    }
    wait()
    return () => { cancelled = true; clearTimeout(timer); stop?.() }
  }, [graph, meteors, meteorSpeed, meteorSizeRatio, dataVersion])

  // ------------------------------------------------------------ 展开邻居
  const expandNeighbors = (id: string) => {
    const G = graphRef.current
    const src = fullGraph
    const sigma = sigmaRef.current
    if (!G || !src || !sigma) return
    const existing = new Set(G.nodes())
    const byId = new Map(src.nodes.map((n) => [String(n.vid), n]))
    const nbrs = new Set<string>()
    for (const e of src.edges) {
      if (String(e.from) === id) nbrs.add(String(e.to))
      if (String(e.to) === id) nbrs.add(String(e.from))
    }
    const missing = [...nbrs].filter((v) => !existing.has(v) && byId.has(v))
    graphLog('expand', { host: id, neighbors: nbrs.size, adding: missing.length })
    if (!missing.length) return

    const base = G.getNodeAttributes(id)
    missing.forEach((v, i) => {
      const n = byId.get(v)!
      const ang = (Math.PI * 2 * i) / missing.length - Math.PI / 2
      G.addNode(v, nodeAttrs(n, base.x + Math.cos(ang) * 1.2, base.y + Math.sin(ang) * 1.2, nodeSizePx, labelColor))
      infoRef.current.set(v, n)
    })
    for (const e of src.edges) {
      const f = String(e.from), t = String(e.to)
      if ((missing.includes(f) || existing.has(f)) && (missing.includes(t) || existing.has(t)) &&
          (missing.includes(f) || missing.includes(t)) && !G.hasEdge(f, t)) {
        G.addEdge(f, t, edgeAttrs(e, byId.get(f)))
      }
    }
    sigma.refresh()
    setDataVersion((v) => v + 1)
    onGraphChanged?.()
  }

  // ------------------------------------------------------------ 隐藏节点
  const hideNode = (id: string) => {
    const G = graphRef.current
    const sigma = sigmaRef.current
    if (!G || !sigma) return
    const removing = new Set<string>([id])
    G.forEachEdge(id, (e) => {
      const [s, t] = G.extremities(e)
      const other = s === id ? t : s
      if (G.degree(other) === 1) removing.add(other)
    })
    const before = G.order
    for (const e of G.edges()) {
      const [s, t] = G.extremities(e)
      if (removing.has(s) || removing.has(t)) G.dropEdge(e)
    }
    for (const v of removing) if (G.hasNode(v)) G.dropNode(v)
    removing.forEach((v) => infoRef.current.delete(v))
    graphLog('hide', { target: id, dropped: before - G.order })
    sigma.refresh()
    setDataVersion((v) => v + 1)
    setRing(null)
    if (selectedVid != null && removing.has(String(selectedVid))) onDeselect?.()
    onGraphChanged?.()
  }

  // ------------------------------------------------------------ 渲染
  const segments = [
    { key: 'expand', title: '显示邻居', a1: -Math.PI / 2 + 0.18, a2: Math.PI / 2 - 0.18, icon: 'M12 5v14M5 12h14', run: expandNeighbors },
    { key: 'hide', title: '隐藏节点及其邻居', a1: Math.PI / 2 + 0.18, a2: Math.PI * 1.5 - 0.18, icon: 'M2 2l20 20M2 22L22 2', run: hideNode },
  ]

  return (
    <div
      ref={boxRef}
      style={{ width: '100%', height: '100%', position: 'relative', pointerEvents: aiBusy ? 'none' : 'auto' }}
    >
      <div ref={sigmaHostRef} style={{ position: 'absolute', inset: 0 }} />

      {ring && (
        <svg
          ref={ringRef}
          className="node-ring"
          style={{ position: 'absolute', left: ring.x, top: ring.y, width: 96, height: 96, transform: `translate(-50%, -50%) scale(${ringScale})`, zIndex: 20 }}
        >
          {segments.map((s) => (
            <g key={s.key}>
              <path d={ringArcPath(s.a1, s.a2)} fill="var(--accent)" opacity={0.9} style={{ cursor: 'pointer' }}
                onClick={(e) => { e.stopPropagation(); s.run(ring.id) }}>
                <title>{s.title}</title>
              </path>
              <path d={s.icon} fill="none" stroke="#fff" strokeWidth={2} style={{ pointerEvents: 'none' }}
                transform="translate(36 36) scale(0.55)" />
            </g>
          ))}
        </svg>
      )}

      {hover && (
        <NodeHoverCard
          node={hover.node}
          x={hover.x}
          y={hover.y}
          onEnter={() => { cardHoverRef.current = true; clearTimeout(leaveTimerRef.current) }}
          onLeave={() => { cardHoverRef.current = false; setHover(null); clearActive() }}
        />
      )}
      {edgeHover && <EdgeHoverCard edge={edgeHover.edge} x={edgeHover.x} y={edgeHover.y} />}
    </div>
  )
}
