import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { invoke } from '../api'
import type { Graph } from '../../../shared/contract'

export default function GraphPage() {
  const { ref = '' } = useParams()
  const [graph, setGraph] = useState<Graph | null>(null)

  useEffect(() => {
    invoke('graph.full', ref)
      .then(setGraph)
      .catch(() => {})
  }, [ref])

  return (
    <div className="graph-page">
      <div className="graph-summary">
        {graph ? `${graph.nodes.length} 个节点 · ${graph.edges.length} 条边` : '正在读取图谱…'}
      </div>
      <div className="graph-stage faint">图谱画布（解析器模块接入后渲染）</div>
    </div>
  )
}
