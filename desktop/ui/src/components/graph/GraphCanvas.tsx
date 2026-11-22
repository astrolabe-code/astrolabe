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
      // ★★★ sigma 的 camera.x/y 是**归一化坐标**（见 createNormalizationFunction）：
      //     normalized = 0.5 + (raw - bboxCenter) / bboxSize
      //   ⇒ 归一化后 bbox 中心**恒为 (0.5, 0.5)**，与原始坐标无关。
      //   ⛔ 之前传原始 bbox 中心（如 -3.3），等于把视口移出图外
      //     ⇒ 图跑到右边、只露半截（所有者截图）。
      //   ratio=1 即「图撑满视口」，留 8% 边距用 1.08。
      sigma.getCamera().animate(
        { ratio: 1.08, x: 0.5, y: 0.5 },
        { duration: 250 },   // ★ 只 fit 一次，平滑收尾
      )
    }

    const tick = () => {
      if (sigmaRef.current !== sigma || finished) return
      try {
        forceAtlas2.assign(G, { iterations: ITER_PER_FRAME, settings })
        doneIter += ITER_PER_FRAME
        // ★ 动画期间 camera 不动（归一化中心恒为 0.5,0.5，图自然居中）：
        //   只把 ratio 阻尼收敛到 1.08，避免初始 ratio=1 与目标的细微跳变。
        {
          const cur = sigma.getCamera().getState()
          sigma.getCamera().setState({
            x: 0.5,
            y: 0.5,
            ratio: cur.ratio + (1.08 - cur.ratio) * 0.15,
          })
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

        // ★★★ 退化保护：某一维 bbox 接近 0（节点共线/只有一个节点）时，
        //   手动在那一维上撑开 —— ⛔ 否则 sigma 归一化会除零，
        //   节点全被映射到视口外（实测：2 节点 bh=0 ⇒ y=-68.9）。
        {
          const xs0: number[] = [], ys0: number[] = []
          G.forEachNode((_id, a) => { xs0.push(a.x); ys0.push(a.y) })
          const w0 = Math.max(...xs0) - Math.min(...xs0)
          const h0 = Math.max(...ys0) - Math.min(...ys0)
          if (w0 < 0.5 || h0 < 0.5) {
            // 沿退化维度按黄金角铺开，幅度取另一维的 0.6（都退化就用 1）
            const base = Math.max(w0, h0, 1)
            G.nodes().forEach((id, i) => {
              if (w0 < 0.5) G.updateNodeAttribute(id, 'x', () => Math.cos(i * 2.399963) * base * 0.6)
              if (h0 < 0.5) G.updateNodeAttribute(id, 'y', () => Math.sin(i * 2.399963) * base * 0.6)
            })
            graphLog('layout:degenerate-fixed', { w0: n1(w0), h0: n1(h0) })
          }
        }

        // ★★★ 诊断：布局结束时的原始数据（fit 之前）
        const xs2: number[] = [], ys2: number[] = []
        G.forEachNode((_id, a) => { xs2.push(a.x); ys2.push(a.y) })
        const bMinX = Math.min(...xs2), bMaxX = Math.max(...xs2)
        const bMinY = Math.min(...ys2), bMaxY = Math.max(...ys2)
        const bbw = bMaxX - bMinX, bbh = bMaxY - bMinY
        const zCalc = Math.min((W - 120) / Math.max(1, bbw), (H - 120) / Math.max(1, bbh))
        const dimNow = sigma.getDimensions()
        graphLog('diag:bbox', {
          minX: n1(bMinX), maxX: n1(bMaxX), minY: n1(bMinY), maxY: n1(bMaxY),
          bw: n1(bbw), bh: n1(bbh),
          canvas: `${dimNow.width}×${dimNow.height}`,
          zCalc: n1(zCalc), ratioCalc: n1(1 / Math.max(0.001, zCalc)),
        })

        fitOnce()         // ★ 结束后 fit 一次（GitNexus 的 fit:true）

        // ★★★ 诊断：fit 之后（等动画 300ms 再读真值）
        window.setTimeout(() => {
          if (sigmaRef.current !== sigma) return
          const cam = sigma.getCamera().getState()
          // 取第一个节点，看它落在屏幕哪里（应该在 0~W / 0~H 内）
          const firstId = G.nodes()[0]
          const fa = G.getNodeAttributes(firstId)
          const vp = sigma.graphToViewport({ x: fa.x, y: fa.y })
          // WebGL 信息（判断是不是渲染层问题）
          let gl = ''
          try {
            const c = (host.querySelector('canvas') as HTMLCanvasElement | null)
            const ctx = c?.getContext('webgl2') || c?.getContext('webgl')
            if (ctx) {
              const dbg = (ctx as WebGLRenderingContext).getExtension('WEBGL_debug_renderer_info')
              gl = dbg
                ? String((ctx as WebGLRenderingContext).getParameter(dbg.UNMASKED_RENDERER_WEBGL))
                : 'webgl-ok(no-debug-info)'
            } else gl = 'NO-WEBGL-CONTEXT'
          } catch (e) { gl = 'err:' + String(e) }
          graphLog('diag:camera', {
            camX: n1(cam.x), camY: n1(cam.y), camRatio: cam.ratio,
            nodeGraph: { x: n1(fa.x), y: n1(fa.y) },
            nodeViewport: { x: n1(vp.x), y: n1(vp.y) },
            inViewport: vp.x >= 0 && vp.x <= dimNow.width && vp.y >= 0 && vp.y <= dimNow.height,
            webgl: gl,
          })
        }, 320)

        readyRef.current = Date.now()
        const dim = sigma.getDimensions()
        graphLog('ready', { nodes: G.order, canvas: `${dim.width}×${dim.height}` })
        onPhase?.('布局完成')
      }
    }

    // ★ 初始 camera 对准初始圆环中心（节点散开时不用移动视口）
    // ★ 归一化中心恒为 (0.5, 0.5)；初始就用居中 + fit 的 ratio
    sigma.getCamera().setState({ x: 0.5, y: 0.5, ratio: 1.08 })
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

    // 把新实例的清理函数存起来，供 unmount / 下一次 build 调用
    cleanupRef.current = () => {
      cancelAnimationFrame(raf)
      clearTimeout(settle)
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
