import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ChevronDown,
  ChevronUp,
  List,
  Loader2,
  Route,
  Search,
  Sparkles,
  Trash2,
  Workflow,
  X,
} from 'lucide-react'
import type { GraphNode } from '../lib/mergeGraph'
import { errorMessage } from '../api/errors'
import { useFullGraph } from '../query/graph'
import { useProject } from '../query/projects'
import { useUserSettings } from '../query/settings'
import {
  useAppendToPath,
  useReadingPath,
  useRemoveFromPath,
  useReplacePath,
} from '../query/readingPath'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import GraphCanvas from '../components/graph/GraphCanvas'
import NodePanel from '../components/node/NodePanel'

/**
 * ★ 图谱页（`D98` · AntV G6 · `D105` 学习路径 · `D107` 健壮性）
 *
 * ## ★★ `D105`：初始只画一小批
 *
 * ```
 * ★★ 初始批量 = 学习路径的前 N 个（* N 视画布大小，* 12~24）✅
 *   · · ★ 没有路径 ⇒* 回落按**度数**排序，* 并提示作者还没排路径 ⚠
 * ★★ 「加载更多」= 沿顺序再取一批；* 「显示全部」留给要全图的人 ✅
 * ★★ 边只画两端都在已展示集合里的（* 否则出悬挂边）✅
 * ```
 *
 * ## ★★ `D107`：失效 vid 不卡站
 *
 * ```
 * ★★ 路径里有节点已不在图里 ⇒* 顶部提示 + 「一键清理」，* ⛔ 不自动删 ✅
 * ★★ 搜索定位到未展示的节点 ⇒* 先把它加进视图，* ⛔ 不静默失败 ✅
 * ```
 */
const KIND_LABEL: Record<string, string> = {
  function: '函数',
  class: '类',
  method: '方法',
  module: '模块',
  file: '文件',
  package: '包',
  type: '类型',
}

const KIND_COLOR: Record<string, string> = {
  function: '#4db8d6',
  class: '#f59e0b',
  method: '#ec4899',
  module: '#a78bfa',
  file: '#22c55e',
  package: '#a78bfa',
  type: '#f59e0b',
}

/** ★ `D105`：按画布面积算初始批量（* 12~24）⚠ */
function initialBatch() {
  const area = (window.innerWidth || 1280) * (window.innerHeight || 720)
  return Math.max(12, Math.min(24, Math.round(area / 45000)))
}

const BATCH_STEP = 24

// ★★★ **稳定的空数组**（`B234`/`D105`）——* `|| []` 每次渲染都是新引用 ⇒
//   * `pathVids`/`orderVids`/`view` 全变 ⇒* `GraphCanvas` 被反复重建 ⇒
//   * 布局、流星、阶段通知**全部被打断**（* 实测踩到）⚠
const EMPTY_ITEMS: import('../api/types').ReadingPathItem[] = []
const EMPTY_VIDS: number[] = []

export default function ProjectGraphPage() {
  const { projectRef = '' } = useParams<{ projectRef: string }>()
  const graph = useFullGraph(projectRef)
  const project = useProject(projectRef)
  const pathQ = useReadingPath(projectRef)
  const append = useAppendToPath(projectRef)
  const removeFromPath = useRemoveFromPath(projectRef)
  const replace = useReplacePath(projectRef)
  const me = useMe()
  // ★★ 流星参数来自**用户设置**（`graph.meteor.*`，* 三级继承 ⇒ 用户档覆盖默认）⚠
  // ★★ 只在**已登录**时请求（* 游客请求会 401 ⇒ 被踢去登录页）⚠
  const userSettings = useUserSettings(!!me.data?.authenticated)
  const meteorConf = userSettings.data?.settings ?? {}
  const meteorOnBySetting = meteorConf['graph.meteor.enabled'] !== false
  // ★ 后端用整数存：* speed 是「×1000」、* size_pct 是百分比 ⚠
  const meteorSpeed = Number(meteorConf['graph.meteor.speed'] ?? 5) / 1000
  const meteorSizeRatio = Number(meteorConf['graph.meteor.size_pct'] ?? 25) / 100

  const [selectedVid, setSelectedVid] = useState<number | null>(null)
  // ★★ `D104`：* 流星轨迹开关（* 默认开；* 嫌吵能关）⚠
  // ★ 默认跟用户设置走；* 工具栏开关只是本次会话的临时覆盖 ⚠
  const [meteors, setMeteors] = useState(true)
  const meteorsInited = useRef(false)
  useEffect(() => {
    if (meteorsInited.current || !userSettings.data) return
    meteorsInited.current = true
    setMeteors(meteorOnBySetting)
  }, [userSettings.data, meteorOnBySetting])
  const [focusVid, setFocusVid] = useState<number | null>(null)
  const [q, setQ] = useState('')
  // ★★ `D105`：* 已展示多少个（* null = 还没初始化 ⇒* 用 initialBatch()）
  const [shownCount, setShownCount] = useState<number | null>(null)
  const [pathOpen, setPathOpen] = useState(false)
  const [hint, setHint] = useState('')
  // ★ 画布当前阶段（* 布局动画中 / 布局完成 / 流星已启动）——* 用来验证效果真的跑了 ⚠
  const [phase, setPhase] = useState('')

  const p = project.data
  const g = graph.data
  const canWrite = !!p?.can_edit
  const meUsername = me.data?.username

  // ★ 用**稳定引用**，⛔ 不用 `|| []`（* 见 EMPTY_ITEMS 的说明）⚠
  const pathItems = pathQ.data?.items ?? EMPTY_ITEMS
  const stale = pathQ.data?.stale ?? EMPTY_VIDS
  const pathVids = useMemo(() => pathItems.map((i) => i.vid), [pathItems])
  const hasPath = pathVids.length > 0
  const ordinalOf = useMemo(() => {
    const m = new Map<number, number>()
    pathItems.forEach((i) => m.set(i.vid, i.ordinal))
    return m
  }, [pathItems])

  useEffect(() => {
    if (shownCount == null) setShownCount(initialBatch())
  }, [shownCount])

  /**
   * ★★ `D105`：展示顺序 = **学习路径优先，其余按度数补齐** ⚠
   *
   * ```
   * ★★ 路径里的节点排最前（* 作者指定的阅读顺序）✅
   * ★★ 路径排完（* 或作者没排）⇒* 剩下的按**度数从高到低**接在后面 ✅
   *   · · ★ 否则路径比首批短时，* 「加载更多 / 显示全部」永远不出现 ⇒
   *     * 用户只能盯着那几个节点（* 实测踩到）⚠
   * ```
   */
  const orderVids = useMemo(() => {
    if (!g) return []
    const deg = new Map<number, number>()
    for (const e of g.edges) {
      deg.set(e.from, (deg.get(e.from) || 0) + 1)
      deg.set(e.to, (deg.get(e.to) || 0) + 1)
    }
    const inGraph = new Set(g.nodes.map((n) => n.vid))
    const head = hasPath ? pathVids.filter((v) => inGraph.has(v)) : []
    const headSet = new Set(head)
    const tail = [...g.nodes]
      .filter((n) => !headSet.has(n.vid))
      .sort((a, b) => (deg.get(b.vid) || 0) - (deg.get(a.vid) || 0) || a.vid - b.vid)
      .map((n) => n.vid)
    return [...head, ...tail]
  }, [g, hasPath, pathVids])

  const shownVids = useMemo(
    () => new Set(orderVids.slice(0, shownCount ?? initialBatch())),
    [orderVids, shownCount],
  )

  /** ★★ `D105`：交给画布的**子集**（* 边只留两端都在集合里的）⚠ */
  const view = useMemo(() => {
    if (!g) return null
    const rank = new Map(orderVids.map((v, i) => [v, i]))
    const nodes = g.nodes
      .filter((n) => shownVids.has(n.vid))
      .sort((a, b) => (rank.get(a.vid) ?? 0) - (rank.get(b.vid) ?? 0))
    const edges = g.edges.filter((e) => shownVids.has(e.from) && shownVids.has(e.to))
    return { ...g, nodes, edges }
  }, [g, shownVids, orderVids])

  const selected = useMemo<GraphNode | null>(() => {
    if (!g || selectedVid == null) return null
    return g.nodes.find((n) => n.vid === selectedVid) || null
  }, [g, selectedVid])

  /** ★ kind 统计（* 图例按**全图**数据来，* ⛔ 不用子集误导）⚠ */
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
    if (!hit) {
      setHint(`没有找到「${q.trim()}」`)
      return
    }
    // ★★ `D107`：* 目标不在当前视图 ⇒* 先加进来，* ⛔ 不静默失败 ✅
    if (!shownVids.has(hit.vid)) {
      const rank = orderVids.indexOf(hit.vid)
      setShownCount(rank >= 0 ? Math.max(shownCount ?? 0, rank + 1) : (g?.nodes.length ?? 0))
    }
    setFocusVid(hit.vid)
    setSelectedVid(hit.vid)
    setHint('')
  }

  const addToPath = async (node: GraphNode) => {
    setHint('')
    try {
      await append.mutateAsync(node.vid)
      setHint(`已把「${node.name}」加入学习路径（第 ${pathItems.length + 1} 个）`)
    } catch (e) {
      setHint(errorMessage(e))
    }
  }

  const removeNode = async (node: GraphNode) => {
    setHint('')
    try {
      await removeFromPath.mutateAsync(node.vid)
      setHint(`已把「${node.name}」从学习路径移除`)
    } catch (e) {
      setHint(errorMessage(e))
    }
  }

  const move = async (index: number, dir: -1 | 1) => {
    const next = [...pathVids]
    const to = index + dir
    if (to < 0 || to >= next.length) return
    ;[next[index], next[to]] = [next[to], next[index]]
    try {
      await replace.mutateAsync(next)
    } catch (e) {
      setHint(errorMessage(e))
    }
  }

  const cleanStale = async () => {
    setHint('')
    try {
      await replace.mutateAsync(pathVids)
      setHint(`已清理 ${stale.length} 个失效节点`)
    } catch (e) {
      setHint(errorMessage(e))
    }
  }

  if (graph.isError || pathQ.isError) {
    return (
      <AppLayout title="图谱">
        <div className="card" style={{ padding: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>不存在或无权访问</div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
            {errorMessage(graph.error || pathQ.error)}
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

  const loading = graph.isLoading || pathQ.isLoading || !view

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
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
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
            {/* ★★ `D105`：加载更多 / 显示全部 */}
            {shownCount != null && shownCount < orderVids.length && (
              <Button
                icon={<ChevronDown size={13} />}
                onClick={() => setShownCount((c) => (c ?? 0) + BATCH_STEP)}
              >
                加载更多（还有 {orderVids.length - shownCount}）
              </Button>
            )}
            {shownCount != null && shownCount < orderVids.length && (
              <Button onClick={() => setShownCount(orderVids.length)}>显示全部</Button>
            )}
            {/* ★★ `D106`：学习路径面板 */}
            <Button
              variant={pathOpen ? 'primary' : 'ghost'}
              icon={<Route size={13} />}
              onClick={() => setPathOpen((v) => !v)}
            >
              学习路径（{pathItems.length}）
            </Button>
            <span className="faint" style={{ fontSize: 11.5, marginLeft: 'auto' }}>
              {g && `共 ${g.nodes.length} 节点 · ${g.edges.length} 边，已展示 ${view?.nodes.length ?? 0}`}
              {/* ★ 构建时间：* 用来判断浏览器加载的是不是最新包（* 见 vite define）⚠ */}
              {phase && <span style={{ color: 'var(--accent)' }}>{` · ${phase}`}</span>}
              <span style={{ opacity: 0.5 }}>
                {' · 构建 '}
                {(typeof __BUILD_TIME__ === 'string' ? __BUILD_TIME__ : '').slice(5, 16).replace('T', ' ')}
              </span>
              {g && (g.manualNodeCount > 0 || g.manualEdgeCount > 0) && (
                <span style={{ color: 'var(--warn)' }}>
                  {` · 其中人工补的 ${g.manualNodeCount + g.manualEdgeCount} 项`}
                </span>
              )}
            </span>
          </div>

          {/* ★★ `D107`：失效 vid 提示 + 一键清理（* ⛔ 不自动删）⚠ */}
          {stale.length > 0 && (
            <div
              className="card flex items-center gap-2 flex-wrap"
              style={{ padding: '8px 12px', marginBottom: 8, borderColor: 'var(--warn)' }}
            >
              <span style={{ fontSize: 12.5 }}>
                学习路径里有 <b>{stale.length}</b> 个节点已不在图中（代码可能变了）：
                <code style={{ marginLeft: 6, fontSize: 11 }}>{stale.slice(0, 5).join('、')}</code>
                {stale.length > 5 ? ' …' : ''}
              </span>
              <Button
                icon={<Trash2 size={12} />}
                style={{ marginLeft: 'auto' }}
                disabled={!canWrite || replace.isPending}
                onClick={cleanStale}
              >
                一键清理
              </Button>
            </div>
          )}

          {/* ★★ 没有路径时的提示（* 作者自己排；* 读者看到度数兜底）⚠ */}
          {!loading && !hasPath && (
            <div className="faint" style={{ fontSize: 11.5, marginBottom: 6 }}>
              作者还没有排学习路径 —— 现在按「连接数」展示前 {view?.nodes.length ?? 0} 个。
              {canWrite && '在节点面板点「加入路径」即可开始编排。'}
            </div>
          )}

          {hint && (
            <div className="faint" style={{ fontSize: 11.5, marginBottom: 6 }}>
              {hint}
            </div>
          )}

          {/* ★★ `D106`：路径面板（* 作者可排序，* 其他人只读）⚠ */}
          {pathOpen && (
            <div className="card" style={{ padding: 10, marginBottom: 8, maxHeight: 200, overflow: 'auto' }}>
              {pathItems.length === 0 ? (
                <div className="faint" style={{ fontSize: 12 }}>
                  还没有排学习路径 —— 在节点面板点「加入路径」开始。
                </div>
              ) : (
                pathItems.map((item, i) => (
                  <div
                    key={item.vid}
                    className="flex items-center gap-2"
                    style={{ padding: '3px 0', fontSize: 12 }}
                  >
                    <span className="faint" style={{ width: 22, textAlign: 'right' }}>
                      {i + 1}
                    </span>
                    <button
                      type="button"
                      style={{ cursor: 'pointer', background: 'none', border: 'none', color: 'var(--accent)' }}
                      onClick={() => {
                        setSelectedVid(item.vid)
                        setFocusVid(item.vid)
                      }}
                    >
                      {item.name}
                    </button>
                    <span className="faint" style={{ fontSize: 10.5 }}>
                      {item.file_path}:{item.line}
                    </span>
                    {canWrite && (
                      <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                        <button
                          type="button"
                          title="上移"
                          disabled={i === 0 || replace.isPending}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-sub)' }}
                          onClick={() => move(i, -1)}
                        >
                          <ChevronUp size={13} />
                        </button>
                        <button
                          type="button"
                          title="下移"
                          disabled={i === pathItems.length - 1 || replace.isPending}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-sub)' }}
                          onClick={() => move(i, 1)}
                        >
                          <ChevronDown size={13} />
                        </button>
                        <button
                          type="button"
                          title="移除"
                          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--err)' }}
                          onClick={() => removeNode({ vid: item.vid, name: item.name } as GraphNode)}
                        >
                          <X size={13} />
                        </button>
                      </span>
                    )}
                  </div>
                ))
              )}
            </div>
          )}

          <div
            className="card"
            style={{ flex: 1, minHeight: 0, overflow: 'hidden', padding: 0, position: 'relative' }}
          >
            {loading ? (
              <div className="flex items-center justify-center h-full gap-2">
                <Loader2 size={16} className="animate-spin" style={{ color: 'var(--text-sub)' }} />
                <span className="faint" style={{ fontSize: 12.5 }}>
                  正在拉取整张图（节点 / 边 / 补丁）…
                </span>
              </div>
            ) : view && view.nodes.length === 0 ? (
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
                graph={view}
                meteors={meteors}
                meteorSpeed={meteorSpeed}
                meteorSizeRatio={meteorSizeRatio}
                onPhase={setPhase}
                selectedVid={selectedVid}
                onSelect={setSelectedVid}
                onDeselect={() => setSelectedVid(null)}
                focusVid={focusVid}
              />
            )}
          </div>

          <div className="flex items-center gap-3 flex-wrap" style={{ marginTop: 8, fontSize: 11 }}>
            {kinds.map(([kind, count]) => (
              <span key={kind} className="flex items-center gap-1">
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    background: KIND_COLOR[kind] || '#94a3b8',
                    display: 'inline-block',
                  }}
                />
                <span className="faint">
                  {KIND_LABEL[kind] || kind} {count}
                </span>
              </span>
            ))}
            <span className="faint">◆ 菱形 = 人工补的节点</span>
          </div>
        </div>

        <div style={{ width: 340, flexShrink: 0 }}>
          <NodePanel
            projectRef={projectRef}
            node={selected}
            canWrite={canWrite}
            meUsername={meUsername}
            inPathOrdinal={selected ? ordinalOf.get(selected.vid) ?? null : null}
            canEditPath={canWrite}
            onAddToPath={selected ? () => addToPath(selected) : undefined}
            onRemoveFromPath={selected ? () => removeNode(selected) : undefined}
          />
        </div>
      </div>
    </AppLayout>
  )
}
