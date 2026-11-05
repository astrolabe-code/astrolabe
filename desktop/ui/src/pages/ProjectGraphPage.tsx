import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {ChevronDown,
  ChevronUp,
  List,
  Loader2,
  Route,
  SlidersHorizontal,
  Maximize2,
  Minimize2,
  Search,
  Trash2,
  Workflow,
  X,
  GitBranch,
  Share2,
} from 'lucide-react'
import type { GraphNode } from '../lib/mergeGraph'
import { errorMessage } from '../api/errors'
import CuratePanel from '../components/graph/CuratePanel'
import { useFullGraph } from '../query/graph'
import { useProject } from '../query/projects'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { getMeteors } from '../lib/uiPrefs'
import {
  useAppendToPath,
  useReadingPath,
  useRemoveFromPath,
  useReplacePath,
} from '../query/readingPath'
import AppLayout from '../components/AppLayout'
import TopbarSlot from '../components/TopbarSlot'
import AppMenuItems from '../components/AppMenuItems'
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
// ★ 类型名与颜色统一来自 `lib/kindLabel`（⛔ 页面里不再另写一份）

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
  // ★★★ 2026-11-05：个人版**没有"用户设置"**（那是网页版账号体系的东西）
  //   ⇒ 流星参数用固定值（与网页版的默认档一致），不再请求 `/api/me/settings/`
  const meteorSpeed = 0.005 // ×1000 存储的那个 5，换算成 0.005
  const meteorSizeRatio = 0.25 // 25%
  const nodeSizePx = 14

  // ★★ 从节点列表点过来时带着 `?node=<vid>`：
  //    要**以它为焦点**展示（它 + 直接邻居），⛔ 不是默认那 16 个 ⚠
  const [sp] = useSearchParams()
  const deepVid = Number(sp.get('node') || 0) || null
  const navigate = useNavigate()

  const [selectedVid, setSelectedVid] = useState<number | null>(deepVid)
  // ★★ `D104`：* 流星轨迹开关（* 默认开；* 嫌吵能关）⚠
  // ★ 默认跟用户设置走；* 工具栏开关只是本次会话的临时覆盖 ⚠
  // ★ 流星开关来自「设置 → 外观」（`lib/uiPrefs`）；图谱页不再提供开关 ⚠
  const [meteors] = useState(() => getMeteors())
  const [focusVid, setFocusVid] = useState<number | null>(null)
  const [q, setQ] = useState('')
  // ★★ `D105`：* 已展示多少个（* null = 还没初始化 ⇒* 用 initialBatch()）
  const [shownCount, setShownCount] = useState<number | null>(null)
  const [pathOpen, setPathOpen] = useState(false)
  // ★ 悬浮工具条：* 默认收起，* 点开才展开（* 不占图谱高度）⚠
  const [barOpen, setBarOpen] = useState(false)
  /** ★★ 改图抽屉（个人版核心兜底能力）⚠ */
  const [curateOpen, setCurateOpen] = useState(false)
  // ★ 搜索胶囊是否展开
  const [searchOpen, setSearchOpen] = useState(false)
  // ★★ 依赖线（imports / includes）默认**不显示** ⚠
  //   · 文件级依赖对"读一个函数"帮助有限，一屏几十条会把主干糊住
  //   · 需要看模块边界时点「依赖」打开
  const [showImports, setShowImports] = useState(false)
  // ★ 画布全屏（* 形似 code_network：右上角圆形按钮，* 全屏时隐藏右侧面板）⚠
  const [fullscreen, setFullscreen] = useState(false)
  // ★★ 写作区全屏（* 与图全屏**互斥**）——* 右侧面板占满整个主区 ⚠
  const [panelFull, setPanelFull] = useState(false)
  // ★★★ **移动端响应式**（* 窄屏 ⇒ 单列 + 写作区抽屉）⚠
  const isNarrow = useMediaQuery('(max-width: 900px)')
  // ★★★ 移动端 = **上下式**（* 照原型：图在上、* 写作区在下）⚠
  //   · · ★ 可**上下拖拽**调高度（* 抓手条 / 标题区，* 25%~85%）✅
  //   · · ★ 可**收起**（* 高度 0 + 过渡动画）；* 选中节点自动展开 ✅
  const [panelPct, setPanelPct] = useState(62)
  const [panelCollapsed, setPanelCollapsed] = useState(false)
  const [panelDragging, setPanelDragging] = useState(false)
  const gripRef = useRef<{ startY: number; startPct: number } | null>(null)
  // ★★ 拖拽过就不能再触发 onClick（* 否则松手瞬间被当点击 ⇒ 面板收起）⚠
  const didDragRef = useRef(false)

  const onGripDown = (e: React.PointerEvent) => {
    e.preventDefault()
    didDragRef.current = false
    if (panelCollapsed) {
      setPanelCollapsed(false)
      gripRef.current = { startY: e.clientY, startPct: panelPct }
    } else {
      gripRef.current = { startY: e.clientY, startPct: panelPct }
    }
    setPanelDragging(true)
    window.addEventListener('pointermove', onGripMove)
    window.addEventListener('pointerup', onGripUp)
  }
  const onGripMove = (e: PointerEvent) => {
    if (!gripRef.current) return
    // 移动超过 3px 才算拖拽（* 避免手抖被当点击）
    if (Math.abs(e.clientY - gripRef.current.startY) > 3) didDragRef.current = true
    const h = mainRef.current?.clientHeight ?? window.innerHeight
    const d = ((gripRef.current.startY - e.clientY) / h) * 100
    // ★★ 上限 **100%**（* 所有者：「向上提升可以把图谱高度挤没的」）⚠
    setPanelPct(Math.min(100, Math.max(15, gripRef.current.startPct + d)))
  }
  const onGripUp = () => {
    gripRef.current = null
    setPanelDragging(false)
    window.removeEventListener('pointermove', onGripMove)
    window.removeEventListener('pointerup', onGripUp)
  }

  // ★ 窄屏选中节点 ⇒ 自动展开写作区（* 原型：点头像节点弹面板）⚠
  useEffect(() => {
    if (isNarrow && selectedVid != null) setPanelCollapsed(false)
  }, [isNarrow, selectedVid])
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
  // ★ 个人版：没有身份，能打开就能改图
  const canWrite = true

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
    // ★★★ 2026-11-05：**默认展示全部**（「加载更多 / 显示全部」已从菜单删除）
    //   ⚠ 仍留 shownCount 这个通道：搜索定位到更靠后的节点时会临时扩大（见 search()）
    if (shownCount == null) setShownCount(orderVids.length || g?.nodes.length || 0)
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

    // ★★ 焦点：`?node=` 指定时，它和**直接相连的节点**排最前
    //   （所有者：「点击列表，就跳转到展示相应节点，以及其直接连接节点的图谱」）
    const focus: number[] = []
    if (deepVid != null && inGraph.has(deepVid)) {
      focus.push(deepVid)
      for (const e of g.edges) {
        if (e.from === deepVid && inGraph.has(e.to)) focus.push(e.to)
        else if (e.to === deepVid && inGraph.has(e.from)) focus.push(e.from)
      }
    }

    const head = [
      ...(hasPath ? pathVids.filter((v) => inGraph.has(v)) : []),
      ...focus,
    ]
    const headSet = new Set(head)
    const tail = [...g.nodes]
      .filter((n) => !headSet.has(n.vid))
      .sort((a, b) => (deg.get(b.vid) || 0) - (deg.get(a.vid) || 0) || a.vid - b.vid)
      .map((n) => n.vid)
    return [...head, ...tail]
  }, [g, hasPath, pathVids, deepVid])

  const shownVids = useMemo(
    () => new Set(orderVids.slice(0, shownCount ?? orderVids.length)),
    [orderVids, shownCount],
  )

  /** ★★ 焦点视图：`?node=` 给的节点 + **直接邻居**（⛔ 不多拉无关节点）⚠
   *  · · 否则补满 16 个时，一屏全是它 import 的头文件，反而看不清主干 */
  const focusVids = useMemo(() => {
    if (!g || deepVid == null) return [] as number[]
    const inGraph = new Set(g.nodes.map((n) => n.vid))
    if (!inGraph.has(deepVid)) return []
    const out = [deepVid]
    for (const e of g.edges) {
      if (e.from === deepVid && inGraph.has(e.to)) out.push(e.to)
      else if (e.to === deepVid && inGraph.has(e.from)) out.push(e.from)
    }
    return [...new Set(out)]
  }, [g, deepVid])

  // ★ 深链焦点：只展示「它 + 直接邻居」（正好这么多，不多也不少）
  useEffect(() => {
    if (deepVid == null || !g) return
    if (focusVids.length) setShownCount(focusVids.length)
    setSelectedVid(deepVid)
  }, [deepVid, g, focusVids.length])


  /** ★★ `D105`：交给画布的**子集**（* 边只留两端都在集合里的）⚠ */
  const view = useMemo(() => {
    if (!g) return null
    const rank = new Map(orderVids.map((v, i) => [v, i]))
    const nodes = g.nodes
      .filter((n) => shownVids.has(n.vid))
      .sort((a, b) => (rank.get(a.vid) ?? 0) - (rank.get(b.vid) ?? 0))
    const edges = g.edges
      .filter((e) => shownVids.has(e.from) && shownVids.has(e.to))
      // ★ 依赖线默认隐藏（`showImports` 打开才画）
      .filter((e) => showImports || (e.type !== 'imports' && e.type !== 'includes'))
    return { ...g, nodes, edges }
  }, [g, shownVids, orderVids, showImports])

  // ★★★ 2026-11-05：**默认选中第一个节点**（所有者要求图谱页与列表页一致）
  //   排序口径与"首批展示"相同（路径优先 → 度数高优先）⇒ 选中的就是左栏第一个
  //   ⚠ 只做一次：用户点过 / 深链带了 ?node=，之后不再干预
  const autoPickedRef = useRef(false)
  useEffect(() => {
    if (autoPickedRef.current) return
    if (selectedVid != null) {
      autoPickedRef.current = true
      return
    }
    if (!g || orderVids.length === 0) return
    autoPickedRef.current = true
    setSelectedVid(orderVids[0])
  }, [g, orderVids, selectedVid])

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
      {/* ★★★ 工具条挂在**顶栏那一行**（画布上不再有浮层）⚠ */}
      <TopbarSlot>
          {/* ★★★ 2026-11-05：工具条从"悬浮"改为**内容流里的一条** ⚠
              所有者：「样子怪不说，还挡住了后面的字」——原来是 absolute 压在图谱上，
              正好盖住上面那句"作者还没有排学习路径…"的提示
              ⇒ 现在：① 不悬浮（把提示文字顶下去） ② 去掉胶囊/阴影（Obsidian 那种
                 扁平图标按钮，悬停才出现浅底） */}
          <div className="graph-toolbar">
            {/* ★★★ 2026-11-05：**按类归组 + 折叠**（所有者：「能合为一类的合为一类，
                并折叠，就像一些编程IDE做的那样」）⚠
                · 左组：导航（列表）· 编辑（改图）· 工具（视图开关全收进下拉）
                · 右组：搜索（单独留在最右，展开时变成输入框）
                ⛔ 不再把「依赖 / 流星 / 加载更多 / 学习路径」平铺成一排 ⚠ */}
            <div className="rail-group">
              {/* ---- 导航 ---- */}
              <button
                type="button"
                className="rail-btn"
                onClick={() => navigate(`/p/${encodeURIComponent(projectRef)}`)}
                title="回到节点列表（可以从头找）"
              >
                <List size={13} />
                {!isNarrow && <span>列表</span>}
              </button>

              {/* ---- 编辑 ---- */}
              <button
                type="button"
                className="rail-btn"
                onClick={() => setCurateOpen(true)}
                title="改图：解析不准的地方在这里补"
              >
                <GitBranch size={13} />
                {!isNarrow && <span>改图</span>}
              </button>

              {/* ---- 工具（视图开关都收在这里，折叠不占位）---- */}
              <div
                onMouseLeave={() => setBarOpen(false)}
                style={{ position: 'relative', display: 'flex' }}
              >
                <button
                  type="button"
                  className="rail-btn"
                  onClick={() => setBarOpen((v) => !v)}
                  aria-pressed={barOpen}
                  title="工具：依赖线 / 流星 / 学习路径 / 加载更多"
                >
                  <SlidersHorizontal size={13} />
                  {!isNarrow && <span>工具</span>}
                  <ChevronDown size={11} style={{ opacity: 0.6 }} />
                </button>

                {barOpen && (
                  <div className="rail-menu">
                    {/* ★★★ 2026-11-05：菜单**不放图标**（所有者：「你把下拉栏都加图标干啥？」）
                        ⚠ 「流星」移到 设置 → 外观；「加载更多 / 显示全部」删除（不需要手动点） */}
                    <Button
                      variant={showImports ? 'primary' : 'ghost'}
                      onClick={() => setShowImports((v) => !v)}
                      title="文件之间的 import / include 连线（默认关，会糊住主干）"
                    >
                      依赖线
                    </Button>
                    <Button
                      variant={pathOpen ? 'primary' : 'ghost'}
                      onClick={() => setPathOpen((v) => !v)}
                    >
                      学习路径（{pathItems.length}）
                    </Button>
                    <span className="rail-menu-sep" />
                    <AppMenuItems />
                  </div>
                )}
              </div>
            </div>

          </div>

      </TopbarSlot>

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
            ? { position: 'fixed', inset: 0, zIndex: 60, background: 'var(--card)', padding: 12 }
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
            // ★★★ 必须 `minHeight:0` ——* flex 列里默认 `min-height:auto`，
            //   * 图区会被 canvas 撑住、* 挤不下去（* 写作区上提时图不缩）⚠
            minHeight: 0,
            display: panelFull ? 'none' : 'flex',
            flexDirection: 'column',
            position: 'relative',
          }}
        >
          {/* ★★★ 左上角两颗胶囊（* 形似 code_network：悬浮、圆角、点开才展开，
              压在图谱上、不占高度）⚠ */}
          {/* ★★★ 右上角：圆形全屏按钮（* 形似 code_network）⚠ */}
          <button
            type="button"
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
              // ★★ 所有者：「两个全屏按钮不要整阴影之类的装饰，看着怪怪的」⚠
              //   ⇒ ⛔ 不用 `.card`（它带 box-shadow: --shadow-card）、⛔ 无任何阴影
              //   ⇒ 只留**白底 + 1px 细边框** ✅
              background: 'var(--card)',
              border: '1px solid var(--card-border)',
              color: 'var(--text-sub)',
              boxShadow: 'none',
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
            // ★★★ 窄屏 ⇒ **两个平行盒子**（* 所有者：「写作区与图谱区是两个平行的
            //   盒子。提上去使用下面写作区的盒子把上面图谱区的盒子的高度挤掉，
            //   就像覆盖一样了」）⚠
            //   · · ★ 写作区 `height` 变大 ⇒ 图区（flex:1）**自动被挤矮** ✅
            //   · · ★ `marginTop:-12` + 上圆角 + 阴影 = 视觉上"浮在图上" ✅
            // ★★★ 桌面端：* 写作区**本身就是一整块白色面板**（* 即使没选节点）——
            //   · · 所有者：「右边写作区没有白色内容，能看见背景，但是呢，却有全屏
            //     按钮？全屏按钮不应该和白色面版区一起的吗？本来就是全屏白色面版区」
            //   · · ⇒ 背景/圆角/边框**由容器统一给**，* NodePanel 不再自己画卡片 ⚠
            ...(isNarrow
              ? {
                  // ★ 收起时只留抓手高度（* 否则抓手被裁掉、再也拉不开）⚠
                  height: panelFull ? undefined : panelCollapsed ? 22 : `${panelPct}%`,
                  marginTop: panelCollapsed || panelPct >= 99 ? 0 : -12,
                  zIndex: 5,
                  background: 'var(--card)',
                  // ★★ 所有者：「写作区与图谱区，就用一条横线分割就行，不要整些阴影效果」
                  //   ⇒ * 无圆角、* 无阴影，* 只留 1px 上边框 ⚠
                  borderTop: panelCollapsed ? 'none' : '1px solid var(--card-border)',
                  borderRadius: 0,
                  boxShadow: 'none',
                  overflow: 'hidden',
                  transition: panelDragging
                    ? 'none'
                    : 'height .32s cubic-bezier(.25,.8,.35,1), margin-top .32s ease',
                }
              : {
                  background: 'var(--card)',
                  borderRadius: 12,
                  border: '1px solid var(--card-border)',
                  overflow: 'hidden',
                }),
          }}
        >
          {/* ★★ 写作区全屏按钮（* 与图的右上角同款，* 两者互斥）⚠ */}
          <button
            type="button"
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
              // ★★ 同图全屏：⛔ 无阴影、⛔ 不用 .card ⚠
              background: 'var(--card)',
              border: '1px solid var(--card-border)',
              color: 'var(--text-sub)',
              boxShadow: 'none',
            }}
          >
            {panelFull ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          {isNarrow && !panelFull && (
            <>
              {/* ★★ 抓手条：* 按住上下拖 = 调高度；* 点一下 = 收起/展开 ⚠ */}
              <div
                onPointerDown={onGripDown}
                onClick={() => {
                  // ★ 拖拽结束的那次 click 不算（* 否则一拖就收起）⚠
                  if (didDragRef.current) {
                    didDragRef.current = false
                    return
                  }
                  setPanelCollapsed((v) => !v)
                }}
                style={{
                  height: 22,
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'grab',
                  touchAction: 'none',
                  // ★ 手指友好：* 上下各留 4px 命中区
                  padding: '4px 0',
                  // ★ 原型 .panel-grip：* 4px 圆角横条
                }}
              >
                <div
                  style={{
                    width: 36,
                    height: 4,
                    borderRadius: 2,
                    background: 'var(--card-border)',
                  }}
                />
              </div>
            </>
          )}
          <NodePanel
            projectRef={projectRef}
            node={selected}
            canWrite={canWrite}
            inPathOrdinal={selected ? ordinalOf.get(selected.vid) ?? null : null}
            canEditPath={canWrite}
            flat
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

      {/* ★★ 改图抽屉（解析不准的地方在这里补）⚠ */}
      <CuratePanel
        open={curateOpen}
        projectRef={projectRef}
        nodes={graph.data?.nodes ?? []}
        onClose={() => setCurateOpen(false)}
        onChanged={() => void graph.refetch()}
        canReparse={!(project.data as unknown as { is_blank?: boolean })?.is_blank}
        blank={!!(project.data as unknown as { is_blank?: boolean })?.is_blank}
      />
    </AppLayout>
  )
}
