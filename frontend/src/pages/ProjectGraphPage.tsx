import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ChevronDown,
  ChevronUp,
  List,
  Loader2,
  Route,
  SlidersHorizontal,
  Maximize2,
  Minimize2,
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
import { useMediaQuery } from '../hooks/useMediaQuery'
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
  // ★★ 节点直径 28 ⇒ 一屏放不下太多（* 十几个就满，* 再多必然挤）⚠
  const area = (window.innerWidth || 1280) * (window.innerHeight || 720)
  return Math.max(10, Math.min(16, Math.round(area / 60000)))
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
  // ★ 节点直径（* 流星光晕随之等比缩放）⚠
  const nodeSizePx = Number(meteorConf['graph.node.size'] ?? 14)

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
  // ★ 悬浮工具条：* 默认收起，* 点开才展开（* 不占图谱高度）⚠
  const [barOpen, setBarOpen] = useState(false)
  // ★ 搜索胶囊是否展开
  const [searchOpen, setSearchOpen] = useState(false)
  // ★ 画布全屏（* 形似 code_network：右上角圆形按钮，* 全屏时隐藏右侧面板）⚠
  const [fullscreen, setFullscreen] = useState(false)
  // ★★ 写作区全屏（* 与图全屏**互斥**）——* 右侧面板占满整个主区 ⚠
  const [panelFull, setPanelFull] = useState(false)
  // ★★★ **移动端响应式**（* 窄屏 ⇒ 单列 + 写作区抽屉）⚠
  const isNarrow = useMediaQuery('(max-width: 900px)')
  // ★★★ 移动端 = **上下式**（* 照原型：图在上、* 写作区在下，* 占 62%）⚠
  //   · · ⛔ 不做右侧抽屉 ——* 所有者：「移动点就用上下式的，不就完了」⚠
  // ★★ 写作区宽度（* 可拖拽分隔条调整；* 单位 px）⚠
  const [panelWidth, setPanelWidth] = useState(340)
  const resizeRef = useRef<{ startX: number; startW: number } | null>(null)
  const mainRef = useRef<HTMLDivElement>(null)
  // ★★ 与所有者原型同口径：* 写作区最小 280、* 图谱最小 320 ——*
  //   * 上限是**动态**的（容器宽 − 图谱最小宽 − 分隔条），* ⛔ 不是写死的 680 ⚠
  const MIN_PANEL = 280
  const MIN_GRAPH = 320
  const RESIZER = 4

  const clampPanel = (w: number) => {
    const inner = mainRef.current?.clientWidth ?? window.innerWidth
    const max = Math.max(MIN_PANEL, inner - RESIZER - MIN_GRAPH)
    return Math.min(max, Math.max(MIN_PANEL, w))
  }

  // ★ 拖拽分隔条：向左拖 ⇒ 写作区变宽（* 上下限 280 ~ 680）⚠
  const onResizeStart = (e: React.PointerEvent) => {
    e.preventDefault()
    resizeRef.current = { startX: e.clientX, startW: panelWidth }
    window.addEventListener('pointermove', onResizeMove)
    window.addEventListener('pointerup', onResizeEnd)
  }
  const onResizeMove = (e: PointerEvent) => {
    if (!resizeRef.current) return
    const next = resizeRef.current.startW - (e.clientX - resizeRef.current.startX)
    setPanelWidth(clampPanel(next))
  }
  const onResizeEnd = () => {
    resizeRef.current = null
    window.removeEventListener('pointermove', onResizeMove)
    window.removeEventListener('pointerup', onResizeEnd)
  }
  useEffect(() => {
    const onWin = () => setPanelWidth((w) => clampPanel(w))
    window.addEventListener('resize', onWin)
    return () => {
      window.removeEventListener('resize', onWin)
      onResizeEnd()
    }
  }, [])
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
      <AppLayout page={false}>
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
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 0,
          padding: fullscreen ? 12 : '10px 16px 0',
          // ★★ 移动端用 `dvh`（* 动态视口高，* 避开地址栏伸缩）⚠
          height: fullscreen ? '100dvh' : 'calc(100dvh - var(--nav-h, 54px))',
          minHeight: fullscreen ? undefined : 520,
          ...(fullscreen
            ? { position: 'fixed', inset: 0, zIndex: 60, background: 'var(--surface)', padding: 12 }
            : {}),
        }}
      >
        {/* ★ 主区 **不留 gap**：* 间距全给分隔条，* 否则 12 + 6 会空出一条大缝 ⚠ */}
        <div
          ref={mainRef}
          style={{
            flex: 1,
            minHeight: 0,
            minWidth: 0,
            display: 'flex',
            flexDirection: isNarrow ? 'column' : 'row',
            gap: 0,
            position: 'relative',
          }}
        >
        {/* 写作区全屏时画布隐藏（* 两者互斥）⚠ */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: panelFull ? 'none' : 'flex',
            flexDirection: 'column',
            position: 'relative',
          }}
        >
          {/* ★★★ 左上角两颗胶囊（* 形似 code_network：悬浮、圆角、点开才展开，
              压在图谱上、不占高度）⚠ */}
          <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 30, display: 'flex', gap: 6 }}>
            {/* ---- 搜索 ---- */}
            <div
              onMouseLeave={() => setSearchOpen(false)}
              style={{ display: 'flex', gap: 6, alignItems: 'center' }}
            >
              <button
                type="button"
                className="card"
                onClick={() => setSearchOpen((v) => !v)}
                title="搜索节点（名字 / qname）"
                style={{
                  padding: isNarrow ? '4px 9px' : '5px 12px',
                  fontSize: isNarrow ? 11.5 : 12.5,
                  borderRadius: 999,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  cursor: 'pointer',
                  boxShadow: '0 2px 8px rgba(15,23,42,.14)',
                }}
              >
                <Search size={13} />
                {!searchOpen && <span>搜索</span>}
              </button>
              {searchOpen && (
                <input
                  className="input"
                  autoFocus
                  style={{ width: isNarrow ? 150 : 240, fontSize: 12.5 }}
                  placeholder="搜节点名 / qname，回车定位"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') search()
                  }}
                />
              )}
            </div>

            {/* ---- 工具 ---- */}
            <div
              onMouseLeave={() => setBarOpen(false)}
              style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}
            >
              <button
                type="button"
                className="card"
                onClick={() => setBarOpen((v) => !v)}
                title="工具"
                style={{
                  padding: isNarrow ? '4px 9px' : '5px 12px',
                  fontSize: isNarrow ? 11.5 : 12.5,
                  borderRadius: 999,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  cursor: 'pointer',
                  boxShadow: '0 2px 8px rgba(15,23,42,.14)',
                }}
              >
                <SlidersHorizontal size={13} />
                {!barOpen && <span>工具</span>}
              </button>
              {barOpen && (
                <div
                  className="card flex items-center gap-2 flex-wrap"
                  style={{
                    padding: 8,
                    maxWidth: isNarrow ? 'calc(100vw - 90px)' : 560,
                    boxShadow: '0 10px 28px rgba(0,0,0,.28)',
                  }}
                >
                  <Link to={`/p/${encodeURIComponent(projectRef)}`}>
                    <Button icon={<List size={13} />}>回列表</Button>
                  </Link>
                  <Button
                    variant={meteors ? 'primary' : 'ghost'}
                    icon={<Sparkles size={13} />}
                    onClick={() => setMeteors((v) => !v)}
                    title="节点之间飞过的流光效果"
                  >
                    流星
                  </Button>
                  {shownCount != null && shownCount < orderVids.length && (
                    <Button
                      icon={<ChevronDown size={13} />}
                      onClick={() => setShownCount((c) => (c ?? 0) + BATCH_STEP)}
                    >
                      加载更多（{orderVids.length - shownCount}）
                    </Button>
                  )}
                  {shownCount != null && shownCount < orderVids.length && (
                    <Button onClick={() => setShownCount(orderVids.length)}>显示全部</Button>
                  )}
                  <Button
                    variant={pathOpen ? 'primary' : 'ghost'}
                    icon={<Route size={13} />}
                    onClick={() => setPathOpen((v) => !v)}
                  >
                    学习路径（{pathItems.length}）
                  </Button>
                </div>
              )}
            </div>
          </div>

          {/* ★★★ 右上角：圆形全屏按钮（* 形似 code_network）⚠ */}
          <button
            type="button"
            className="card"
            onClick={() => {
              setFullscreen((v) => !v)
              setPanelFull(false)
            }}
            title={fullscreen ? '退出全屏' : '全屏'}
            style={{
              position: 'absolute',
              top: 10,
              right: 10,
              zIndex: 30,
              width: isNarrow ? 30 : 34,
              height: isNarrow ? 30 : 34,
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              cursor: 'pointer',
              boxShadow: '0 2px 10px rgba(15,23,42,.16)',
            }}
          >
            {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>

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
              <>
              {/* ★ 统计已移到页脚托底条（* 避免和图例叠在左下角）⚠ */}
                            <GraphCanvas
                graph={view}
                meteors={meteors}
                meteorSpeed={meteorSpeed}
                meteorSizeRatio={meteorSizeRatio}
                nodeSizePx={nodeSizePx}
                onPhase={setPhase}
                fullGraph={g}
                selectedVid={selectedVid}
                onSelect={setSelectedVid}
                onDeselect={() => setSelectedVid(null)}
                focusVid={focusVid}
              />
              </>
            )}
          </div>

        </div>

        {/* ★★ 左右拖动调整宽度（* 形似所有者原型的分隔条）⚠ */}
        {!fullscreen && !panelFull && !isNarrow && (
          <div
            onPointerDown={onResizeStart}
            title="拖动调整宽度"
            style={{
              width: 4,
              flexShrink: 0,
              cursor: 'col-resize',
              background: 'transparent',
              transition: 'background .15s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--accent)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          />
        )}

        {!fullscreen && (
        <div
          style={{
            width: isNarrow ? '100%' : panelFull ? undefined : panelWidth,
            flex: panelFull ? 1 : undefined,
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            minHeight: 0,
            position: 'relative',
            // ★★★ 窄屏 ⇒ **上下式**：* 占 62% 高、* 上圆角、* 压住图底边一点
            //   （* 照原型 .code-panel 在 @media(max-width:768px) 的写法）⚠
            ...(isNarrow
              ? {
                  height: panelFull ? undefined : '62%',
                  marginTop: -12,
                  zIndex: 5,
                  background: 'var(--surface)',
                  borderRadius: '14px 14px 0 0',
                  boxShadow: '0 -8px 24px rgba(15,23,42,.18)',
                  overflow: 'hidden',
                }
              : {}),
          }}
        >
          {/* ★★ 写作区全屏按钮（* 与图的右上角同款，* 两者互斥）⚠ */}
          <button
            type="button"
            className="card"
            onClick={() => {
              setPanelFull((v) => !v)
              setFullscreen(false)
            }}
            title={panelFull ? '退出全屏' : '写作区全屏'}
            style={{
              position: 'absolute',
              top: 6,
              right: 6,
              zIndex: 12,
              width: 30,
              height: 30,
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              cursor: 'pointer',
              boxShadow: '0 2px 10px rgba(15,23,42,.16)',
            }}
          >
            {panelFull ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
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
        )}
        </div>

        {/* ★★★ **托底状态条**（* 所有者：「我页面底下也有一块的，你写的界面没了，
            整个画布都是悬空的」）——* 一条固定高度，占住底部，画布不再悬空 ⚠ */}
        <div
          style={{
            // ★★ 用 `flex: 0 0 26px` 而不是 height ——* flex 容器里 height 会被拉伸 ⚠
            flex: '0 0 26px',
            marginTop: 6,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 11,
            color: 'var(--text-sub)',
            borderTop: '1px solid var(--card-border)',
            paddingLeft: 4,
            flexShrink: 0,
            // ★ 锁死高度：* 文字不换行、不撑高（* 否则托底条被内容顶成两行）⚠
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            maxHeight: 26,
          }}
        >
          {g && (
            <span>
              已展示 {view?.nodes.length ?? 0} / {g.nodes.length} 节点
            </span>
          )}
          {phase && <span style={{ color: 'var(--accent)' }}>{phase}</span>}
          <span style={{ marginLeft: 'auto', opacity: 0.55 }}>
            {g ? `${g.edges.length} 边` : ''}
            {g && (g.manualNodeCount + g.manualEdgeCount > 0
              ? ` · 人工补 ${g.manualNodeCount + g.manualEdgeCount} 项`
              : '')}
            {' · 构建 '}
            {(typeof __BUILD_TIME__ === 'string' ? __BUILD_TIME__ : '').slice(5, 16).replace('T', ' ')}
          </span>
        </div>
      </div>
    </AppLayout>
  )
}
