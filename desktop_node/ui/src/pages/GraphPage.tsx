import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Minus, Plus, RefreshCw, X } from 'lucide-react'
import { useParams } from 'react-router-dom'
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'
import { invoke } from '../api'
import type { Graph, GraphEdge } from '../../../shared/contract'

const W = 900
const H = 620
const MAX_NODES = 300
const TICKS = 280

interface SimNode extends SimulationNodeDatum {
  id: number
  kind: string
  name: string
  qname: string
  file: string
  line: number
  degree: number
}

interface Layout {
  nodes: SimNode[]
  edges: GraphEdge[]
}

/** 力导向布局：同步跑完收敛，再自适应到画布；无动画 timer、无每帧重渲染 */
function buildLayout(graph: Graph, seed: number): Layout {
  const picked = graph.nodes.slice(0, MAX_NODES)
  const ids = new Set(picked.map((n) => n.vid))
  const edges = graph.edges.filter((e) => ids.has(e.from) && ids.has(e.to))

  const degree = new Map<number, number>()
  for (const e of edges) {
    degree.set(e.from, (degree.get(e.from) ?? 0) + 1)
    degree.set(e.to, (degree.get(e.to) ?? 0) + 1)
  }

  const nodes: SimNode[] = picked.map((n) => ({
    ...n,
    id: n.vid,
    degree: degree.get(n.vid) ?? 0,
  }))
  nodes.forEach((n, i) => {
    const a = i * 2.399963 + seed * 1.7
    const r = 40 + Math.sqrt(i) * 24
    n.x = Math.cos(a) * r
    n.y = Math.sin(a) * r
  })

  const links: SimulationLinkDatum<SimNode>[] = edges.map((e) => ({
    source: e.from,
    target: e.to,
  }))
  const sim = forceSimulation(nodes)
    .force(
      'link',
      forceLink<SimNode, SimulationLinkDatum<SimNode>>(links)
        .id((d) => d.id)
        .distance(80)
        .strength(0.35),
    )
    .force('charge', forceManyBody<SimNode>().strength(-160).distanceMax(400))
    .force('center', forceCenter(0, 0))
    .force('collide', forceCollide<SimNode>().radius((d) => 12 + Math.min(d.degree, 8) * 2))
    .stop()
  for (let i = 0; i < TICKS; i++) sim.tick()
  sim.stop()

  // 自适应视图：把收敛结果居中并缩放到画布内
  if (nodes.length) {
    let minX = Infinity
    let maxX = -Infinity
    let minY = Infinity
    let maxY = -Infinity
    for (const n of nodes) {
      minX = Math.min(minX, n.x ?? 0)
      maxX = Math.max(maxX, n.x ?? 0)
      minY = Math.min(minY, n.y ?? 0)
      maxY = Math.max(maxY, n.y ?? 0)
    }
    const scale = Math.min((W - 100) / Math.max(maxX - minX, 1), (H - 100) / Math.max(maxY - minY, 1), 2)
    const cx = (minX + maxX) / 2
    const cy = (minY + maxY) / 2
    for (const n of nodes) {
      n.x = ((n.x ?? 0) - cx) * scale + W / 2
      n.y = ((n.y ?? 0) - cy) * scale + H / 2
    }
  }
  return { nodes, edges }
}

export default function GraphPage() {
  const { ref = '' } = useParams()
  const [graph, setGraph] = useState<Graph | null>(null)
  const [seed, setSeed] = useState(0)
  const [layout, setLayout] = useState<Layout | null>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [hover, setHover] = useState<number | null>(null)
  const [selected, setSelected] = useState<SimNode | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragRef = useRef<{ id: number; sx: number; sy: number; x: number; y: number } | null>(null)
  const panRef = useRef<{ sx: number; sy: number; x: number; y: number } | null>(null)

  useEffect(() => {
    invoke('graph.full', ref)
      .then(setGraph)
      .catch(() => {})
  }, [ref])

  const computed = useMemo(() => (graph ? buildLayout(graph, seed) : null), [graph, seed])
  useEffect(() => {
    setLayout(computed)
  }, [computed])

  const pos = useMemo(() => new Map(layout?.nodes.map((n) => [n.id, n]) ?? []), [layout])

  const neighbors = useMemo(() => {
    const s = new Set<number>()
    if (hover == null || !layout) return s
    s.add(hover)
    for (const e of layout.edges) {
      if (e.from === hover) s.add(e.to)
      if (e.to === hover) s.add(e.from)
    }
    return s
  }, [hover, layout])

  const toSvg = (clientX: number, clientY: number) => {
    const rect = svgRef.current!.getBoundingClientRect()
    return {
      x: ((clientX - rect.left) * W) / rect.width,
      y: ((clientY - rect.top) * H) / rect.height,
    }
  }

  const onNodeDown = (e: ReactPointerEvent, n: SimNode) => {
    e.stopPropagation()
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    dragRef.current = { id: n.id, sx: e.clientX, sy: e.clientY, x: n.x ?? 0, y: n.y ?? 0 }
  }

  const onNodeMove = (e: ReactPointerEvent) => {
    const d = dragRef.current
    if (!d) return
    const now = toSvg(e.clientX, e.clientY)
    const start = toSvg(d.sx, d.sy)
    const dx = (now.x - start.x) / zoom
    const dy = (now.y - start.y) / zoom
    setLayout((l) =>
      l
        ? { ...l, nodes: l.nodes.map((n) => (n.id === d.id ? { ...n, x: d.x + dx, y: d.y + dy } : n)) }
        : l,
    )
  }

  const onNodeUp = (e: ReactPointerEvent) => {
    dragRef.current = null
    try {
      ;(e.currentTarget as Element).releasePointerCapture(e.pointerId)
    } catch {
      /* 指针已释放 */
    }
  }

  const onSvgDown = (e: ReactPointerEvent) => {
    if (e.button !== 0) return
    panRef.current = { sx: e.clientX, sy: e.clientY, x: pan.x, y: pan.y }
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
  }

  const onSvgMove = (e: ReactPointerEvent) => {
    if (dragRef.current) return
    const p = panRef.current
    if (!p) return
    const now = toSvg(e.clientX, e.clientY)
    const start = toSvg(p.sx, p.sy)
    setPan({ x: p.x + now.x - start.x, y: p.y + now.y - start.y })
  }

  const onSvgUp = (e: ReactPointerEvent) => {
    panRef.current = null
    try {
      ;(e.currentTarget as Element).releasePointerCapture(e.pointerId)
    } catch {
      /* 指针已释放 */
    }
  }

  const zoomBy = (factor: number) => setZoom((z) => Math.max(0.4, Math.min(3, z * factor)))

  return (
    <div className="graph-page">
      <div className="graph-toolbar">
        <span>
          {graph
            ? `${graph.nodes.length} 个节点 · ${graph.edges.length} 条边${graph.nodes.length > MAX_NODES ? `（画布显示前 ${MAX_NODES} 个）` : ''}`
            : '正在读取图谱…'}
        </span>
        <div className="graph-legend">
          <span><i className="dot file" />文件</span>
          <span><i className="dot type" />类型</span>
          <span><i className="dot function" />函数</span>
          <span><i className="line call" />调用</span>
          <span><i className="line include" />包含</span>
        </div>
        <button type="button" className="btn ghost" onClick={() => setSeed((s) => s + 1)}>
          <RefreshCw size={12} /> 重新布局
        </button>
        <div className="board-zoom">
          <button type="button" title="缩小" onClick={() => zoomBy(1 / 1.15)}><Minus size={12} /></button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" title="放大" onClick={() => zoomBy(1.15)}><Plus size={12} /></button>
        </div>
        <button type="button" className="btn ghost" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }) }}>
          复位
        </button>
      </div>

      {!layout ? null : layout.nodes.length === 0 ? (
        <div className="graph-stage faint">还没有节点，回到项目页点「解析项目」</div>
      ) : (
        <div className="graph-canvas-wrap">
          <svg
            ref={svgRef}
            className="graph-svg"
            viewBox={`0 0 ${W} ${H}`}
            onPointerDown={onSvgDown}
            onPointerMove={onSvgMove}
            onPointerUp={onSvgUp}
            onWheel={(e) => zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12)}
          >
            <g
              transform={`translate(${W / 2 + pan.x},${H / 2 + pan.y}) scale(${zoom}) translate(${-W / 2},${-H / 2})`}
            >
              {layout.edges.map((e) => {
                const a = pos.get(e.from)
                const b = pos.get(e.to)
                if (!a || !b) return null
                const dim = hover != null && !(neighbors.has(e.from) && neighbors.has(e.to))
                return (
                  <line
                    key={e.id}
                    className={`graph-edge ${e.type}${dim ? ' dimmed' : ''}`}
                    x1={a.x ?? 0}
                    y1={a.y ?? 0}
                    x2={b.x ?? 0}
                    y2={b.y ?? 0}
                  />
                )
              })}
              {layout.nodes.map((n) => {
                const dim = hover != null && !neighbors.has(n.id)
                return (
                  <g
                    key={n.id}
                    className={`graph-node${dim ? ' dimmed' : ''}`}
                    onPointerDown={(e) => onNodeDown(e, n)}
                    onPointerMove={onNodeMove}
                    onPointerUp={onNodeUp}
                    onMouseEnter={() => setHover(n.id)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => setSelected(n)}
                  >
                    <circle
                      cx={n.x ?? 0}
                      cy={n.y ?? 0}
                      r={5 + Math.min(n.degree, 8) + (n.kind === 'file' ? 2 : 0)}
                      className={n.kind}
                    />
                    {(zoom > 0.75 || n.degree > 2) && (
                      <text x={(n.x ?? 0) + 11} y={(n.y ?? 0) + 4}>
                        {n.name}
                      </text>
                    )}
                  </g>
                )
              })}
            </g>
          </svg>

          {selected && (
            <div className="card graph-detail">
              <button type="button" className="graph-detail-close" onClick={() => setSelected(null)}>
                <X size={12} />
              </button>
              <div className="graph-detail-title">{selected.qname || selected.name}</div>
              <div className="faint">
                {selected.kind === 'file' ? '文件' : selected.kind === 'type' ? '类型' : '函数'} · {selected.file}:{selected.line}
              </div>
              <div className="faint">相连 {selected.degree} 条边</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
