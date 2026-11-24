import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { select, type Selection } from 'd3-selection'
import {
  forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide,
  type Simulation, type SimulationNodeDatum, type SimulationLinkDatum,
} from 'd3-force'
import { zoom as d3zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from 'd3-zoom'
import { drag as d3drag } from 'd3-drag'
import 'd3-transition'   // ★ 侧加载：给 selection 挂 .transition()
import { startMeteor } from '../../lib/meteorFx'
import { graphLog, n1 } from '../../lib/graphLog'
import type { EffectiveGraph, GraphEdge, GraphNode } from '../../lib/mergeGraph'
import { kindColor } from '../../lib/kindLabel'
import NodeHoverCard from '../node/NodeHoverCard'
import { useAiBusy } from '../../lib/aiBusy'
import EdgeHoverCard from './EdgeHoverCard'

/**
 * ★★ 图谱画布（D3 + SVG，2026-11-24 重写）
 *
 * 为什么换掉 sigma.js：
 *   · sigma 的 camera 是**归一化坐标**（bbox 中心恒为 0.5,0.5）、ratio 语义反直觉，
 *     调一次要翻源码；边裁剪只裁终点；边拾取是 1px WebGL picking，几乎点不中。
 *   · 本场景只展示几十~几百个节点（全量在库里用 Cypher 查），
 *     SVG 完全够用，而且 hover / 拖拽 / 边拾取都是 DOM 原生事件，代码少一半。
 *
 * 设计：
 *   1. **d3 全权管理 SVG 内容**（React 只渲染容器 + HTML 浮层），
 *      避免 React re-render 覆盖 d3 写入的坐标。
 *   2. 坐标就是 SVG 像素坐标；缩放/平移由 d3-zoom 的 transform 应用到 <g>，
 *      `toScreen()` 一行完成图坐标 → 屏幕坐标。
 *   3. 布局动画 = d3-force 的 tick，天然平滑（不需要 setCustomBBox 那套）。
 */

// ---------------------------------------------------------------- 常量

const LABEL_MAX_NAME = 16
const LABEL_MAX_FILE = 22
const HOVER_LINGER_MS = 800
const RING_GEO = { c: 48, r1: 24, r2: 42 }
const LABEL_ZOOM_THRESHOLD = 0.7
const LABEL_MIN_NODES = 30
const LABEL_TOP_DEGREE = 12
const EDGE_HIT_WIDTH = 12          // 边的透明命中宽度（SVG 里白拿的宽容度）
const EDGE_DIST_PX = 10            // 手动边检测阈值（兜底）

const truncate = (s: string, max: number) => {
  const t = (s || '').trim()
  return t.length > max ? `${t.slice(0, max)}…` : t
}
const labelMax = (n: GraphNode) =>
  n.kind === 'file' || n.kind === 'dir' ? LABEL_MAX_FILE : LABEL_MAX_NAME
const colorOf = (n: GraphNode) => kindColor(n.kind)

/**
 * 环形按钮的缩放：
 *   基准 = 节点半径 7px（= nodeSizePx 14 的一半）
 *   再乘 zoom（限制 0.85~2，避免缩到看不见或撑爆屏幕）
 */
const RING_BASE_R = 7
function ringScaleFor(nodeR: number, zoomK: number): number {
  const byNode = (nodeR || RING_BASE_R) / RING_BASE_R
  const byZoom = Math.max(0.85, Math.min(zoomK, 2))
  return byNode * byZoom
}

function ringArcPath(a1: number, a2: number): string {
  const { c, r1, r2 } = RING_GEO
  const pt = (r: number, a: number) => [c + r * Math.cos(a), c + r * Math.sin(a)] as const
  const [x1, y1] = pt(r2, a1), [x2, y2] = pt(r2, a2)
  const [x3, y3] = pt(r1, a2), [x4, y4] = pt(r1, a1)
  const large = a2 - a1 > Math.PI ? 1 : 0
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r2} ${r2} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} L ${x3.toFixed(2)} ${y3.toFixed(2)} A ${r1} ${r1} 0 ${large} 0 ${x4.toFixed(2)} ${y4.toFixed(2)} Z`
}

// ---------------------------------------------------------------- 类型

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

interface SimNode extends SimulationNodeDatum {
  id: string
  node: GraphNode
  r: number
}
interface SimLink extends SimulationLinkDatum<SimNode> {
  id: string
  edge: GraphEdge
  source: string | SimNode
  target: string | SimNode
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
  meteors,
  meteorSpeed,
  meteorSizeRatio,
  nodeSizePx = 14,
}: GraphCanvasProps) {
  const boxRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const gRef = useRef<SVGGElement | null>(null)

  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  const tfRef = useRef<ZoomTransform>(zoomIdentity)
  const nodesRef = useRef<SimNode[]>([])
  const linksRef = useRef<SimLink[]>([])
  /** 记住节点位置（含拖拽固定坐标 fx/fy，重建时保留） */
  const posRef = useRef(new Map<string, { x: number; y: number; fx?: number | null; fy?: number | null }>())
  /**
   * ★★ 运行时增删（不改页面传来的 props.graph）：
   *   extra  = 「显示邻居」加进来的节点（数据从 fullGraph 取）
   *   hidden = 「隐藏节点」去掉的节点
   *   渲染时：nodes = (graph.nodes - hidden) ∪ (fullGraph 中属于 extra 的)
   *   展开/隐藏后通过 setDataVersion 触发重建。
   */
  const extraRef = useRef(new Set<string>())
  const hiddenRef = useRef(new Set<string>())
  /** 是否已首次建图：首次才做「居中 + 结束 fit」，之后重建保持当前视野 */
  const initedRef = useRef(false)
  /** 是否已经自动 fit 过一次 */
  const fittedRef = useRef(false)

  const [hover, setHover] = useState<{ node: GraphNode; x: number; y: number } | null>(null)
  const [edgeHover, setEdgeHover] = useState<{ edge: GraphEdge; x: number; y: number } | null>(null)
  const [ring, setRing] = useState<{ vid: number; x: number; y: number; r: number } | null>(null)
  const [ringScale, setRingScale] = useState(1)
  /** ring 的镜像：zoom 回调里读它，避免闭包拿到旧 state */
  const ringRef = useRef<{ vid: number; x: number; y: number; r: number } | null>(null)
  useEffect(() => { ringRef.current = ring }, [ring])
  const [dataVersion, setDataVersion] = useState(0)

  const aiBusy = useAiBusy()
  const leaveTimerRef = useRef(0)
  const edgeLeaveRef = useRef(0)
  const cardHoverRef = useRef(false)
  /** 当前 hover 高亮的节点集合（含邻居） */
  const activeSetRef = useRef<Set<string>>(new Set())

  /** 图坐标 → 屏幕坐标（d3-zoom 的 transform） */
  const toScreen = useCallback((x: number, y: number): [number, number] => {
    const t = tfRef.current
    return [x * t.k + t.x, y * t.k + t.y]
  }, [])

  // ============================================================ 主 effect：建 SVG + 布局
  useEffect(() => {
    const box = boxRef.current
    const svgEl = svgRef.current
    if (!box || !svgEl || !graph) return

    const W = box.clientWidth || 900
    const H = box.clientHeight || 600
    graphLog('build:start', { nodes: graph.nodes.length, edges: graph.edges.length, W, H })

    const r0 = Math.max(4, nodeSizePx / 2)

    // ① 当前可见节点 = props.nodes 去 hidden，再加 fullGraph 里的 extra
    const hidden = hiddenRef.current
    const extra = extraRef.current
    const visibleNodes: GraphNode[] = graph.nodes.filter((n) => !hidden.has(String(n.vid)))
    if (extra.size && fullGraph) {
      const have = new Set(visibleNodes.map((n) => String(n.vid)))
      for (const n of fullGraph.nodes) {
        const id = String(n.vid)
        if (extra.has(id) && !hidden.has(id) && !have.has(id)) visibleNodes.push(n)
      }
    }

    // ② 节点：优先复用旧坐标，否则黄金角螺旋（避免节点共线导致布局退化）
    const prev = posRef.current
    const nodes: SimNode[] = visibleNodes.map((n, i) => {
      const id = String(n.vid)
      const old = prev.get(id)
      const ang = i * 2.399963229728653
      const rad = 6 * Math.sqrt(i + 1)
      return {
        id,
        node: n,
        r: n.origin === 'manual' ? r0 * 1.15 : r0,
        x: old?.x ?? Math.cos(ang) * rad,
        y: old?.y ?? Math.sin(ang) * rad,
        // ★ 恢复用户手动摆放的固定位置（否则重建后又被力导向拉走）
        fx: old?.fx ?? undefined,
        fy: old?.fy ?? undefined,
      }
    })
    const byId = new Map(nodes.map((n) => [n.id, n]))

    // ③ 边：两端都可见才画（props.edges ∪ fullGraph.edges，去重）
    const links: SimLink[] = []
    const seenEdge = new Set<string>()
    const allEdges: GraphEdge[] = [...graph.edges, ...(fullGraph?.edges ?? [])]
    for (const e of allEdges) {
      const s = String(e.from), t = String(e.to)
      if (!byId.has(s) || !byId.has(t)) continue
      const k = String(e.id)
      if (seenEdge.has(k)) continue
      seenEdge.add(k)
      links.push({ id: k, edge: e, source: s, target: t })
    }
    graphLog('visible', {
      nodes: nodes.length, links: links.length,
      extra: extra.size, hidden: hidden.size,
    })

    nodesRef.current = nodes
    linksRef.current = links

    const svg = select(svgEl)
    // ★ 主动设尺寸：⛔ 只靠 ResizeObserver 的话首次回调是异步的，
    //   那一帧 SVG 还是 0×0 ⇒ 图只露出左上角一角 ⚠
    svg.attr('width', W).attr('height', H).attr('viewBox', `0 0 ${W} ${H}`)
    svg.selectAll('*').remove()

    // ③ zoom 层
    const root = svg.append('g').attr('class', 'zoom-layer')
    gRef.current = root.node() as SVGGElement

    const linkLayer = root.append('g').attr('class', 'links')
    const nodeLayer = root.append('g').attr('class', 'nodes')

    // ④ 边（可见线 + 透明加宽命中线）
    const linkSel = linkLayer
      .selectAll<SVGLineElement, SimLink>('line.link')
      .data(links, (d) => d.id)
      .join('line')
      .attr('class', 'link')
      .attr('stroke', (d) => {
        const src = byId.get(String(d.source))
        return src ? colorOf(src.node) : '#94a3b8'
      })
      .attr('stroke-width', 1.2)
      .attr('stroke-opacity', 0.55)

    // ⑤ 节点组
    const nodeSel = nodeLayer
      .selectAll<SVGGElement, SimNode>('g.node')
      .data(nodes, (d) => d.id)
      .join('g')
      .attr('class', 'node')
      .style('cursor', 'pointer')

    nodeSel
      .append('circle')
      .attr('r', (d) => d.r)
      .attr('fill', (d) => colorOf(d.node))
      .attr('stroke', (d) => (d.node.patched ? '#fbbf24' : '#ffffff'))
      .attr('stroke-width', (d) => (d.node.patched ? 2.5 : 2))

    nodeSel
      .append('text')
      .attr('class', 'node-label')
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => d.r + 13)
      .attr('font-size', 11)
      .attr('fill', 'var(--text-muted, #94a3b8)')
      .style('pointer-events', 'none')
      .text((d) => truncate(d.node.name, labelMax(d.node)))

    // ⑥ 力导向
    const sim = forceSimulation<SimNode>(nodes)
      .force('link', forceLink<SimNode, SimLink>(links).id((d) => d.id).distance(70).strength(0.35))
      .force('charge', forceManyBody<SimNode>().strength(-220))
      .force('center', forceCenter(0, 0))
      .force('collide', forceCollide<SimNode>((d) => d.r + 6))
      .alphaDecay(0.045)      // ≈1.5~2 秒收敛（d3 默认 0.0228 约 5 秒，太慢）
      .velocityDecay(0.4)
    simRef.current = sim

    // ⑦ tick：只更新 DOM 属性（React 不参与，零 re-render）
    const renderTick = () => {
      linkSel
        .attr('x1', (d) => (d.source as SimNode).x ?? 0)
        .attr('y1', (d) => (d.source as SimNode).y ?? 0)
        .attr('x2', (d) => (d.target as SimNode).x ?? 0)
        .attr('y2', (d) => (d.target as SimNode).y ?? 0)
      nodeSel.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`)
    }
    sim.on('tick', renderTick)

    // ⑧ 结束：fit 一次
    sim.on('end', () => {
      // ★ 只有首次布局才自动 fit；展开/隐藏后的重建保持当前视野
      const firstBuild = !fittedRef.current
      fittedRef.current = true
      const xs = nodes.map((n) => n.x ?? 0)
      const ys = nodes.map((n) => n.y ?? 0)
      if (firstBuild && xs.length) {
        const minX = Math.min(...xs), maxX = Math.max(...xs)
        const minY = Math.min(...ys), maxY = Math.max(...ys)
        const bw = Math.max(1, maxX - minX), bh = Math.max(1, maxY - minY)
        const pad = 60
        const k = Math.min((W - pad * 2) / bw, (H - pad * 2) / bh, 2)
        const tx = W / 2 - ((minX + maxX) / 2) * k
        const ty = H / 2 - ((minY + maxY) / 2) * k
        const t = zoomIdentity.translate(tx, ty).scale(k)
        svg.transition().duration(300).call(zoomRef.current!.transform, t)
        graphLog('fit', { k: n1(k), bw: n1(bw), bh: n1(bh) })
      }
      // 记住坐标供下次复用
      const m = new Map<string, { x: number; y: number; fx?: number | null; fy?: number | null }>()
      for (const n of nodes) m.set(n.id, { x: n.x ?? 0, y: n.y ?? 0, fx: n.fx, fy: n.fy })
      posRef.current = m
      graphLog('layout:done', { nodes: nodes.length })
      onPhase?.('布局完成')
    })

    // ⑨ zoom / pan
    const zoomBehavior = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.08, 8])
      .on('zoom', (ev) => {
        tfRef.current = ev.transform
        root.attr('transform', String(ev.transform))
        // 环形按钮跟随
        setRing((r) => {
          if (!r) return r
          const n = byId.get(String(r.vid))
          if (!n) return null
          const [sx, sy] = [n.x! * ev.transform.k + ev.transform.x, n.y! * ev.transform.k + ev.transform.y]
          return { ...r, x: sx, y: sy }
        })
        const curRing = ringRef.current
        if (curRing) setRingScale(ringScaleFor(curRing.r, ev.transform.k))
        // 标签疏密：缩小时只留高度数节点
        if (nodes.length >= LABEL_MIN_NODES) {
          const dense = ev.transform.k < LABEL_ZOOM_THRESHOLD
          nodeSel.select('text').style('display', (d) => {
            if (!dense) return null
            return keepLabel(d, nodes, links) ? null : 'none'
          })
        }
      })
    zoomRef.current = zoomBehavior
    svg.call(zoomBehavior)
    svg.on('dblclick.zoom', null)   // 双击不缩放（交给节点双击）

    // ★★ 初始 transform：
    //   首次建图 → 图原点居中 + 留散开余量（否则节点落在左上角外面，
    //             只能看到右下四分之一）。
    //   之后重建（展开邻居/隐藏节点）→ 保持用户当前视野，⛔ 不重置。
    if (!initedRef.current) {
      svg.call(zoomBehavior.transform, zoomIdentity.translate(W / 2, H / 2).scale(0.9))
      initedRef.current = true
    } else {
      svg.call(zoomBehavior.transform, tfRef.current)
    }

    // ⑩ 拖拽节点
    const dragBehavior = d3drag<SVGGElement, SimNode>()
      .on('start', (ev, d) => {
        if (!ev.active) sim.alphaTarget(0.25).restart()
        d.fx = d.x; d.fy = d.y
      })
      .on('drag', (ev, d) => {
        // ★★ d3-drag 的 event.x/y **已经是图坐标**（相对父 <g>，zoom transform
        //   由 d3.pointer 的 getScreenCTM().inverse() 计入）
        //   ⛔ 不能再调 toGraph()：那会二次换算（减 translate、除 k），
        //     鼠标与节点差出几十上百像素（所有者反馈）。
        d.fx = ev.x; d.fy = ev.y
      })
      .on('end', (ev, d) => {
        if (!ev.active) sim.alphaTarget(0)
        // ★★ 不清理 fx/fy —— 用户手动摆放的位置要**定住**。
        //   ⛔ 置 null 的话力导向会立刻把节点拽回去（所有者反馈「松开就弹回去」）。
        //   想恢复自动布局：双击该节点（见下面 dblclick）。
        d.fx = d.x; d.fy = d.y
      })
    nodeSel.call(dragBehavior)

    // ⑪ 节点 hover / 点击
    nodeSel
      .on('mouseenter', (ev: MouseEvent, d) => {
        window.clearTimeout(leaveTimerRef.current)
        applyActive(d.id, nodes, links, nodeSel, linkSel)
        const rect = box.getBoundingClientRect()
        const [sx, sy] = [ev.clientX - rect.left, ev.clientY - rect.top]
        setHover({ node: d.node, x: sx + rect.left, y: sy + rect.top })
        setEdgeHover(null)
        graphLog('hover:enter', { node: d.id, name: d.node.name })
      })
      .on('mouseleave', () => {
        window.clearTimeout(leaveTimerRef.current)
        leaveTimerRef.current = window.setTimeout(() => {
          leaveTimerRef.current = 0
          if (cardHoverRef.current) return
          setHover(null)
          clearActive(nodeSel, linkSel)
        }, HOVER_LINGER_MS)
      })
      .on('dblclick', (ev: MouseEvent, d) => {
        // ★ 双击节点 = 取消固定（解除用户拖拽时锁定的位置），恢复力导向
        ev.stopPropagation()
        d.fx = null; d.fy = null
        sim.alpha(0.3).restart()
        graphLog('drag:unfix', { node: d.id })
      })
      .on('click', (ev: MouseEvent, d) => {
        ev.stopPropagation()
        onSelect(Number(d.id))
        // ★★ 圆心必须是**节点中心**，⛔ 不是鼠标点击点 ——
        //   点在节点边缘时，用鼠标坐标会让圆环偏出去（所有者反馈「圆心不是节点」）
        const [sx, sy] = toScreen(d.x ?? 0, d.y ?? 0)
        setRing({ vid: Number(d.id), x: sx, y: sy, r: d.r })
        setRingScale(ringScaleFor(d.r, tfRef.current.k))
        setHover(null)
      })

    // ⑫ 边 hover（SVG line 自带宽命中，另加手动距离兜底）
    linkSel
      .on('mouseenter', (ev: MouseEvent, d) => {
        window.clearTimeout(edgeLeaveRef.current)
        const rect = box.getBoundingClientRect()
        setEdgeHover({ edge: d.edge, x: ev.clientX - rect.left, y: ev.clientY - rect.top })
        select(ev.currentTarget as SVGLineElement).attr('stroke-width', 2.5).attr('stroke-opacity', 1)
      })
      .on('mouseleave', (ev: MouseEvent) => {
        select(ev.currentTarget as SVGLineElement).attr('stroke-width', 1.2).attr('stroke-opacity', 0.55)
        window.clearTimeout(edgeLeaveRef.current)
        edgeLeaveRef.current = window.setTimeout(() => setEdgeHover(null), 200)
      })

    // ⑬ 点空白：取消选中 + 收起环形按钮
    svg.on('click', () => {
      setRing(null)
      setHover(null)
      clearActive(nodeSel, linkSel)
      onDeselect?.()
    })

    // ⑭ 首次渲染 + 启动
    renderTick()
    onPhase?.('布局中…')

    // 清理
    return () => {
      cancelAnimationFrame(0)
      sim.stop()
      simRef.current = null
      zoomRef.current = null
      svg.on('.zoom', null)
      svg.selectAll('*').remove()
      setRing(null)
      setHover(null)
      setEdgeHover(null)
      window.clearTimeout(leaveTimerRef.current)
      window.clearTimeout(edgeLeaveRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, fullGraph, dataVersion])

  // ============================================================ 选中 / 高亮 / 主题：只改属性
  useEffect(() => {
    const svgEl = svgRef.current
    if (!svgEl) return
    const nodeSel = select(svgEl).selectAll<SVGGElement, SimNode>('g.node')
    if (!nodeSel.size()) return

    const sel = selectedVid != null ? String(selectedVid) : null
    const hl = new Set((highlightVids ?? []).map(String))

    nodeSel.select('circle')
      .attr('r', (d) => {
        const base = d.r
        if (sel && d.id === sel) return base * 1.3
        if (hl.has(d.id)) return base * 1.18
        return base
      })
      .attr('stroke', (d) => {
        if (sel && d.id === sel) return '#22d3ee'
        if (hl.has(d.id)) return '#f59e0b'
        return d.node.patched ? '#fbbf24' : '#ffffff'
      })
      .attr('stroke-width', (d) => {
        if (sel && d.id === sel) return 3.5
        if (hl.has(d.id)) return 3
        return d.node.patched ? 2.5 : 2
      })
      .attr('fill-opacity', (d) => {
        // ★★ 选中（sel）**不再压暗其他节点** ——
        //   页面一打开就把默认焦点设为选中，压暗 0.35 会让整张图发浅（所有者反馈）。
        //   只有「执行流高亮」才压暗非相关节点。
        if (!hl.size) return 1
        return hl.has(d.id) || d.id === sel ? 1 : 0.45
      })

    nodeSel.select('text').attr('fill', (d) => {
      if (sel && d.id === sel) return '#22d3ee'
      if (hl.has(d.id)) return '#f59e0b'
      return 'var(--text-muted, #94a3b8)'
    })
  }, [selectedVid, highlightVids, dataVersion])

  // ============================================================ 聚焦
  useEffect(() => {
    const svgEl = svgRef.current
    const zoomBehavior = zoomRef.current
    if (!svgEl || !zoomBehavior || focusVid == null) return
    const n = nodesRef.current.find((x) => x.id === String(focusVid))
    if (!n) return
    const box = boxRef.current
    const W = box?.clientWidth ?? 900
    const H = box?.clientHeight ?? 600
    const k = tfRef.current.k
    const tx = W / 2 - (n.x ?? 0) * k
    const ty = H / 2 - (n.y ?? 0) * k
    select(svgEl).transition().duration(300)
      .call(zoomBehavior.transform, zoomIdentity.translate(tx, ty).scale(k))
  }, [focusVid])

  // ============================================================ 尺寸变化
  useEffect(() => {
    const box = boxRef.current
    const svgEl = svgRef.current
    if (!box || !svgEl) return
    let last = ''
    const ro = new ResizeObserver(() => {
      const w = box.clientWidth, h = box.clientHeight
      const key = `${w}x${h}`
      if (key === last) return
      last = key
      if (w > 0 && h > 0) {
        select(svgEl).attr('width', w).attr('height', h).attr('viewBox', `0 0 ${w} ${h}`)
        graphLog('resize', { w, h })
      }
    })
    ro.observe(box)
    return () => ro.disconnect()
  }, [])

  // ============================================================ 流星
  useEffect(() => {
    const box = boxRef.current
    if (!box || !meteors) return
    const list = linksRef.current.map((l) => {
      const s = l.source as SimNode
      const t = l.target as SimNode
      return {
        from: s.id,
        to: t.id,
        size: s.r,
        color: colorOf(s.node),
        toSize: t.r,
      }
    })
    if (!list.length) return
    const getPos = (id: string): [number, number] | null => {
      const n = nodesRef.current.find((x) => x.id === id)
      if (!n) return null
      return toScreen(n.x ?? 0, n.y ?? 0)
    }
    const stop = startMeteor(getPos, box, list, {
      speed: meteorSpeed,
      sizeRatio: meteorSizeRatio,
    })
    return stop
  }, [meteors, meteorSpeed, meteorSizeRatio, dataVersion, toScreen])

  // ============================================================ 环形按钮动作
  /**
   * ★ 显示邻居：从 fullGraph 里把「当前不可见」的邻居加进 extra。
   *   新节点的初始位置放在宿主周围一圈（写进 posRef，重建时直接用）。
   */
  const expandNeighbors = useCallback((vid: number) => {
    setRing(null)
    const id = String(vid)
    const src = fullGraph
    if (!src) return

    // 当前可见集合
    const visible = new Set(nodesRef.current.map((n) => n.id))

    // 找出该节点的全部邻居
    const nbrs = new Set<string>()
    for (const e of src.edges) {
      const f = String(e.from), t = String(e.to)
      if (f === id) nbrs.add(t)
      else if (t === id) nbrs.add(f)
    }

    const missing = [...nbrs].filter((v) => !visible.has(v))
    graphLog('expand', { host: id, neighbors: nbrs.size, adding: missing.length })
    if (!missing.length) return

    // 新节点摆成宿主周围一圈
    const host = nodesRef.current.find((n) => n.id === id)
    const hx = host?.x ?? 0
    const hy = host?.y ?? 0
    missing.forEach((v, i) => {
      const ang = (Math.PI * 2 * i) / missing.length - Math.PI / 2
      posRef.current.set(v, {
        x: hx + Math.cos(ang) * 70,
        y: hy + Math.sin(ang) * 70,
      })
      extraRef.current.add(v)
      hiddenRef.current.delete(v)   // 之前藏过的，显示时一并露出
    })

    setDataVersion((v) => v + 1)
  }, [fullGraph])

  /**
   * ★ 隐藏节点：把它和「只连着它的孤儿邻居」一起加进 hidden。
   *   注：只是从画布去掉，数据还在页面的 graph.json 里，重新解析/重建会回来。
   */
  const hideNode = useCallback((vid: number) => {
    setRing(null)
    const id = String(vid)

    // 当前可见图的度数
    const deg = new Map<string, number>()
    for (const l of linksRef.current) {
      const s = String(typeof l.source === 'string' ? l.source : l.source.id)
      const t = String(typeof l.target === 'string' ? l.target : l.target.id)
      deg.set(s, (deg.get(s) ?? 0) + 1)
      deg.set(t, (deg.get(t) ?? 0) + 1)
    }

    const removing = new Set<string>([id])
    for (const l of linksRef.current) {
      const s = String(typeof l.source === 'string' ? l.source : l.source.id)
      const t = String(typeof l.target === 'string' ? l.target : l.target.id)
      if (s === id && (deg.get(t) ?? 0) === 1) removing.add(t)
      if (t === id && (deg.get(s) ?? 0) === 1) removing.add(s)
    }

    for (const v of removing) {
      hiddenRef.current.add(v)
      extraRef.current.delete(v)
    }
    graphLog('hide', { target: id, removing: [...removing] })

    setDataVersion((v) => v + 1)
    if (selectedVid != null && removing.has(String(selectedVid))) onDeselect?.()
  }, [selectedVid, onDeselect])

  /**
   * ★ 扇区 + 图标位置：
   *   图标必须画在**扇区中部**（角度中点、半径 (r1+r2)/2），
   *   ⛔ 之前固定 translate(36 36) 把两个图标都堆在圆心，
   *     叠成一颗白色星芒（所有者截图）。
   */
  const segments = useMemo(() => {
    const midR = (RING_GEO.r1 + RING_GEO.r2) / 2
    const mk = (
      key: string, title: string, a1: number, a2: number, icon: string, run: (vid: number) => void,
    ) => {
      const mid = (a1 + a2) / 2
      return {
        key, title, a1, a2, icon, run,
        ix: RING_GEO.c + Math.cos(mid) * midR,
        iy: RING_GEO.c + Math.sin(mid) * midR,
      }
    }
    return [
      mk('expand', '显示邻居', -Math.PI / 2 + 0.18, Math.PI / 2 - 0.18, 'M12 5v14M5 12h14', expandNeighbors),
      mk('hide', '隐藏节点', Math.PI / 2 + 0.18, Math.PI * 1.5 - 0.18, 'M2 2l20 20M2 22L22 2', hideNode),
    ]
  }, [expandNeighbors, hideNode])

  return (
    <div
      ref={boxRef}
      style={{ width: '100%', height: '100%', position: 'relative', overflow: 'hidden', pointerEvents: aiBusy ? 'none' : 'auto' }}
    >
      <svg
        ref={svgRef}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block' }}
      />

      {ring && (
        <svg
          className="node-ring"
          style={{
            position: 'absolute',
            left: ring.x,
            top: ring.y,
            width: 96,
            height: 96,
            transform: `translate(-50%, -50%) scale(${ringScale})`,
            zIndex: 20,
            overflow: 'visible',
          }}
        >
          {segments.map((s) => (
            <g key={s.key}>
              <path
                d={ringArcPath(s.a1, s.a2)}
                /* ★ 灰白半透明（所有者要求）：白底 + 浅灰描边 + 投影，浮在图上不刺眼 */
                fill="rgba(255,255,255,0.92)"
                stroke="rgba(148,163,184,0.9)"
                strokeWidth={1}
                style={{
                  cursor: 'pointer',
                  filter: 'drop-shadow(0 2px 8px rgba(15,23,42,0.18))',
                }}
                onClick={(e) => { e.stopPropagation(); s.run(ring.vid) }}
              >
                <title>{s.title}</title>
              </path>
              <path
                d={s.icon}
                fill="none"
                /* 深灰图标：白底上清晰，且不抢节点颜色 */
                stroke="#475569"
                strokeWidth={2.6}
                strokeLinecap="round"
                style={{ pointerEvents: 'none' }}
                transform={`translate(${s.ix - 6.6} ${s.iy - 6.6}) scale(0.55)`}
              />
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
          onLeave={() => {
            cardHoverRef.current = false
            setHover(null)
            const svgEl = svgRef.current
            if (svgEl) {
              const nodeSel = select(svgEl).selectAll<SVGGElement, SimNode>('g.node')
              const linkSel = select(svgEl).selectAll<SVGLineElement, SimLink>('line.link')
              clearActive(nodeSel, linkSel)
            }
          }}
        />
      )}
      {edgeHover && <EdgeHoverCard edge={edgeHover.edge} x={edgeHover.x} y={edgeHover.y} />}
    </div>
  )
}

// ---------------------------------------------------------------- hover 高亮工具

/** 缩小时哪些节点保留标签：一是选中/高亮，二是度数最高的前 N 个 */
function keepLabel(d: SimNode, nodes: SimNode[], links: SimLink[]): boolean {
  const deg = new Map<string, number>()
  for (const l of links) {
    const s = String(typeof l.source === 'string' ? l.source : l.source.id)
    const t = String(typeof l.target === 'string' ? l.target : l.target.id)
    deg.set(s, (deg.get(s) ?? 0) + 1)
    deg.set(t, (deg.get(t) ?? 0) + 1)
  }
  const top = [...deg.entries()].sort((a, b) => b[1] - a[1]).slice(0, LABEL_TOP_DEGREE).map(([id]) => id)
  return top.includes(d.id)
}

/** 高亮节点 + 一度邻居 + 相连边 */
function applyActive(
  id: string,
  nodes: SimNode[],
  links: SimLink[],
  nodeSel: Selection<SVGGElement, SimNode, any, any>,
  linkSel: Selection<SVGLineElement, SimLink, any, any>,
) {
  const set = new Set<string>([id])
  for (const l of links) {
    const s = String(typeof l.source === 'string' ? l.source : l.source.id)
    const t = String(typeof l.target === 'string' ? l.target : l.target.id)
    if (s === id) set.add(t)
    else if (t === id) set.add(s)
  }
  void nodes
  nodeSel
    .select('circle')
    .attr('fill-opacity', (d) => (set.has(d.id) ? 1 : 0.25))
    .attr('stroke-width', (d) => (d.id === id ? 3.5 : set.has(d.id) ? 2.5 : 2))
  linkSel
    .attr('stroke-opacity', (l) => {
      const s = String(typeof l.source === 'string' ? l.source : l.source.id)
      const t = String(typeof l.target === 'string' ? l.target : l.target.id)
      return set.has(s) && set.has(t) ? 1 : 0.12
    })
    .attr('stroke-width', (l) => {
      const s = String(typeof l.source === 'string' ? l.source : l.source.id)
      const t = String(typeof l.target === 'string' ? l.target : l.target.id)
      return set.has(s) && set.has(t) ? 2.2 : 1.2
    })
}

/** 取消高亮 */
function clearActive(
  nodeSel: Selection<SVGGElement, SimNode, any, any>,
  linkSel: Selection<SVGLineElement, SimLink, any, any>,
) {
  nodeSel.select('circle').attr('fill-opacity', 1).attr('stroke-width', (d) => (d.node.patched ? 2.5 : 2))
  linkSel.attr('stroke-opacity', 0.55).attr('stroke-width', 1.2)
}
