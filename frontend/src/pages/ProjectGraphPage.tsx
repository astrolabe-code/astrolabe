import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { List, Loader2, Search, Sparkles, Workflow } from 'lucide-react'
import type { GraphNode } from '../lib/mergeGraph'
import { errorMessage } from '../api/errors'
import { useFullGraph } from '../query/graph'
import { useProject } from '../query/projects'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import GraphCanvas from '../components/graph/GraphCanvas'
import NodePanel from '../components/node/NodePanel'

/**
 * ★ 图谱页（`D98` · AntV G6）
 *
 * ## ★★ 它补的是「看清结构关系」这一半
 *
 * | 页面 | 回答的问题 |
 * |---|---|
 * | 项目页（列表） | ★ 「这个节点在哪？* 搜一下」✅ |
 * | ★★ 图谱页（本页） | ★★ 「**谁调谁、哪儿是中心**」✅ |
 *
 * ## ★★ 数据与渲染
 *
 * ```
 * ★★ `useFullGraph`：* 循环分页拉全 nodes/edges + patches ⇒* `mergeGraph` 合并 ✅
 * ★★ `GraphCanvas`：* G6 力导向布局 ✅
 * ★★ 点节点 ⇒* 右侧开 `NodePanel`（* 与项目页同一个组件，* 笔记读写照旧）✅
 * ```
 */
const KIND_LABEL: Record<string, string> = {
  function: '函数',
  class: '类',
  method: '方法',
  module: '模块',
  file: '文件',
  package: '包',
}

const KIND_COLOR: Record<string, string> = {
  function: '#4db8d6',
  class: '#f59e0b',
  method: '#ec4899',
  module: '#a78bfa',
  file: '#22c55e',
  package: '#a78bfa',
}

export default function ProjectGraphPage() {
  const { projectRef = '' } = useParams<{ projectRef: string }>()
  const graph = useFullGraph(projectRef)
  const project = useProject(projectRef)
  const me = useMe()
  const [selectedVid, setSelectedVid] = useState<number | null>(null)
  // ★★ `D104`：* 流星轨迹开关（* 默认开；* 嫌吵能关）⚠
  const [meteors, setMeteors] = useState(true)
  const [focusVid, setFocusVid] = useState<number | null>(null)
  const [q, setQ] = useState('')

  const p = project.data
  const g = graph.data
  const canWrite = !!p?.can_edit
  const meUsername = me.data?.username

  const selected = useMemo<GraphNode | null>(() => {
    if (!g || selectedVid == null) return null
    return g.nodes.find((n) => n.vid === selectedVid) || null
  }, [g, selectedVid])

  /** ★ kind 统计（* 图例按真实数据来） */
  const kinds = useMemo(() => {
    const m = new Map<string, number>()
    for (const n of g?.nodes || []) m.set(n.kind, (m.get(n.kind) || 0) + 1)
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [g])

  const search = () => {
    const kw = q.trim().toLowerCase()
    if (!kw || !g) return
    const hit =
      g.nodes.find((n) => (n.name || '').toLowerCase() === kw) ||
      g.nodes.find((n) => (n.name || '').toLowerCase().includes(kw)) ||
      g.nodes.find((n) => (n.qname || '').toLowerCase().includes(kw))
    if (hit) {
      setFocusVid(hit.vid)
      setSelectedVid(hit.vid)
    }
  }

  if (graph.isError) {
    return (
      <AppLayout title="图谱">
        <div className="card" style={{ padding: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>不存在或无权访问</div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
            {errorMessage(graph.error)}
          </div>
          <div className="mt-4">
            <Link to="/workspace">
              <Button>回工作区</Button>
            </Link>
          </div>
        </div>
      </AppLayout>
    )
  }

  return (
    <AppLayout
      page={false}
      crumbs={[
        { label: '工作区', to: '/workspace' },
        { label: p?.name || '项目', to: `/p/${encodeURIComponent(projectRef)}` },
        { label: '图谱' },
      ]}
    >
      <div style={{ display: 'flex', gap: 12, height: 'calc(100vh - 150px)', minHeight: 520 }}>
        {/* 左：工具栏 + 画布 */}
        <div className="flex flex-col min-w-0" style={{ flex: 1 }}>
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <div className="relative">
              <Search
                size={13}
                className="absolute left-2.5 top-1/2 -translate-y-1/2"
                style={{ color: 'var(--text-sub)' }}
              />
              <input
                className="input"
                style={{ paddingLeft: 28, width: 220, fontSize: 12.5 }}
                placeholder="搜节点名 / qname，回车定位"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') search()
                }}
              />
            </div>
            <Link to={`/p/${encodeURIComponent(projectRef)}`}>
              <Button icon={<List size={13} />}>回列表</Button>
            </Link>
            {/* ★★ `D104`：流星开关 */}
            <Button
              variant={meteors ? 'primary' : 'ghost'}
              icon={<Sparkles size={13} />}
              onClick={() => setMeteors((v) => !v)}
              title="节点之间飞过的流光效果"
            >
              流星
            </Button>
            <span className="faint" style={{ fontSize: 11.5, marginLeft: 'auto' }}>
              {g && `${g.nodes.length} 节点 · ${g.edges.length} 边`}
              {g && (g.manualNodeCount > 0 || g.manualEdgeCount > 0) && (
                <span style={{ color: 'var(--warn)' }}>
                  {` · 其中人工补的 ${g.manualNodeCount + g.manualEdgeCount} 项`}
                </span>
              )}
            </span>
          </div>

          <div
            className="card"
            style={{ flex: 1, minHeight: 0, overflow: 'hidden', padding: 0, position: 'relative' }}
          >
            {graph.isLoading ? (
              <div className="flex items-center justify-center h-full gap-2">
                <Loader2 size={16} className="animate-spin" style={{ color: 'var(--text-sub)' }} />
                <span className="faint" style={{ fontSize: 12.5 }}>
                  正在拉取整张图（节点 / 边 / 补丁）…
                </span>
              </div>
            ) : !g || g.nodes.length === 0 ? (
              <div className="flex items-center justify-center h-full">
                <EmptyState
                  title="这个项目还没有图"
                  hint="先去工作区触发拉取代码并解析"
                  icon={<Workflow size={28} />}
                  action={
                    <Link to="/workspace">
                      <Button variant="primary">去工作区</Button>
                    </Link>
                  }
                />
              </div>
            ) : (
              <GraphCanvas
                graph={g}
                meteors={meteors}
                selectedVid={selectedVid}
                onSelect={setSelectedVid}
                onDeselect={() => setSelectedVid(null)}
                focusVid={focusVid}
              />
            )}
          </div>

          {/* 图例 */}
          {g && g.nodes.length > 0 && (
            <div className="flex items-center gap-3 flex-wrap mt-2" style={{ fontSize: 11.5 }}>
              {kinds.map(([kind, count]) => (
                <span key={kind} className="flex items-center gap-1 faint">
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: KIND_COLOR[kind] || '#94a3b8',
                      display: 'inline-block',
                    }}
                  />
                  {KIND_LABEL[kind] || kind} {count}
                </span>
              ))}
              <span className="faint" style={{ marginLeft: 'auto' }}>
                菱形 = 人工补的节点 · 虚线边 = 人工补的边 · 黄色描边 = 被改过
              </span>
            </div>
          )}
        </div>

        {/* 右：节点面板（* 与项目页同一个组件） */}
        <div style={{ width: 380, flexShrink: 0, overflowY: 'auto', paddingRight: 2 }}>
          {selected ? (
            <NodePanel
              projectRef={projectRef}
              node={selected}
              canWrite={canWrite}
              meUsername={meUsername}
            />
          ) : (
            <div className="card flex items-center justify-center" style={{ minHeight: 200, padding: 20 }}>
              <div className="faint" style={{ fontSize: 12.5, textAlign: 'center', lineHeight: 1.8 }}>
                点画布上的节点，看它的笔记 ——
                <br />
                或者按「回列表」用搜索找节点。
              </div>
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  )
}
