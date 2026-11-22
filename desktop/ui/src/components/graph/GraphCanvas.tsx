import { useEffect, useMemo, useRef, useState } from 'react'
import Sigma from 'sigma'
import DirectedGraph from 'graphology'
import forceAtlas2 from 'graphology-layout-forceatlas2'
import { startMeteor } from '../../lib/meteorFx'
import type { EffectiveGraph, GraphEdge, GraphNode } from '../../lib/mergeGraph'
import { kindColor } from '../../lib/kindLabel'
import {
  nodePos, toGraph, toViewport, zoomOf, setStates, applyVisual,
  nodeSizeOf, nodeColorOf, addNode, addEdge, dropNodes, focusOn,
} from '../../lib/sigmaBridge' 
import NodeHoverCard from '../node/NodeHoverCard'
import { useAiBusy } from '../../lib/aiBusy'
import EdgeHoverCard from './EdgeHoverCard'

/**
 * ★★ 节点标签的最大字符数（超出用 `…` 截断）
 *
 * 所有者原话（2026-11-14）：
 * 「图上标全长的函数名，节点一多，就继承密密麻麻的字符了，可以设置一个
 *   最大字符长度，超出了的部分用...表示」
 *
 * 为什么按类型给不同上限：
 *   · 文件名/目录名是「定位信息」，长一点也值得看清（`test_call_graph.py`）
 *   · 函数名只需辨认，截短后靠 hover 浮窗看全名，不丢信息
 */
const LABEL_MAX_NAME = 16
const LABEL_MAX_FILE = 22

function truncateLabel(text: string, max: number): string {
  const t = (text || '').trim()
  return t.length > max ? `${t.slice(0, max)}…` : t
}

/** 缩放低于它就进入「只显示关键标签」模式（借鉴 sigma 的 labelRenderedSizeThreshold） */
const LABEL_ZOOM_THRESHOLD = 0.7
/** 节点少于这么多时不启用（小图上标签本来就不挤） */
const LABEL_MIN_NODES = 30
/** 密集模式下最多保留多少个「度数最高」的标签 */
const LABEL_TOP_DEGREE = 12

/**
 * ★★ 鼠标离开节点后，浮窗再多留一小会儿（ms）
 *
 * 所有者原话（2026-11-17）：
 * 「只需要在节点里可以移动到弹窗的定时器就行，离开节点，弹窗立刻消失」
 *
 * ⇒ 这是**唯一**一个定时器，只为了一件事：让鼠标能跨过节点与浮窗之间
 *   那十几像素的空白去点「挑战问题」。除此之外任何离开都立即消失。
 */
const HOVER_LINGER_MS = 800

/** 点到线段的距离（画布单位），用来判定鼠标是否落在某条聚合边上 */
function distToSegment(p: ArrayLike<number>, a: ArrayLike<number>, b: ArrayLike<number>): number {
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  const l2 = dx * dx + dy * dy
  if (!l2) return Math.hypot(p[0] - a[0], p[1] - a[1])
  let t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
}

/**
 * ★ 图谱画布（`D98` · AntV G6 v5）
 *
 * ## ★★ 所有者口径（原话）
 *
 * > 「**现在图要用 G6 画，不要用 vis-network 了。**」
 * > 「**先用两三秒调整布局，最后再根据稳定的布局，加上 canvas 的流星效果。**」
 *
 * ## ★★ 三个时间点（* 一次说清，* 别再乱）
 *
 * ```
 * t=0      建图：* 节点先排成**小圆环**聚在画布中心（* 肉眼能看到"聚"）
 * t≈2.5s   fruchterman 散开到位 ⇒ fitView + fitCenter ⇒ 通知「布局完成」
 * t≈2.6s   流星启动（* 等布局稳了才画，* 否则位置乱窜）
 * ```
 *
 * ## ★★ 四条必须遵守的实现约束（* 都是踩过的坑）
 *
 * ```
 * ① ★ `animation` 必须**开**，否则布局过渡是瞬时的（看不到散开）
 * ② ★★ `animation: true` 时 **`g.render()` 的 promise 永不 resolve** ——
 *     ⛔ 绝对不能 `await` / `.then()`，否则后面全都不执行（* 流星因此消失过）⚠
 * ③ ★ 初始位置**不能全重叠在一点** —— fruchterman 散不开（* 斥力方向不定）；
 *     排成半径 70 的小圆环，* 视觉上仍是"聚在中心" ✅
 * ④ ★ 容器必须 `position: relative` —— 流星罩层是 absolute;inset:0 ⚠
 * ```
 */

// ★ 颜色统一来自 lib/kindLabel（图谱 / 列表 / 面板三处必须一致）

const colorOf = (n: GraphNode) => kindColor(n.kind)

/** ★★ 环形按钮几何（Neo4j 风格）：* 内径 24、外径 42、画布 96 ——
 *   环绕节点一圈，分左右两段弧形扇区 ⚠ */
const RING_GEO = { c: 48, r1: 24, r2: 42 }

/** 生成一段环形扇区路径（* 角度 0 = 向右，* 正方向顺时针，* 与 SVG 一致） */
function ringArcPath(a1: number, a2: number): string {
  const { c, r1, r2 } = RING_GEO
  const pt = (r: number, a: number) => [c + r * Math.cos(a), c + r * Math.sin(a)] as const
  const [x1, y1] = pt(r2, a1)
  const [x2, y2] = pt(r2, a2)
  const [x3, y3] = pt(r1, a2)
  const [x4, y4] = pt(r1, a1)
  const large = a2 - a1 > Math.PI ? 1 : 0
  return [
    `M ${x1.toFixed(2)} ${y1.toFixed(2)}`,
    `A ${r2} ${r2} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`,
    `L ${x3.toFixed(2)} ${y3.toFixed(2)}`,
    `A ${r1} ${r1} 0 ${large} 0 ${x4.toFixed(2)} ${y4.toFixed(2)}`,
    'Z',
  ].join(' ')
}

/** 初始圆环半径（px）—— 小到看起来"聚在中心"，又大到能让布局散开 */
const RING = 70
/** 布局散开 + 适配的时间（ms） */
const SETTLE_MS = 2500

interface GraphCanvasProps {
  /** ★★ 高亮一组节点（执行流用）：传空数组表示清除 */
  highlightVids?: number[]
  graph?: EffectiveGraph
  /** 选中节点 vid（受控） */
  selectedVid?: number | null
  onSelect: (vid: number) => void
  /** 点空白处 */
  onDeselect?: () => void
  /** 搜索聚焦（* 只移动视口，* 不改选中） */
  focusVid?: number | null
  /** 流星开关（* 默认开） */
  meteors?: boolean
  /** ★ 流星速度：* 每帧相位增量（* 来自用户设置，* 越小越慢）⚠ */
  meteorSpeed?: number
  /** ★ 流星大小：* 头部直径 / 节点直径（* 0.25 = 1/4）⚠ */
  meteorSizeRatio?: number
  /** ★ 节点直径（px，* 默认 14；* 来自用户设置）⚠ */
  nodeSizePx?: number
  /** 阶段回调（* 供页面显示"布局动画中 / 布局完成 / 流星已启动"） */
  onPhase?: (phase: string) => void
  /** ★★ 完整图（* 环形按钮展开邻居时要从这里查——* `graph` 只是已展示子集）⚠ */
  fullGraph?: EffectiveGraph
  /** ★ 发生增删后通知页面（* 用于统计展示数）⚠ */
  onGraphChanged?: () => void
}

export default function GraphCanvas({
  graph,
  selectedVid,
  highlightVids,
  onSelect,
  onDeselect,
  focusVid,
  meteors = true,
  meteorSpeed,
  meteorSizeRatio,
  nodeSizePx = 28,
  onPhase,
  fullGraph,
  onGraphChanged,
}: GraphCanvasProps) {
  // ★★★ 节点标签颜色：**读 CSS 变量 + 作为建图依赖** ⚠
  //   · · ★ 试过 `updateNodeData` 逐节点改 ——* G6 这条增量路径对节点样式不生效
  //     （* 改完 `getElementRenderStyle` 仍是旧值）⚠
  //   · · ★★ 最终做法：* 颜色一变就**重建图**（* 代价是重跑一次布局，
  //     * 但主题切换不频繁，* 正确性优先）✅
  const labelColorRef = useRef<string>('')
  const readLabelColor = () =>
    getComputedStyle(document.documentElement).getPropertyValue('--text-main').trim() || '#000000'
  if (!labelColorRef.current) labelColorRef.current = readLabelColor()
  const [labelColor, setLabelColor] = useState<string>(labelColorRef.current)

  useEffect(() => {
    const sync = () => {
      const v = readLabelColor()
      setLabelColor((prev) => (prev === v ? prev : v))
    }
    const mo = new MutationObserver(sync)
    mo.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
    const t1 = window.setTimeout(sync, 50)
    const t2 = window.setTimeout(sync, 200)
    return () => {
      mo.disconnect()
      window.clearTimeout(t1)
      window.clearTimeout(t2)
    }
  }, [])

  /**
   * ★ AI 回答中：画布不接收鼠标（点节点、拖拽都停），
   *   但问答区照常可用（用户要能滚动看输出）。
   */
  const aiBusy = useAiBusy()
  const boxRef = useRef<HTMLDivElement>(null)
  /** sigma 实例（替代 G6 gRef） */
  const gRef = useRef<Sigma | null>(null)
  /** graphology 图数据（sigma 的单一数据源） */
  const graphRef = useRef<DirectedGraph | null>(null)
  /** 上一轮高亮过的节点 id（换链时要先清掉，否则残留） */
  const flowIdsRef = useRef<string[]>([])
  const selectedRef = useRef<number | null>(null)
  /** 布局是否已稳定（* 0 = 还没有；存时刻） */
  const readyRef = useRef(0)
  // ★★ 环形操作按钮（* Neo4j 风格）：* 点节点后浮在它周围，* 跟随拖拽/缩放 ⚠
  // ★★ 悬停浮窗（所有者：图谱上鼠标移上去就显示详情，⛔ 不打断阅读、不用点开右栏）
  /** 与 NodeHoverCard.CARD_W 保持一致（用于判断浮窗翻到哪一侧） */
  const CARD_W = 440
  const [hover, setHover] = useState<{ node: GraphNode; x: number; y: number } | null>(null)
  const [edgeHover, setEdgeHover] = useState<{ edge: GraphEdge; x: number; y: number } | null>(null)
  /**
   * ★★ 浮窗保持：鼠标从节点移向浮窗时会先离开画布，若立刻清掉 hover，
   *   浮窗就消失、里面的「挑战问题」按钮永远点不到。
   *   ⇒ 离开延迟 150ms；这期间浮窗的 mouseenter 会把 cardHoverRef 置真。
   */
  const cardHoverRef = useRef(false)
  const leaveTimerRef = useRef(0)
  /** 与 `hover` 同步：`update` 是闭包，读不到最新 state，用它判断「是否刚离开节点」 */
  const hoverRef = useRef<{ node: GraphNode; x: number; y: number } | null>(null)
  /** ★ 同步写 hover：方向判断要拿即时值，⛔ 不等 useEffect 那一帧 */
  const setHoverSync = (v: { node: GraphNode; x: number; y: number } | null) => {
    hoverRef.current = v
    setHover(v)
  }
  /** 上一帧指针位置：用来判断「是不是朝右下（弹窗方向）走」 */
  const prevPtRef = useRef({ x: 0, y: 0 })
  const [ring, setRing] = useState<{ id: string; x: number; y: number } | null>(null)
  const [ringScale, setRingScale] = useState(1)
  const ringRef = useRef<SVGSVGElement>(null)
  // ★★★ **当前可见节点集合**（* 单一数据源）——
  //   · · ★ 增删节点时同步维护；* 一切"这个节点还在吗"都查它 ⚠
  //   · · ★★ 照原型 `visible.some(n => n.id === id)` 的写法：
  //     * **用数据判断**，* 而不是 try/catch 兜 G6 抛的异常 ✅
  const visibleRef = useRef<Set<string>>(new Set())
  /**
   * ★★ 节点的**实时**信息表（画布上出现过的全部节点，含"展开邻居"临时加进来的）⚠
   *
   * ⚠ 不能用 `graph.nodes` 推出来的 `nodeById`：
   *   `expandNeighbors` 是**直接往 G6 里加**节点/边（不跑布局、不改页面状态），
   *   那些节点不在 `graph.nodes` 里 ⇒ 悬停查不到 → 没有浮窗（所有者踩到）
   */
  const nodeInfoRef = useRef<Map<string, GraphNode>>(new Map())
  /** ★★ 画布数据版本：加/删节点与边之后 +1 ⇒ 流星按**实时数据**重建 ⚠ */
  const [dataVersion, setDataVersion] = useState(0)
  // ★ 节点的 size / color：* 节点渲染与流星共用（* 流星大小 = 直径 1/10、颜色 = 节点色）⚠
  // ★ 手工补的节点略大 15%，* 其余按设置值（* 流星光晕随之等比缩放）⚠
  const nodeSize = (n: GraphNode) =>
    n.origin === 'manual' ? Math.round(nodeSizePx * 1.15) : nodeSizePx
  const nodeById = useMemo(
    () => new Map((graph?.nodes ?? []).map((n) => [String(n.vid), n])),
    [graph],
  )

  // ============================================================ 悬停浮窗
  /**
   * ★★ 鼠标移到节点上 ⇒ 浮窗显示详情（名字 / 类型 / 签名 / 文件行号）⚠
   *
   * 所有者原话（2026-11-01）：
   * 「不用这么复杂，图谱上，在鼠标移到相应节点时就一个浮窗，显示相应详细信息，
   *   列表哪里也是一样。」
   *
   * ## 为什么用**原生 pointermove + 距离判定**，而不用 G6 的 `node:pointerenter`
   *
   * ```
   * G6 的事件走它自己的画布拾取，合成事件（自动化测试里）到不了 ⇒ 无法验证
   * 原生监听 + getCanvasByViewport 换算 + 最近节点判断：
   *   可测、可控、和 G6 版本解耦（它换事件系统也不影响我们）
   * ```
   *
   * ⚠ 只在命中半径内才弹（`节点直径/2 + 4`）⇒ 不会满屏乱弹
   */
  useEffect(() => {
    const box = boxRef.current
    if (!box || !graph) return

    let raf = 0
    let last: PointerEvent | null = null

    const update = () => {
      raf = 0
      const sigma = gRef.current
      const G = graphRef.current
      if (!sigma || !G || !last) return
      const rect = box.getBoundingClientRect()
      let p: { x: number; y: number }
      try {
        p = toGraph(sigma, last.clientX - rect.left, last.clientY - rect.top)
      } catch {
        return
      }
      let bestId = ''
      let bestD = Infinity
      for (const id of visibleRef.current) {
        const pos = nodePos(G, id)
        if (!pos) continue
        const d = Math.hypot(pos.x - p.x, pos.y - p.y)
        if (d < bestD) {
          bestD = d
          bestId = id
        }
      }
      const n = bestId ? nodeInfoRef.current.get(bestId) : undefined
      // ★ 半径用画布单位（节点 size 就是画布单位），不随缩放漂
      const hit = !!n && bestD <= nodeSizePx / 2 + 4
      if (hit && n) {
        // ★★★ 进入节点必须**先取消**上一次离开挂起的清空定时器！
        //   ⛔ 否则：从上个节点/空白移进来时，那次离开的 timer 还在跑，
        //   鼠标一停下它就到期，把刚出现的浮窗清掉（表现为「过几秒自己消失」）。
        window.clearTimeout(leaveTimerRef.current)
        // ★★★ 位置策略（所有者 2026-11-17）：
        //   「鼠标向左向上，弹窗就跟着走，向右下就定住，不就完了。
        //    触发定住的就是鼠标向右下角移动」
        //   弹窗在鼠标的右下 ⇒ 朝右下走 = 用户想过去点按钮 ⇒ 定住不动；
        //   其余方向 = 还在浏览 ⇒ 跟着走。
        const cx = last.clientX
        const cy = last.clientY
        const p0 = prevPtRef.current
        const moving = cx !== p0.x || cy !== p0.y

        // ★★ 浮窗实际在哪一侧？NodeHoverCard 的规则：
        //    x + 14 + CARD_W > 屏宽 ⇒ 翻到鼠标左边（避免出屏）。
        //    列表页浮窗恒在右侧，写死「右下定住」没问题；
        //    图谱节点可在屏幕任意位置 ⇒ 必须按实际侧判断，否则靠右节点
        //    的浮窗在左边，用户往左移想点它，代码却以为「远离」而跟着跑。
        const cardOnLeft = cx + 14 + CARD_W > (typeof window === 'undefined' ? 1200 : window.innerWidth)
        const towardCard = moving && (
          cardOnLeft ? cx <= p0.x && cy >= p0.y   // 浮窗在左下 ⇒ 往左下 = 过去点它
                     : cx >= p0.x && cy >= p0.y   // 浮窗在右下 ⇒ 往右下 = 过去点它
        )
        prevPtRef.current = { x: cx, y: cy }

        const sameNode = hoverRef.current?.node.vid === n.vid
        if (!(towardCard && sameNode)) {
          setHoverSync({ node: n, x: cx, y: cy })
        }
        setEdgeHover(null)
        return
      }
      
      // ★★ 离开节点：**延迟**清空而不是立即清 —— 否则鼠标刚要移向浮窗就没了
      if (hoverRef.current && !cardHoverRef.current) {
        window.clearTimeout(leaveTimerRef.current)
        leaveTimerRef.current = window.setTimeout(() => {
          if (!cardHoverRef.current) setHoverSync(null)
        }, HOVER_LINGER_MS)
      }

      // ★ 没命中节点就判边：点到「聚合边」线段的距离
      // ⚠⚠ 只判**画布上真的画出来的边** —— `graph` 是已展示子集；
      //    ⛔ 不能用 `fullGraph`：它含被 showImports 过滤掉的 imports/includes
      //    ⇒ 会出现「两点之间根本没有线，却弹出这条边的详情」
      let bestEdge: GraphEdge | null = null
      let bestED = Infinity
      for (const e of graph?.edges ?? []) {
        if (!visibleRef.current.has(String(e.from)) || !visibleRef.current.has(String(e.to))) continue
        const pa = nodePos(G, String(e.from))
        const pb = nodePos(G, String(e.to))
        if (!pa || !pb) continue
        const d = distToSegment([p.x, p.y], [pa.x, pa.y], [pb.x, pb.y])
        if (d < bestED) { bestED = d; bestEdge = e }
      }
      setEdgeHover(
        bestEdge && bestED <= 8 ? { edge: bestEdge, x: last.clientX, y: last.clientY } : null,
      )
    }

    const onMove = (ev: PointerEvent) => {
      last = ev
      if (!raf) raf = requestAnimationFrame(update)
    }
    const onLeave = () => {
      // ★★ 浮窗 portal 到 body（画布之外）⇒ 鼠标从节点移向浮窗必然先离开画布。
      //   若这里立即清空，浮窗根本没机会被 hover 到（用户「移上去就立刻消失」）。
      //   ⇒ 与「离开节点」共用同一个 800ms 定时器，给鼠标跨过去的时间。
      window.clearTimeout(leaveTimerRef.current)
      leaveTimerRef.current = window.setTimeout(() => {
        if (!cardHoverRef.current) setHoverSync(null)
      }, HOVER_LINGER_MS)
      setEdgeHover(null)   // 边的浮窗没有交互按钮，仍然立即清
    }

    box.addEventListener('pointermove', onMove)
    box.addEventListener('pointerleave', onLeave)
    return () => {
      box.removeEventListener('pointermove', onMove)
      box.removeEventListener('pointerleave', onLeave)
      if (raf) cancelAnimationFrame(raf)
      window.clearTimeout(leaveTimerRef.current)
    }
  }, [graph, nodeSizePx])

  // 把 state 同步给 ref（供上面的 pointermove 闭包判断）
  useEffect(() => {
    hoverRef.current = hover
  }, [hover])

  // ============================================================ 建图（只在 graph 变时）
  useEffect(() => {
    const box = boxRef.current
    if (!box || !graph) return

    const W = box.clientWidth || 900
    const H = box.clientHeight || 600
    const total = Math.max(1, graph.nodes.length)

    // ★ graphology：sigma 的数据容器（有向图，对应原来的 G6 data）
    const G = new DirectedGraph({ type: 'directed', multi: true })
    graph.nodes.forEach((n, i) => {
      const ang = (i / total) * Math.PI * 2
      const patched = !!n.patched
      G.addNode(String(n.vid), {
        // 初始小圆环（ForceAtlas2 从它出发散开）
        x: W / 2 + Math.cos(ang) * RING,
        y: H / 2 + Math.sin(ang) * RING,
        // 显示属性（reducer 会用到）
        size: nodeSize(n),
        color: colorOf(n),
        border: patched ? '#fbbf24' : '#ffffff',
        borderWidth: patched ? 2.5 : 2,
        label: truncateLabel(
          n.name,
          n.kind === 'file' || n.kind === 'dir' ? LABEL_MAX_FILE : LABEL_MAX_NAME,
        ),
        labelColor,
        // 内部标记（reducer 读）
        kind: n.kind,
        origin: n.origin,
        patched,
        flow: false,
        selected: false,
        active: false,
        hideLabel: false,
      })
    })
    graph.edges.forEach((e) => {
      if (!G.hasNode(String(e.from)) || !G.hasNode(String(e.to))) return
      const src = nodeById.get(String(e.from))
      G.addEdge(String(e.from), String(e.to), {
        key: String(e.id),
        color: src ? colorOf(src) : '#94a3b8',
        size: 1,
        manual: e.origin === 'manual',
        active: false,
      })
    })

    visibleRef.current = new Set(graph.nodes.map((n) => String(n.vid)))
    nodeInfoRef.current = new Map(graph.nodes.map((n) => [String(n.vid), n]))

    // ★ sigma 实例：替代 G6 Graph
    const sigma = new Sigma(G, box, {
      // ★ sigma 3：属性名固定为 color/size/label（reducer 里返回即可）
      labelRenderedSizeThreshold: 0,
      renderEdgeLabels: false,
      // ★ sigma 3：标签颜色从节点属性 labelColor 读
      labelColor: { attribute: 'labelColor', color: '#94a3b8' },
      defaultNodeColor: '#94a3b8',
      defaultEdgeColor: '#94a3b8',
      zIndex: true,
      // 节点 reducer：把 flow/selected/active/hideLabel 映射成样式
      nodeReducer: (_node, data) => ({
        ...data,
        // ★ 直接用节点自带 size（展开邻居时已写入），不查 nodeInfoRef 避免 undefined
        size: data.selected ? Number(data.size || 14) * 1.25
            : data.flow ? Number(data.size || 14) * 1.18
            : data.active ? Number(data.size || 14) * 1.08
            : data.size,
        borderWidth: data.selected ? 3 : data.flow ? 3 : data.active ? 3.5 : data.borderWidth,
        label: data.hideLabel ? '' : data.label,
      }),
      edgeReducer: (_edge, data) => ({
        ...data,
        color: data.active ? '#22d3ee' : data.color,
        size: data.active ? 2.5 : data.size,
      }),
    })

    gRef.current = sigma
    graphRef.current = G

    let alive = true
    onPhase?.('布局动画中…')

    // ★★★ ForceAtlas2：从圆环出发散开（同步 assign，分帧执行避免卡 UI）
    const t0 = performance.now()
    const settle = window.setTimeout(() => {
      if (!alive) return
      try {
        const sensible = forceAtlas2.inferSettings(G)
        forceAtlas2.assign(G, { iterations: 120, settings: sensible })
        sigma.refresh()
      } catch {
        /* 布局失败不影响看图 */
      }
      // ★ bbox 适配（替代 G6 fitCenter/zoomTo）
      try {
        const xs: number[] = []
        const ys: number[] = []
        G.forEachNode((_id, a) => { xs.push(a.x); ys.push(a.y) })
        const minX = Math.min(...xs), maxX = Math.max(...xs)
        const minY = Math.min(...ys), maxY = Math.max(...ys)
        if (isFinite(minX) && maxX - minX > 1 && maxY - minY > 1) {
          const pad = 70
          const z = Math.min((W - pad * 2) / (maxX - minX), (H - pad * 2) / (maxY - minY), 1.6)
          sigma.getCamera().setState({
            ratio: 1 / Math.max(0.15, z),
            x: (minX + maxX) / 2,
            y: (minY + maxY) / 2,
          })
        }
      } catch { /* 适配失败不影响看图 */ }
      readyRef.current = Date.now() || t0
      onPhase?.('布局完成')
    }, SETTLE_MS)

    // ★ 事件：点节点 / 点空白
    sigma.on('clickNode', ({ node }) => {
      const pos = sigma.graphToViewport({ x: G.getNodeAttribute(node, 'x'), y: G.getNodeAttribute(node, 'y') })
      setRing({ id: node, x: pos.x, y: pos.y })
      setRingScale(Math.max(1, Math.min(1 / sigma.getCamera().getState().ratio, 1.6)))
      onSelect(Number(node))
      setHoverSync(null)
    })
    sigma.on('clickStage', () => setRing(null))

    return () => {
      alive = false
      window.clearTimeout(settle)
      readyRef.current = 0
      gRef.current = null
      graphRef.current = null
      selectedRef.current = null
      sigma.kill()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, labelColor])

  // ============================================================ 执行流高亮
  /**
   * ★ 点「执行流」里的一条链 → 把链上节点点亮。
   *   ⚠ 先清上一轮的，再设新的：否则换链会留下残留的高亮。
   *   ⚠ 节点可能被「显示前 N 个」过滤掉，`setElementState` 会抛错 —— 逐个 try。
   */
  useEffect(() => {
    const G = graphRef.current
    const sigma = gRef.current
    if (!G || !sigma) return
    for (const id of flowIdsRef.current) setStates(G, id, [])
    flowIdsRef.current = []
    for (const v of highlightVids || []) {
      const id = String(v)
      if (!G.hasNode(id)) continue
      setStates(G, id, ['flow'])
      flowIdsRef.current.push(id)
    }
    if (selectedVid != null && G.hasNode(String(selectedVid))) {
      setStates(G, String(selectedVid), ['flow', 'selected'])
    }
    sigma.refresh()
  }, [highlightVids, selectedVid, graph])

  // ============================================================ 标签疏密（按缩放）
  /**
   * ★★ 节点一多、缩小看图时标签会糊成一片。
   *
   * 所有者原话（2026-11-14）：
   * 「图上标全长的函数名，节点一多，就继承密密麻麻的字符了」
   *
   * 借鉴 sigma 的三个设置（GitNexus 的 web 图谱用它）：
   *   `labelRenderedSizeThreshold`（太小就不画）、`labelDensity` + `labelGridCellSize`
   *   （网格内只放一个标签）⇒ 本质是**按空间竞争决定谁显示**。
   * G6 没有这套，所以自己实现：缩放 < 0.7 且节点 ≥ 30 时，只留
   *   「选中节点 + 它的直接邻居 + 度数最高的 12 个」的标签，其余置空。
   *
   * ⚠ 只改 `labelText`，不动节点/边结构；用 rAF 合并连续的缩放事件。
   */
  useEffect(() => {
    const sigma = gRef.current
    const G = graphRef.current
    if (!sigma || !G || !graph || graph.nodes.length < LABEL_MIN_NODES) return

    const labelOf = new Map<string, string>()
    for (const n of graph.nodes) {
      const max = n.kind === 'file' || n.kind === 'dir' ? LABEL_MAX_FILE : LABEL_MAX_NAME
      labelOf.set(String(n.vid), truncateLabel(n.name, max))
    }

    const deg = new Map<string, number>()
    for (const e of graph.edges) {
      const a = String(e.from)
      const b = String(e.to)
      deg.set(a, (deg.get(a) ?? 0) + 1)
      deg.set(b, (deg.get(b) ?? 0) + 1)
    }

    let raf = 0
    // ★ 只在「密集/非密集」切换时重绘，缩放过程中不重复 update（否则掉帧）
    let lastDense: boolean | null = null
    const apply = () => {
      raf = 0
      const dense = zoomOf(sigma) < LABEL_ZOOM_THRESHOLD
      if (dense === lastDense) return
      lastDense = dense
      let keep: Set<string> | null = null
      if (dense) {
        keep = new Set<string>()
        for (const [id] of [...deg.entries()].sort((x, y) => y[1] - x[1]).slice(0, LABEL_TOP_DEGREE)) {
          keep.add(id)
        }
        if (selectedVid != null) {
          const sid = String(selectedVid)
          keep.add(sid)
          for (const e of graph.edges) {
            if (String(e.from) === sid) keep.add(String(e.to))
            if (String(e.to) === sid) keep.add(String(e.from))
          }
        }
      }
      for (const [id, text] of labelOf) {
        if (!G.hasNode(id)) continue
        applyVisual(G, id, { label: keep && !keep.has(id) ? '' : text })
      }
      sigma.refresh()
    }
    const onTransform = () => {
      if (!raf) raf = requestAnimationFrame(apply)
    }

    sigma.getCamera().on('updated', onTransform)
    apply()
    return () => {
      sigma.getCamera().off('updated', onTransform)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [graph, selectedVid])

  // ============================================================ 环形按钮跟住节点
  useEffect(() => {
    if (!ring) return
    let raf = 0
    const tick = () => {
      const sigma = gRef.current
      const G = graphRef.current
      const el = ringRef.current
      // 节点被隐藏 ⇒ 收起按钮（* 先判断数据，* 不做异常兜底）⚠
      if (!visibleRef.current.has(ring.id)) {
        setRing(null)
        return
      }
      if (sigma && G && el) {
        const np = nodePos(G, ring.id)
        if (np) {
          const p = toViewport(sigma, np.x, np.y)
          const z = Math.max(1, Math.min(zoomOf(sigma), 1.6))
          // ★★ 直接写 DOM style —— 走 setState 会因 React 排帧慢而「跟不住」⚠
          el.style.left = `${p.x}px`
          el.style.top = `${p.y}px`
          el.style.transform = `translate(-50%, -50%) scale(${z})`
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [ring?.id])

  // ============================================================ 容器尺寸 ⇒ 重画
  useEffect(() => {
    const sigma = gRef.current
    const box = boxRef.current
    if (!sigma || !box) return
    // ★★★ 写作区上提 / 分隔条拖动时容器尺寸会变 ——* 必须显式 resize，
    //   * 否则 G6 的 canvas 还是旧尺寸（* 图被裁、* 流星坐标也错）⚠
    const ro = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        try {
          const w = box.clientWidth
          const h = box.clientHeight
          if (w > 0 && h > 0) sigma.refresh()
        } catch {
          /* 实例已销毁 */
        }
      })
    })
    ro.observe(box)
    return () => ro.disconnect()
  }, [graph])

  // ============================================================ 选中态（受控）
  useEffect(() => {
    const sigma = gRef.current
    const G = graphRef.current
    if (!sigma || !G || !graph) return
    const cur = selectedVid ?? null
    const prev = selectedRef.current

    // ★★★ **直接改节点描边**，⛔ 不用 `setElementState` ——
    //   · · ★ G6 的默认 selected 样式会叠一层**黑色描边**（* 实测：点击后变黑圈，
    //     颜色和标签文字一样），* 改 state 样式压不住那层 ⚠
    //   · · ★ 直接 `updateNodeData` 最可控 ✅
    // ★★ `scale` = 节点直径倍数：* 选中要**把节点放大**，
    //   * 只加粗描边会让填充区视觉上变小（* 所有者指出的问题）⚠
    const paint = (vid: number, stroke: string, lineWidth: number, scale: number) => {
      const n = graph.nodes.find((x) => x.vid === vid)
      if (!n) return
      // ★★ 查**可见集合**（* 已被隐藏移除的节点直接跳过，不碰 G6）⚠
      if (!visibleRef.current.has(String(vid))) return
      applyVisual(G, String(vid), {
        stroke, lineWidth, size: nodeSize(n) * scale,
      })
    }
    if (prev != null && prev !== cur) {
      const p = graph.nodes.find((x) => x.vid === prev)
      paint(prev, p?.patched ? '#fbbf24' : '#ffffff', p?.patched ? 2.5 : 2, 1)
    }
    // ★★★ 选中 = **节点放大 1.25 倍 + 白描边略加粗**（* 只加粗描边会让填充变
    //   小、* 视觉上反而"缩小"，* 所以必须同时放大尺寸）⚠
    if (cur != null) paint(cur, '#ffffff', 3, 1.25)
    selectedRef.current = cur
    sigma.refresh()
  }, [selectedVid, graph])

  // ============================================================ 搜索聚焦
  useEffect(() => {
    const sigma = gRef.current
    const G = graphRef.current
    if (!sigma || !G || focusVid == null) return
    focusOn(sigma, G, String(focusVid))
  }, [focusVid])

  // ============================================================ 流星（等布局稳定后启动）
  useEffect(() => {
    const sigma = gRef.current
    const G = graphRef.current
    const box = boxRef.current
    if (!sigma || !G || !box || !graph || !meteors) return
    // ★★★ 所有者原话：「**不管什么情况，都给我加个动态效果**」⚠
    //   ⛔ 不再因 `prefers-reduced-motion` 跳过 —— * 那会让流星彻底不出现
    //   （* 一度就是这个原因：* 系统开了"减少动态效果" ⇒ 用户始终看不到 canvas）⚠

    let stop: (() => void) | null = null
    let timer: number | null = null
    let cancelled = false

    // ★ 轮询等「布局完成」信号；布局还在动时画流星会乱窜
    const wait = () => {
      if (cancelled) return
      if (!readyRef.current) {
        timer = window.setTimeout(wait, 150)
        return
      }
      // ★★ 每条边带上**发出节点**的 size / color ——
      //    * 流星大小 = 节点直径 1/10，* 颜色 = 节点颜色（* 所有者口径）⚠
      // ★★ 边一律取自**画布实时数据**（`g.getEdgeData()`），⛔ 不再取页面状态 ⚠
      //   原因：「显示邻居」和改图新增是**直接往 G6 里加**节点/边，
      //   页面状态里没有它们 ⇒ 用 `graph.edges` 会漏掉这些边 ⇒ 新边没有流星（所有者踩到）
      const edges = G.edges().map((e) => {
        const [f, t] = G.extremities(e)
        return {
          from: f,
          to: t,
          size: nodeSizeOf(G, f),
          // 颜色 = 发出节点的填充色（和节点同源）
          color: nodeColorOf(G, f),
          toSize: nodeSizeOf(G, t),
        }
      })
      stop = startMeteor(sigma, G, box, edges, {
        speed: meteorSpeed,
        sizeRatio: meteorSizeRatio,
      })
      onPhase?.('流星已启动')
    }
    wait()

    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
      stop?.()
    }
    // ★★ `labelColor` 也进依赖：* 切主题 ⇒ 建图 effect 重跑（图重建）⇒
    //    * 旧的流星实例已销毁 ⇒* 必须跟着重启，否则"切背景后流星没了"⚠
  }, [graph, meteors, meteorSpeed, meteorSizeRatio, labelColor, dataVersion])

  // ★★★ 展开邻居：**只把新节点摆到宿主四周 80px 处 + draw()** ——
  //   * ⛔ 绝不 `render()` / 跑布局（* 那会整图重排，* 是所有者踩过的坑）⚠
  const expandNeighbors = async (id: string) => {
    const sigma = gRef.current
    const G = graphRef.current
    const src = fullGraph
    if (!sigma || !G || !src) return
    const existing = new Set(G.nodes())
    const byId = new Map(src.nodes.map((n) => [String(n.vid), n]))
    const nbrs = new Set<string>()
    for (const e of src.edges) {
      if (String(e.from) === id) nbrs.add(String(e.to))
      if (String(e.to) === id) nbrs.add(String(e.from))
    }
    const missing = [...nbrs].filter((v) => !existing.has(v) && byId.has(v))
    if (missing.length === 0) return

    const base = nodePos(G, id)
    if (!base) return
    const bx = base.x
    const by = base.y
    missing.forEach((v, i) => {
      const n = byId.get(v) as GraphNode
      const ang = (Math.PI * 2 * i) / missing.length - Math.PI / 2
      addNode(G, v, {
        x: bx + Math.cos(ang) * 90,
        y: by + Math.sin(ang) * 90,
        size: nodeSize(n),
        color: colorOf(n),
        border: n.patched ? '#fbbf24' : '#ffffff',
        borderWidth: n.patched ? 2.5 : 2,
        label: truncateLabel(n.name, n.kind === 'file' || n.kind === 'dir' ? LABEL_MAX_FILE : LABEL_MAX_NAME),
        labelColor,
        kind: n.kind, origin: n.origin, patched: !!n.patched,
        flow: false, selected: false, active: false, hideLabel: false,
      })
    })

    // 只加「两端都在图里」的边（* 新节点 ↔ 已在图里的节点）
    const addedIds = new Set(missing)
    const addedEdges = src.edges
      .filter((e) => {
        const f = String(e.from)
        const t = String(e.to)
        const fOk = existing.has(f) || addedIds.has(f)
        const tOk = existing.has(t) || addedIds.has(t)
        return fOk && tOk && (addedIds.has(f) || addedIds.has(t))
      })
      .forEach((e) => addEdge(G, String(e.from), String(e.to), {
        key: String(e.id),
        color: colorOf(byId.get(String(e.from)) as GraphNode),
        size: 1,
        manual: e.origin === 'manual',
        active: false,
      }))

    sigma.refresh()
    // ★ 同步可见集合 + **实时信息表**（悬停浮窗要用）
    missing.forEach((v) => {
      visibleRef.current.add(v)
      const n = byId.get(v)
      if (n) nodeInfoRef.current.set(v, n)
    })
    setDataVersion((v) => v + 1) // ★ 新边也要有流星
    onGraphChanged?.()
  }

  // ★★★ 隐藏节点：* **照原型 `hideNodeFromVisible` 的口径** ——
  //   · · ① 目标节点本身移除 ✅
  //   · · ② 只与它相连的**叶子邻居**（* 度数 1 且只连它）一并收起 ✅
  //   · · ③ 还连着**其它节点**的邻居 ⇒* **保留**，* 只断开与目标之间的边 ⚠
  //   · · （* 我原来把所有直接邻居都删了 ⇒ 点个枢纽节点半张图就没了）⚠
  const hideNodeAndNeighbors = async (id: string) => {
    const sigma = gRef.current
    const G = graphRef.current
    if (!sigma || !G) return
    const nodes = G.nodes()
    const edges = G.edges().map((e) => {
      const [s, t] = G.extremities(e)
      return { source: s, target: t }
    })

    // 当前可见图的无向邻接表
    const adj = new Map<string, Set<string>>()
    for (const e of edges) {
      const a = String(e.source)
      const b = String(e.target)
      if (!adj.has(a)) adj.set(a, new Set())
      if (!adj.has(b)) adj.set(b, new Set())
      adj.get(a)!.add(b)
      adj.get(b)!.add(a)
    }

    const removing = new Set<string>([id])
    for (const n of adj.get(id) ?? []) {
      const nbrs = adj.get(n)
      // ★ 只删「仅与它相连」的邻居（* 还连着别人的要留在图上）⚠
      if (nbrs && nbrs.size === 1 && nbrs.has(id)) removing.add(n)
    }

    const cur = new Set(nodes)
    const ids = [...removing].filter((v) => cur.has(v))
    if (ids.length === 0) return

    // 先删边（两头沾到被移除节点的边），再删点
    for (const e of G.edges()) {
      const [s, t] = G.extremities(e)
      if (removing.has(s) || removing.has(t)) G.dropEdge(e)
    }
    dropNodes(G, ids)
    sigma.refresh()
    // ★ 同步可见集合（* 之后任何判断都以它为准）⚠
    ids.forEach((v) => {
      visibleRef.current.delete(v)
      nodeInfoRef.current.delete(v)
    })
    setDataVersion((v) => v + 1)
    setRing(null)
    // ★ 被隐藏的若是当前选中节点 ⇒ 清掉选中
    if (selectedRef.current != null && removing.has(String(selectedRef.current))) {
      onDeselect?.()
    }
    onGraphChanged?.()
  }

  // ★★ 两段弧：* 右半 = 显示邻居，* 左半 = 隐藏节点及其邻居 ⚠
  const ringSegments = [
    {
      key: 'expand',
      title: '显示邻居',
      d: ringArcPath(-Math.PI / 2 + 0.18, Math.PI / 2 - 0.18),
      icon: {
        x: RING_GEO.c + ((RING_GEO.r1 + RING_GEO.r2) / 2) * Math.cos(0),
        y: RING_GEO.c + ((RING_GEO.r1 + RING_GEO.r2) / 2) * Math.sin(0),
        d: 'M12 5v14M5 12h14',
      },
      run: (id: string) => void expandNeighbors(id),
    },
    {
      key: 'hide',
      title: '隐藏节点及其邻居',
      d: ringArcPath(Math.PI / 2 + 0.18, Math.PI * 1.5 - 0.18),
      icon: {
        x: RING_GEO.c + ((RING_GEO.r1 + RING_GEO.r2) / 2) * Math.cos(Math.PI),
        y: RING_GEO.c + ((RING_GEO.r1 + RING_GEO.r2) / 2) * Math.sin(Math.PI),
        d: 'M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61M9.88 9.88a3 3 0 1 0 4.24 4.24M2 2l20 20',
      },
      run: (id: string) => void hideNodeAndNeighbors(id),
    },
  ]

  // ★ ④ position:relative —— 流星罩层靠它定位；`height:100%` 靠父卡片给高度 ⚠
  return (
    <div
      ref={boxRef}
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
        // ★ AI 回答中画布不吃鼠标；问答区不受影响
        pointerEvents: aiBusy ? 'none' : 'auto',
      }}
    >
      {ring && (
        <svg
          ref={ringRef}
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
            // ★★★ 关键：* 环外空白**不拦截**图的拖拽 / 缩放 ——
            //   否则 96×96 整个盖住节点，* 节点就拖不动了（* 所有者踩过的坑）⚠
            pointerEvents: 'none',
          }}
          viewBox="0 0 96 96"
        >
          {ringSegments.map((seg) => (
            <g key={seg.key}>
              <path
                d={seg.d}
                onClick={(e) => {
                  e.stopPropagation()
                  seg.run(ring.id)
                }}
                style={{
                  // ★★★ 完全照原型 .node-ring-seg：
                  //   白实底 rgba(255,255,255,.96) + 边 #cbd5e1 + pointer-events auto ⚠
                  fill: 'rgba(255,255,255,.96)',
                  stroke: '#cbd5e1',
                  strokeWidth: 1,
                  pointerEvents: 'auto',
                  cursor: 'pointer',
                  transition: 'fill .15s, stroke .15s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.fill = '#eff6ff'
                  e.currentTarget.style.stroke = '#93c5fd'
                  const icon = e.currentTarget.nextElementSibling as SVGElement | null
                  if (icon) icon.style.stroke = '#2563eb'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.fill = 'rgba(255,255,255,.96)'
                  e.currentTarget.style.stroke = '#cbd5e1'
                  const icon = e.currentTarget.nextElementSibling as SVGElement | null
                  if (icon) icon.style.stroke = '#475569'
                }}
              >
                <title>{seg.title}</title>
              </path>
              <g
                transform={`translate(${seg.icon.x} ${seg.icon.y}) scale(0.55) translate(-12 -12)`}
                style={{ pointerEvents: 'none', fill: 'none', stroke: '#475569' }}
              >
                <path
                  d={seg.icon.d}
                  style={{
                    // ★★★ 照原型 .node-ring-icon：* 深灰蓝 #475569（* 白底上清晰）⚠
                    fill: 'none',
                    stroke: 'inherit',
                    strokeWidth: 2.6,
                    strokeLinecap: 'round',
                    strokeLinejoin: 'round',
                  }}
                />
              </g>
            </g>
          ))}
        </svg>
      )}

      {/* ★★ 悬停浮窗（名字 / 类型 / 签名 / 文件行号）—— 重载靠签名分辨 ⚠ */}
      {hover && (
        <NodeHoverCard
          node={hover.node}
          x={hover.x}
          y={hover.y}
          onEnter={() => {
            cardHoverRef.current = true
            window.clearTimeout(leaveTimerRef.current)
          }}
          onLeave={() => {
            cardHoverRef.current = false
            setHoverSync(null)
            setEdgeHover(null)
          }}
        />
      )}
      {edgeHover && <EdgeHoverCard edge={edgeHover.edge} x={edgeHover.x} y={edgeHover.y} />}
    </div>
  )
}
