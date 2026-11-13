import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { invoke } from '../api'
import type { GraphNode } from '../../../shared/contract'

interface Props {
  projectRef: string
  selectedVid: number
  onSelect: (vid: number, label: string) => void
}

export default function NodeListView({ projectRef, selectedVid, onSelect }: Props) {
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState('')

  const load = async () => {
    try {
      setNodes(await invoke('graph.nodes', projectRef))
    } catch {
      setNodes([])
    }
  }

  useEffect(() => {
    void load()
  }, [projectRef])

  const parse = async () => {
    setBusy(true)
    setReport('正在解析…')
    try {
      const r = await invoke('project.parse', projectRef)
      setReport(`${r.files} 个文件 · ${r.nodes} 个节点 · ${r.edges} 条边`)
      await load()
    } catch (e) {
      setReport(String(e))
    } finally {
      setBusy(false)
    }
  }

  const items = nodes.filter((n) => !query || n.qname.toLowerCase().includes(query.toLowerCase()))

  return (
    <div className="pane list-pane node-tree">
      <div className="pane-bar">
        <span>节点</span>
        <button type="button" className="btn ghost" disabled={busy} onClick={() => void parse()}>
          <RefreshCw size={12} /> {busy ? '解析中…' : '解析项目'}
        </button>
      </div>
      <input
        className="node-search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="搜索节点名"
      />
      {report && <div className="faint node-report">{report}</div>}
      <div className="node-list">
        {items.map((n) => (
          <button
            key={n.vid}
            type="button"
            className={`node-item${n.vid === selectedVid ? ' active' : ''}`}
            title={`${n.file}:${n.line}`}
            onClick={() => onSelect(n.vid, n.qname)}
          >
            <span className={`node-kind ${n.kind}`}>
              {n.kind === 'file' ? '文' : n.kind === 'type' ? '类' : '函'}
            </span>
            <span className="node-name">{n.qname}</span>
            <span className="faint node-file">{n.file}</span>
          </button>
        ))}
        {items.length === 0 && (
          <div className="faint node-hint">还没有节点，点「解析项目」扫描源码目录</div>
        )}
      </div>
    </div>
  )
}
