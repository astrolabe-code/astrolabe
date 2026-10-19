import { useEffect, useMemo, useRef } from 'react'
import { Graph } from '@antv/g6'
import { startMeteor } from '../../lib/meteorFx'
import { useTheme } from '../../hooks/useTheme'
import type { EffectiveGraph, GraphNode } from '../../lib/mergeGraph'

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

const KIND_COLOR: Record<string, string> = {
  function: '#4db8d6',
  class: '#f59e0b',
  method: '#ec4899',
  module: '#a78bfa',
  file: '#22c55e',
  package: '#a78bfa',
  type: '#f59e0b',
}

const colorOf = (n: GraphNode) => KIND_COLOR[n.kind] || '#94a3b8'

/** 初始圆环半径（px）—— 小到看起来"聚在中心"，又大到能让布局散开 */
const RING = 70
/** 布局散开 + 适配的时间（ms） */
const SETTLE_MS = 2500

interface GraphCanvasProps {
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
}

export default function GraphCanvas({
  graph,
  selectedVid,
  onSelect,
  onDeselect,
  focusVid,
  meteors = true,
  meteorSpeed,
  meteorSizeRatio,
  nodeSizePx = 28,
  onPhase,
}: GraphCanvasProps) {
  // ★★★ 节点标签颜色**跟随主题反转**（* 所有者：「深色背景就用白色，跟着反转」）⚠
  //   · · ★ 原来写死 #cbd5e1（浅灰）⇒ 深色下发灰、浅色下糊成一片 ⚠
  const { theme } = useTheme()
  const labelColor = theme === 'dark' ? '#ffffff' : '#000000'

  const boxRef = useRef<HTMLDivElement>(null)
  const gRef = useRef<Graph | null>(null)
  const selectedRef = useRef<number | null>(null)
  /** 布局是否已稳定（* 0 = 还没有；存时刻） */
  const readyRef = useRef(0)
  // ★ 节点的 size / color：* 节点渲染与流星共用（* 流星大小 = 直径 1/10、颜色 = 节点色）⚠
  // ★ 手工补的节点略大 15%，* 其余按设置值（* 流星光晕随之等比缩放）⚠
  const nodeSize = (n: GraphNode) =>
    n.origin === 'manual' ? Math.round(nodeSizePx * 1.15) : nodeSizePx
  const nodeById = useMemo(
    () => new Map((graph?.nodes ?? []).map((n) => [String(n.vid), n])),
    [graph],
  )

  // ============================================================ 建图（只在 graph 变时）
  useEffect(() => {
    const box = boxRef.current
    if (!box || !graph) return

    const W = box.clientWidth || 900
    const H = box.clientHeight || 600
    const total = Math.max(1, graph.nodes.length)

    const g = new Graph({
      container: box,
      autoResize: true,
      // ★ ① 必须开：关掉的话布局过渡是瞬时的（看不到散开）
      animation: true,
      data: {
        nodes: graph.nodes.map((n, i) => {
          // ★ ③ 小圆环初始分布（视觉上聚在中心，但布局能散开）
          const ang = (i / total) * Math.PI * 2
          const manual = n.origin === 'manual'
          return {
            id: String(n.vid),
            type: manual ? 'diamond' : 'circle',
            style: {
              x: W / 2 + Math.cos(ang) * RING,
              y: H / 2 + Math.sin(ang) * RING,
              size: nodeSize(n),
              fill: colorOf(n),
              // ★★ 白描边 2px ——* 深色背景上一圈白边，* 节点立刻"跳"出来（形似 code_network）⚠
              stroke: n.patched ? '#fbbf24' : '#ffffff',
              lineWidth: n.patched ? 2.5 : 2,
              lineDash: n.patched ? [4, 3] : undefined,
              labelText: n.name,
              labelPlacement: 'bottom',
              labelFill: labelColor,
              labelFontSize: 11,
            },
          }
        }),
        edges: graph.edges.map((e) => {
          const src = nodeById.get(String(e.from))
          return {
            id: String(e.id),
            source: String(e.from),
            target: String(e.to),
            style: {
              // ★★★ 连线颜色 = **发出节点的颜色**（* 所有者：「就用发出节点的颜色」）⚠
              //   · · ★ 以后连线颜色可能承载别的含义，* 现在统一跟节点走 ✅
              stroke: src ? colorOf(src) : '#94a3b8',
              lineWidth: 1,
              opacity: 0.65,
              endArrow: true,
              // ★★ 箭头调小（* 默认 10 左右 ⇒* 满屏都是箭头，* 密密麻麻）⚠
              endArrowSize: 4,
              lineDash: e.origin === 'manual' ? [5, 4] : undefined,
            },
          }
        }),
      },
      node: {
        style: { labelPlacement: 'bottom', labelFill: labelColor, labelFontSize: 11 },
        state: { selected: { lineWidth: 3, stroke: '#f59e0b' } },
      },
      edge: { style: { endArrow: true, lineWidth: 1 } },
      layout: {
        // ★ 从圆环出发，fruchterman 把它散开
        type: 'fruchterman',
        // ★★ 布局区域缩到画布 85% ——* 否则边缘节点会被切掉（* fit 后仍顶边）⚠
        width: W * 0.85,
        height: H * 0.85,
        // ★★ 节点 28px ⇒ 向心力必须小（* 8 太聚，* 24 个圆挤成一团）⚠
        gravity: 4,
        speed: 10,
      },
      behaviors: ['zoom-canvas', 'drag-canvas', 'drag-element', 'click-select'],
    })

    let alive = true

    // ★ ② 不 await / 不 then —— `animation:true` 时 promise 永不 resolve
    void g.render()
    onPhase?.('布局动画中…')

    // ★ 2.5 秒后：适配视图 + 标记"布局完成"
    const settle = window.setTimeout(() => {
      if (!alive) return
      void (async () => {
        try {
          // ★★★ **自己算缩放**：* `fitView` 会顶边（* 边缘节点被切），
          //   * 而 `zoomTo(常数)` 在大小图上都不合适 ⇒* 算 bbox + 留白 ⚠
          const fit = async () => {
            const ids = graph.nodes.map((n) => String(n.vid))
            let minX = Infinity
            let minY = Infinity
            let maxX = -Infinity
            let maxY = -Infinity
            for (const id of ids) {
              const p = g.getElementPosition(id)
              if (!p) continue
              minX = Math.min(minX, p[0])
              minY = Math.min(minY, p[1])
              maxX = Math.max(maxX, p[0])
              maxY = Math.max(maxY, p[1])
            }
            if (!isFinite(minX) || maxX - minX < 1 || maxY - minY < 1) return
            const pad = 70 // 四周留白（* 像素）
            const bw = maxX - minX
            const bh = maxY - minY
            const z = Math.min((W - pad * 2) / bw, (H - pad * 2) / bh, 1.6)
            // ★★ 必须 await ——* 否则 `fitCenter` 用旧 zoom（* 实测图不放大）⚠
            await g.zoomTo(Math.max(0.15, z))
            await g.fitCenter()
          }
          void fit()
          window.setTimeout(() => void fit(), 700)
        } catch {
          /* 适配失败不影响看图 */
        }
      })()
      readyRef.current = Date.now()
      onPhase?.('布局完成')
    }, SETTLE_MS)

    g.on('node:click', (evt: unknown) => {
      const e = evt as { target?: { id?: string | number } }
      if (e?.target?.id != null) onSelect(Number(e.target.id))
    })
    g.on('canvas:click', () => onDeselect?.())

    gRef.current = g

    return () => {
      alive = false
      window.clearTimeout(settle)
      readyRef.current = 0
      gRef.current = null
      selectedRef.current = null
      g.destroy()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph])

  // ============================================================ 主题切换：只改标签色
  useEffect(() => {
    const g = gRef.current
    if (!g) return
    // ★ 不重建图（* 那会重跑 2.5s 布局动画）——* 只改全局节点样式再重绘 ⚠
    g.setOptions({ node: { style: { labelFill: labelColor } } })
    void g.draw()
  }, [labelColor])

  // ============================================================ 容器尺寸变化 ⇒ 重画
  useEffect(() => {
    const g = gRef.current
    const box = boxRef.current
    if (!g || !box) return
    // ★★ 拖动分隔条 / 写作区全屏时容器宽度会变 ——* G6 的 autoResize 不够，
    //   * 必须显式 `resize()` 才会按新尺寸重绘（* 否则节点不动，* 看着像卡住）⚠
    const ro = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        try {
          g.resize()
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
    const g = gRef.current
    if (!g || !graph) return
    const cur = selectedVid ?? null
    const prev = selectedRef.current
    if (prev != null && prev !== cur) void g.setElementState(String(prev), [])
    selectedRef.current = cur
    if (cur != null) void g.setElementState(String(cur), ['selected'])
  }, [selectedVid, graph])

  // ============================================================ 搜索聚焦
  useEffect(() => {
    const g = gRef.current
    if (!g || focusVid == null) return
    void g.focusElement(String(focusVid))
  }, [focusVid])

  // ============================================================ 流星（等布局稳定后启动）
  useEffect(() => {
    const g = gRef.current
    const box = boxRef.current
    if (!g || !box || !graph || !meteors) return
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
      const edges = graph.edges.map((e) => {
        const src = nodeById.get(String(e.from))
        const dst = nodeById.get(String(e.to))
        return {
          from: String(e.from),
          to: String(e.to),
          size: src ? nodeSize(src) : 14,
          color: src ? colorOf(src) : '#94a3b8',
          toSize: dst ? nodeSize(dst) : 14,
        }
      })
      stop = startMeteor(g, box, edges, {
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
  }, [graph, meteors, meteorSpeed, meteorSizeRatio])

  // ★ ④ position:relative —— 流星罩层靠它定位；`height:100%` 靠父卡片给高度 ⚠
  return <div ref={boxRef} style={{ width: '100%', height: '100%', position: 'relative' }} />
}
