import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { invoke } from '../api'
import type { Graph } from '../../../shared/contract'

const W = 900
const H = 620

export default function GraphPage() {
  const { ref = '' } = useParams()
  const [graph, setGraph] = useState<Graph | null>(null)

  useEffect(() => {
    invoke('graph.full', ref)
      .then(setGraph)
      .catch(() => {})
  }, [ref])

  const view = useMemo(() => {
    if (!graph) return null
    const nodes = graph.nodes.slice(0, 200)
    const pos = new Map<number, { x: number; y: number }>()
    nodes.forEach((n, i) => {
      const a = (i / Math.max(nodes.length, 1)) * Math.PI * 2
      const r = 180 + (i % 3) * 45
      pos.set(n.vid, { x: W / 2 + Math.cos(a) * r * 1.4, y: H / 2 + Math.sin(a) * r })
    })
    const edges = graph.edges.filter((e) => pos.has(e.from) && pos.has(e.to))
    return { nodes, edges, pos }
  }, [graph])

  return (
    <div className="graph-page">
      <div className="graph-summary">
        {graph
          ? `${graph.nodes.length} 个节点 · ${graph.edges.length} 条边${graph.nodes.length > 200 ? '（画布只画前 200 个）' : ''}`
          : '正在读取图谱…'}
      </div>
      {!view ? null : view.nodes.length === 0 ? (
        <div className="graph-stage faint">还没有节点，回到项目页点「解析项目」</div>
      ) : (
        <svg className="graph-svg" viewBox={`0 0 ${W} ${H}`}>
          {view.edges.map((e) => {
            const a = view.pos.get(e.from)!
            const b = view.pos.get(e.to)!
            return (
              <line
                key={e.id}
                className={`graph-edge ${e.type}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
              />
            )
          })}
          {view.nodes.map((n) => {
            const p = view.pos.get(n.vid)!
            return (
              <g key={n.vid} className="graph-node">
                <circle cx={p.x} cy={p.y} r={n.kind === 'file' ? 7 : 5} className={n.kind} />
                <text x={p.x + 10} y={p.y + 4}>
                  {n.name}
                </text>
              </g>
            )
          })}
        </svg>
      )}
    </div>
  )
}
