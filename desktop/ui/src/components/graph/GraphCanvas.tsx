import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Sigma from 'sigma'
import { NodeCircleProgram, EdgeDoubleClampedProgram } from 'sigma/rendering'
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
/** 点到线段的像素距离（边命中检测用） */
function distToSeg(
  px: number, py: number,
  ax: number, ay: number,
  bx: number, by: number,
): number {
  const dx = bx - ax, dy = by - ay
  const l2 = dx * dx + dy * dy
  if (!l2) return Math.hypot(px - ax, py - ay)
  let t = ((px - ax) * dx + (py - ay) * dy) / l2
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

function edgeAttrs(e: GraphEdge, src: GraphNode | undefined) {
  return {
    // ★★ 记住原始边 id：graphology 的 addEdge 不给 key 就自动生成 "geid_N"，
    //   sigma 的 clickEdge/enterEdge 给的是那个自动 id ⇒
    //   ⛔ 直接拿去 graph.edges 里找 String(e.id) 永远找不到（点边没反应）。
    origId: String(e.id),
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
  const cleanupRef = useRef<(() => void) | null>(null)
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
  /** 边详情弹窗的延迟清除定时器 */
  const edgeLeaveRef = useRef(0)
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

  // ------------------------------------------------------------ 建图（graph 变时才重建）
  // ★ 页面层已修 shownCount 竞争（深链时不再先设 initialBatch），
  //   所以这里 graph 只变一次 ⇒ 只建一次图。⛔ 不需要防抖补丁。
  useEffect(() => {
    buildGraph()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph])

  /** 真正的建图逻辑（用最新 props） */
  function buildGraph() {
    const box = boxRef.current
    const host = sigmaHostRef.current
    if (!box || !host || !graph) return

    const W = box.clientWidth || 900
    const H = box.clientHeight || 600
    graphLog('build:start', { nodes: graph.nodes.length, edges: graph.edges.length, W, H })

    // ★★ 先 kill 旧实例（清空 sigmaHost），⛔ 必须在新 Sigma 之前 ——
    //   否则 kill 会把刚创建的 canvas 一起删掉（一闪而过）⚠
    const prev = sigmaRef.current
    if (prev) {
      cleanupRef.current?.()
      cleanupRef.current = null
    }

    const G = new DirectedGraph({ type: 'directed' })
    graph.nodes.forEach((n, i) => {
      // ★★★ 初始位置用**黄金角螺旋**，⛔ 不用「i/N * 2π」均匀圆周 ——
      //   后者在 2 个节点时正好是 0 和 π（都在 y=0），FA2 因对称永远散不开，
      //   结果 bh=0 ⇒ sigma 归一化 y 方向除零 ⇒ 节点全在视口外（实测 ogy 日志）。
      //   黄金角保证任意节点数都不共线。
      const ang = i * 2.399963229728653
      const r = RING * Math.sqrt(i + 1)
      G.addNode(String(n.vid), nodeAttrs(n, Math.cos(ang) * r, Math.sin(ang) * r, nodeSizePx, labelColor))
    })
    graph.edges.forEach((e) => {
      if (!G.hasNode(String(e.from)) || !G.hasNode(String(e.to))) return
      G.addEdge(String(e.from), String(e.to), edgeAttrs(e, nodeById.get(String(e.from))))
    })
    infoRef.current = new Map(graph.nodes.map((n) => [String(n.vid), n]))

    const sigma = new Sigma(G, host, {
      nodeProgramClasses: { circle: NodeCircleProgram },
      // ★★★ 用**双端裁剪**的箭头程序：
      //   sigma 的 EdgeArrowProgram = [clamped 线, arrowHead]，而 clamped 只裁
      //   **终点**（源码：var radius = targetData.size）⇒ 起点端直插节点中心
      //   （所有者：「边直接到节点中心了？」）。EdgeDoubleClampedProgram 两端都裁。⚠
      edgeProgramClasses: { arrow: EdgeDoubleClampedProgram },
      defaultNodeType: 'circle',
      defaultEdgeType: 'arrow',
      labelColor: { attribute: 'labelColor', color: '#94a3b8' },
      labelRenderedSizeThreshold: 0,
      renderEdgeLabels: false,
      // ★★★ 标签画在**节点下方居中**（sigma 默认画在右侧 + hover 白底框）：
      //   所有者原话：「节点名字应该在节点下面，不是右边」
      defaultDrawNodeLabel: (context, data, settings) => {
        if (!data.label) return
        const size = settings.labelSize
        const lc = settings.labelColor
        const attr = 'attribute' in lc ? lc.attribute : undefined
        const color = (attr ? (data as Record<string, unknown>)[attr] : undefined)
          || lc.color || '#000'
        context.fillStyle = String(color)
        context.font = `${settings.labelWeight} ${size}px ${settings.labelFont}`
        // ★ 水平居中：x - 文本宽度/2；垂直：节点底部 + 一行
        const w = context.measureText(String(data.label)).width
        context.fillText(String(data.label), data.x - w / 2, data.y + data.size + size + 2)
      },
      // ★ hover 不再画右侧白底标签框（改为我们自己画在下方 + HTML 浮窗）
      defaultDrawNodeHover: (context, data, settings) => {
        if (!data.label) return
        const size = settings.labelSize
        const lc = settings.labelColor
        const attr = 'attribute' in lc ? lc.attribute : undefined
        const color = (attr ? (data as Record<string, unknown>)[attr] : undefined)
          || lc.color || '#000'
        context.fillStyle = String(color)
        context.font = `${settings.labelWeight} ${size}px ${settings.labelFont}`
        const w = context.measureText(String(data.label)).width
        context.fillText(String(data.label), data.x - w / 2, data.y + data.size + size + 2)
      },
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

    // ★★★ 布局动画：**先同步算出最终布局并记录快照，再按 1.5 秒回放**
    //
    //   ⚠ 为什么不直接「每帧跑几次 FA2」：
    //   sigma 每次 refresh 都按**当前 bbox** 归一化（createNormalizationFunction），
    //   节点坐标变大 ⇒ bbox 同步变大 ⇒ 归一化后始终铺满视口
    //   ⇒ 视觉上根本看不出「散开」，只有位置抖动（所有者实测看不到动画）。
    //   解法：setCustomBBox() 把归一化基准**固定成最终布局范围**，
    //   再让坐标从中心小圆环逐渐长到最终位置 —— 这才是真的散开。
    const t0 = performance.now()
    const TOTAL_ITER = 120
    const FRAMES = 90            // 快照帧数
    const DURATION_MS = 1500     // ★ 动画总时长（所有者要 1-2 秒）
    const settings = forceAtlas2.inferSettings(G)
    let raf = 0
    let finished = false

    /** 记录当前所有节点坐标 */
    const snap = () => {
      const out: { id: string; x: number; y: number }[] = []
      G.forEachNode((id, a) => out.push({ id, x: a.x, y: a.y }))
      return out
    }
    /** 应用一帧坐标 */
    const applyFrame = (f: { id: string; x: number; y: number }[]) => {
      for (const p of f) {
        if (!G.hasNode(p.id)) continue
        G.setNodeAttribute(p.id, 'x', p.x)
        G.setNodeAttribute(p.id, 'y', p.y)
      }
    }
    /** 算 bbox */
    const bboxOf = (f: { id: string; x: number; y: number }[]) => {
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
      for (const p of f) {
        if (p.x < minX) minX = p.x
        if (p.x > maxX) maxX = p.x
        if (p.y < minY) minY = p.y
        if (p.y > maxY) maxY = p.y
      }
      return { minX, maxX, minY, maxY }
    }

    // ① 同步跑完布局，逐帧记录快照
    const snapshots: { id: string; x: number; y: number }[][] = [snap()]
    const per = Math.max(1, Math.round(TOTAL_ITER / FRAMES))
    for (let i = 0; i < FRAMES; i++) {
      try {
        forceAtlas2.assign(G, { iterations: per, settings })
      } catch (e) {
        graphLog('layout:ERROR', { err: String(e) })
        break
      }
      snapshots.push(snap())
    }
    const finalFrame = snapshots[snapshots.length - 1]
    let bb = bboxOf(finalFrame)

    // ★ 退化保护：某一维接近 0（节点共线/只有一个节点）时撑开，
    //   ⛔ 否则 sigma 归一化除零 ⇒ 节点全在视口外（实测 2 节点 bh=0）。
    {
      const w0 = bb.maxX - bb.minX
      const h0 = bb.maxY - bb.minY
      if (w0 < 0.5 || h0 < 0.5) {
        const base = Math.max(w0, h0, 1)
        finalFrame.forEach((p, idx) => {
          if (w0 < 0.5) p.x = Math.cos(idx * 2.399963) * base * 0.6
          if (h0 < 0.5) p.y = Math.sin(idx * 2.399963) * base * 0.6
        })
        bb = bboxOf(finalFrame)
        graphLog('layout:degenerate-fixed', { w0: n1(w0), h0: n1(h0) })
      }
    }
    graphLog('diag:bbox', {
      minX: n1(bb.minX), maxX: n1(bb.maxX), minY: n1(bb.minY), maxY: n1(bb.maxY),
      bw: n1(bb.maxX - bb.minX), bh: n1(bb.maxY - bb.minY),
      frames: snapshots.length, durationMs: DURATION_MS,
    })

    // ② 固定归一化基准 = 最终布局范围 ⇒ 动画期间不会被自动缩放吃掉
    sigma.setCustomBBox({ x: [bb.minX, bb.maxX], y: [bb.minY, bb.maxY] })
    sigma.getCamera().setState({ x: 0.5, y: 0.5, ratio: 1.08 })

    // ③ 从第一帧开始回放
    applyFrame(snapshots[0])
    sigma.refresh()

    const playStart = performance.now()
    const play = () => {
      if (sigmaRef.current !== sigma || finished) return
      const t = Math.min(1, (performance.now() - playStart) / DURATION_MS)
      const idx = Math.min(snapshots.length - 1, Math.round(t * (snapshots.length - 1)))
      applyFrame(snapshots[idx])
      sigma.refresh()
      if (t < 1) {
        raf = requestAnimationFrame(play)
      } else {
        finished = true
        graphLog('layout:done', { ms: Math.round(performance.now() - t0), frames: snapshots.length })
        // ④ 结束：恢复自动归一化（此刻实际 bbox == customBBox，不会跳）
        sigma.setCustomBBox(null)
        sigma.getCamera().animate({ ratio: 1.08, x: 0.5, y: 0.5 }, { duration: 200 })
        readyRef.current = Date.now()
        graphLog('ready', { nodes: G.order })
        onPhase?.('布局完成')
      }
    }
    raf = requestAnimationFrame(play)
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

    // ★ 边的交互走「鼠标到线段距离」的手动检测（见下面的 effect）——
    //   ⛔ 不用 sigma 的 enterEdge/clickEdge：像素级精确命中，1px 线宽几乎点不中。

    // ★★ 节点拖拽：sigma 3 没有内置 drag-element（G6 有），手动实现
    //   downNode 抓住节点 → 禁用相机（否则会同时拖画布）→ 移动时改坐标 → 松开恢复
    let dragging: string | null = null
    sigma.on('downNode', ({ node }: { node: string }) => {
      if (!readyRef.current) return   // 布局动画期间不拖
      dragging = node
      sigma.getCamera().disable()
    })
    sigma.getMouseCaptor().on('mouseup', () => {
      if (!dragging) return
      dragging = null
      sigma.getCamera().enable()
    })
    sigma.getMouseCaptor().on('mousemovebody', (e) => {
      if (!dragging) return
      const GG = graphRef.current
      if (!GG || !GG.hasNode(dragging)) return
      const p = sigma.viewportToGraph({ x: e.x, y: e.y })
      GG.setNodeAttribute(dragging, 'x', p.x)
      GG.setNodeAttribute(dragging, 'y', p.y)
      sigma.refresh()
    })

    // 把新实例的清理函数存起来，供 unmount / 下一次 build 调用
    cleanupRef.current = () => {
      cancelAnimationFrame(raf)
      clearTimeout(settle)
      window.clearTimeout(edgeLeaveRef.current)
      sigmaRef.current = null
      graphRef.current = null
      readyRef.current = 0
      sigma.kill()
    }
  }

  // 组件卸载：清理当前 sigma 实例
  useEffect(() => () => cleanupRef.current?.(), [])

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
      // ★ graphToViewport 是**相对 canvas** 的坐标；浮窗用 position:fixed
      //   ⇒ 必须加上画布在页面里的偏移，否则卡片位置会偏掉 ⚠
      const rect = boxRef.current?.getBoundingClientRect()
      const n = infoRef.current.get(node)
      if (n) {
        setHover({
          node: n,
          x: v.x + (rect?.left ?? 0),
          y: v.y + (rect?.top ?? 0),
        })
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

  // ------------------------------------------------------------ 浮窗锚点：固定在节点右下（露出节点）
  // ★★ ⛔ 不再把 hover 坐标换成鼠标位置 ——
  //   那会让卡片贴着鼠标（鼠标在节点上时正好盖住节点）。
  //   现在锚点恒为**节点中心**，由 NodeHoverCard 向右下偏移，
  //   节点（半径 7px）始终露出来，鼠标斜向右下即可移到卡片上 ⚠
  useEffect(() => {
    // 鼠标离开画布 ⇒ 走 800ms 滞留（在 hover effect 里处理）
    // 这里不再改坐标，保持节点锚点稳定
  }, [!!hover])

  // ------------------------------------------------------------ 边命中：鼠标离线段 ≤8px 就显示详情
  // ★★★ 为什么不用 sigma 的 enterEdge/clickEdge：
  //   sigma 的边拾取是**像素级精确命中**（线宽 1px）⇒ 几乎点不中，
  //   所有者实测「点击没有显示边信息弹窗」。
  //   ⇒ 自己算「鼠标到线段的像素距离 ≤ 8px」，和原来 G6 版本一致。
  useEffect(() => {
    const box = boxRef.current
    if (!box || !graph) return
    graphLog('edge:effect', { edges: graph.edges.length, nodes: graph.nodes.length })
    let raf = 0
    let last: { x: number; y: number } | null = null
    let lastReport = 0
    let lastHit = ''

    const update = () => {
      raf = 0
      const sigma = sigmaRef.current
      const G = graphRef.current
      if (!sigma || !G || !last) return
      const rect = box.getBoundingClientRect()
      const mx = last.x - rect.left
      const my = last.y - rect.top
      if (mx < 0 || my < 0 || mx > rect.width || my > rect.height) return

      // ★★★ 节点优先：鼠标压在节点上时**不显示边弹窗**
      //   节点就在边的端点上，鼠标在节点上时到那条边的距离必然 ≤ 阈值，
      //   ⛔ 不挡的话两个弹窗会一起冒出来（所有者反馈）。
      {
        let onNode = false
        for (const id of G.nodes()) {
          const a = G.getNodeAttributes(id)
          const v = sigma.graphToViewport({ x: a.x, y: a.y })
          const r = Number(a.size || 14) / 2 + 4
          if (Math.hypot(mx - v.x, my - v.y) <= r) { onNode = true; break }
        }
        if (onNode) {
          if (!edgeLeaveRef.current) {
            edgeLeaveRef.current = window.setTimeout(() => {
              edgeLeaveRef.current = 0
              setEdgeHover(null)
            }, 100)
          }
          return
        }
      }

      let best: GraphEdge | null = null
      let bestD = Infinity
      let skipped = 0
      for (const e of graph.edges) {
        const f = String(e.from), t = String(e.to)
        if (!G.hasNode(f) || !G.hasNode(t)) { skipped++; continue }
        const av = G.getNodeAttributes(f)
        const bv = G.getNodeAttributes(t)
        const pa = sigma.graphToViewport({ x: av.x, y: av.y })
        const pb = sigma.graphToViewport({ x: bv.x, y: bv.y })
        const d = distToSeg(mx, my, pa.x, pa.y, pb.x, pb.y)
        if (d < bestD) { bestD = d; best = e }
      }

      if (best && bestD <= 12) {
        const key = String(best.id)
        if (lastHit !== key) {
          lastHit = key
          graphLog('edge:hit', { id: key, dist: n1(bestD) })
        }
        window.clearTimeout(edgeLeaveRef.current)
        edgeLeaveRef.current = 0
        setEdgeHover({ edge: best, x: last.x, y: last.y })
      } else {
        // ★ 每 2 秒报一次「扫描结果」，确认检测在跑、距离大概多少
        const now = Date.now()
        if (now - lastReport > 2000) {
          lastReport = now
          lastHit = ''
          graphLog('edge:scan', {
            minDist: best ? n1(bestD) : -1,
            edges: graph.edges.length,
            skipped,
            mouse: { x: n1(mx), y: n1(my) },
            canvas: `${Math.round(rect.width)}×${Math.round(rect.height)}`,
          })
        }
        if (!edgeLeaveRef.current) {
          // 离开边 ⇒ 200ms 后清（给眼睛一点时间）
          edgeLeaveRef.current = window.setTimeout(() => {
            edgeLeaveRef.current = 0
            setEdgeHover(null)
          }, 200)
        }
      }
    }

    const onMove = (ev: PointerEvent) => {
      last = { x: ev.clientX, y: ev.clientY }
      if (!raf) raf = requestAnimationFrame(update)
    }
    box.addEventListener('pointermove', onMove)
    return () => {
      box.removeEventListener('pointermove', onMove)
      if (raf) cancelAnimationFrame(raf)
      window.clearTimeout(edgeLeaveRef.current)
      edgeLeaveRef.current = 0
    }
  }, [graph])

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
    // ★ camera.x/y 是归一化坐标：normalized = 0.5 + (raw - bboxCenter)/bboxSize
    //   ⛔ 不能直接传原始坐标（会把视口甩到图外）
    const xs: number[] = [], ys: number[] = []
    G.forEachNode((_id, at) => { xs.push(at.x); ys.push(at.y) })
    if (!xs.length) return
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const size = Math.max(maxX - minX, maxY - minY) || 1
    const nx = 0.5 + ((G.getNodeAttribute(String(focusVid), 'x') - (minX + maxX) / 2) / size)
    const ny = 0.5 + ((G.getNodeAttribute(String(focusVid), 'y') - (minY + maxY) / 2) / size)
    sigma.getCamera().animate({ x: nx, y: ny }, { duration: 300 })
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
