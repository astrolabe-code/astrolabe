import { useEffect, useRef } from 'react'
import { startMeteor } from '../../lib/meteorFx'
import { Graph } from '@antv/g6'
import type { EffectiveGraph, GraphEdge, GraphNode } from '../../lib/mergeGraph'

/**
 * ★ 图谱画布（`D98` · AntV G6 v5）
 *
 * ## ★★ 为什么是 G6（* 所有者原话）
 *
 * > 「**现在图要用G6画，不要用vis-network了。**」
 *
 * ## ★★ 四条口径
 *
 * ```
 * ① ★★ 布局用 d3-force（* 代码图是"谁调谁"，* 力导向最直观）✅
 * ② ★★ 节点按 kind 着色；* 人工补的 = **菱形 + 虚线边**；* 补丁过的 = **虚线描边** ⚠
 * ③ ★★ 选中 / 聚焦走 `setElementState` + `focusElement`（* 搜索定位用）✅
 * ④ ★ 点节点 ⇒ `onSelect(vid)`；* 点空白 ⇒ `onDeselect()` ✅
 * ```
 *
 * ⚠★ 大图（> 800 节点）**不画标签** ——* 否则画布糊满、渲染拖慢 ⚠
 */
const KIND_COLOR: Record<string, string> = {
  function: '#4db8d6',
  class: '#f59e0b',
  method: '#ec4899',
  module: '#a78bfa',
  file: '#22c55e',
  package: '#a78bfa',
}

const colorOf = (n: GraphNode) => KIND_COLOR[n.kind] || '#94a3b8'

function edgeColor(e: GraphEdge): string {
  if (e.type === 'calls' || e.type === 'call') return '#d97706'
  if (e.type === 'imports' || e.type === 'import') return '#64748b'
  return '#94a3b8'
}

interface GraphCanvasProps {
  graph?: EffectiveGraph
  /** 选中的节点 vid（受控） */
  selectedVid?: number | null
  onSelect: (vid: number) => void
  /** 点空白处（* 关面板用） */
  onDeselect?: () => void
  /** 搜索聚焦（* 只移动视口，不改变选中） */
  focusVid?: number | null
  /** ★★ `D104`：* 流星轨迹开关（* 默认开）⚠ */
  meteors?: boolean
  /** ★ 当前阶段（* 布局动画中 / 布局完成 / 流星已启动）——* 用户据此验证效果 ⚠ */
  onPhase?: (phase: string) => void
}

export default function GraphCanvas({
  graph,
  selectedVid,
  onSelect,
  onDeselect,
  focusVid,
  meteors = true,
  onPhase,
}: GraphCanvasProps) {
  const boxRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  /** ★ 记住上一次选中的 id ——* 换选时先清旧态（`setElementState` 是附加的）⚠ */
  const selectedRef = useRef<number | null>(null)
  /** ★ 布局稳定的时刻（0 = 还没稳）——* 流星要等它 ⚠ */
  const layoutDoneRef = useRef(0)

  useEffect(() => {
    const box = boxRef.current
    if (!box || !graph) return

    const big = graph.nodes.length > 800
    // ★★ 布局必须知道**画布尺寸** ——* 不传就以 (0,0) 为中心铺开 ⇒
    //   图整个跑到画布右/下侧，只剩左上角一小块（* 实测挤成一团的真因）⚠
    const LW = box.clientWidth || 900
    const LH = box.clientHeight || 600

    const g = new Graph({
      container: box,
      autoResize: true,
      // ★★★ 必须开：* `false` 会让**布局过渡**也变瞬时 ⇒ 看不出"散开" ⚠
      animation: true,
      data: {
        nodes: graph.nodes.map((n, idx) => {
          const manual = n.origin === 'manual'
          // ★★★ 初始位置：* **小圆环**（半径 70）——* 视觉上还是"聚在中心"，*
          //   但 fruchterman 能沿径向散开（* 全重叠在一个点 ⇒ 斥力方向不定 ⇒ 散不开）⚠
          const ang = (idx / Math.max(1, graph.nodes.length)) * Math.PI * 2
          const ring = 70
          return {
            id: String(n.vid),
            // ★ G6 v5：节点类型在 data 顶层（`NodeData.type`），⛔ 不在 style 里
            type: manual ? 'diamond' : 'circle',
            style: {
              // ★ 小圆环初始分布（* 见上面 ang/ring 的说明）⚠
              x: LW / 2 + Math.cos(ang) * ring,
              y: LH / 2 + Math.sin(ang) * ring,
              size: big ? 10 : manual ? 16 : 14,
              fill: colorOf(n),
              stroke: n.patched ? '#fbbf24' : colorOf(n),
              lineWidth: n.patched ? 2 : 1,
              lineDash: n.patched ? [4, 3] : undefined,
              labelText: big ? undefined : n.name,
              labelPlacement: 'bottom',
              labelFill: '#cbd5e1',
              labelFontSize: 10,
            },
          }
        }),
        edges: graph.edges.map((e) => ({
          id: String(e.id),
          source: String(e.from),
          target: String(e.to),
          style: {
            stroke: edgeColor(e),
            lineWidth: 1,
            opacity: 0.65,
            endArrow: true,
            lineDash: e.origin === 'manual' ? [5, 4] : undefined,
          },
        })),
      },
      node: {
        style: {
          labelPlacement: 'bottom',
          labelFill: '#cbd5e1',
          labelFontSize: 10,
        },
        state: {
          // ★ 选中态：金色描边（* 与补丁的黄色虚线区分开——一个是 lineWidth/实线）
          selected: { lineWidth: 3, stroke: '#f59e0b' },
        },
      },
      edge: { style: { endArrow: true, lineWidth: 1 } },
      layout: {
        // ★★★ 两段式：* 节点自带**中心初始坐标**（* 见上面 style.x/y）+ 布局算法
        //   会把它们**散开** ——* 不再用 `preset` 再二次 `layout()`（* 实测不执行）⚠
        type: 'fruchterman',
        width: LW,
        height: LH,
        gravity: 8,
        speed: 8,
      },
      behaviors: ['zoom-canvas', 'drag-canvas', 'drag-element', 'click-select'],
    })

    // ★★★ 布局完成后**显式适配视图**（`autoFit` 的对象形态在 v5 里不生效——
    //   实测图会挤在左上角一小块、* 节点密密麻麻）⚠
    //   · · ★★ 必须在 `afterlayout` 里做：* 布局是**异步**的，* 在 `render()`
    //     resolve 时就 fit ⇒* 节点还在 (0,0) ⇒* fit 到空气 ⇒* 等于没做 ⚠
    let alive = true
    // ★★★ 两段式布局（* `D105` 补充）⚠
    //   · · ① 预设位置渲染 ⇒* 节点全在画布中心（* 一瞬间就能看到）✅
    //   · · ② 2.5 秒内 **fruchterman 散开**（* graph 级 `animation:true` 才有过渡）✅
    //   · · ③ 散开后 fit 一次；* 然后才让流星出场（* 见下方 effect）✅
    const fitOnce = () => {
      if (!alive) return
      void (async () => {
        try {
          await g.fitView({ when: 'always' })
          await g.fitCenter()
        } catch {
          /* 适配失败不影响看 */
        }
      })()
    }
    // ★★★ 布局给 **2.5 秒**散开（* 所有者口径：「用两三秒调整布局」）——
    //   ⛔ 不再用 `afterlayout` 去抖：* fruchterman 会持续触发该事件 ⇒
    //   * 去抖永远等不到"稳定" ⇒* fit 与流星都不会发生（* 实测踩到）⚠
    // ⚠★★ `animation: true` 时 **`g.render()` 的 promise 永不 resolve**
    //   （* 实测：* 不 then 就永远卡住 ⇒* 后面 fit / 流星全不执行）⚠
    //   ⇒ ★ 不依赖它的 promise，* 用固定时间推进阶段 ✅
    let settleTimer: number | null = null
    void g.render()
    onPhase?.('布局动画中…')
    settleTimer = window.setTimeout(() => {
      if (!alive) return
      fitOnce()
      layoutDoneRef.current = Date.now()
      onPhase?.('布局完成')
    }, 2500)

    g.on('node:click', (evt: unknown) => {
      const e = evt as { target?: { id?: string | number } }
      const raw = e?.target?.id
      if (raw != null) onSelect(Number(raw))
    })
    g.on('canvas:click', () => onDeselect?.())

    graphRef.current = g
    return () => {
      alive = false
      if (settleTimer != null) window.clearTimeout(settleTimer)
      layoutDoneRef.current = 0
      graphRef.current = null
      selectedRef.current = null
      g.destroy()
    }
    // ⚠ 重建只在「图换了」时发生（选中 / 聚焦走下面的 effect）⚠
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph])

  // ★ 选中态（受控）—— 先清旧的，再点亮新的
  useEffect(() => {
    const g = graphRef.current
    if (!g || !graph) return
    const cur = selectedVid ?? null
    const prev = selectedRef.current
    if (prev != null && prev !== cur) {
      void g.setElementState(String(prev), [])
    }
    selectedRef.current = cur
    if (cur != null) {
      void g.setElementState(String(cur), ['selected'])
    }
  }, [selectedVid, graph])

  // ★ 搜索聚焦：* 移动视口到目标（* 不改选中）✅
  useEffect(() => {
    const g = graphRef.current
    if (!g || focusVid == null) return
    void g.focusElement(String(focusVid))
  }, [focusVid])

  // ★★★ `D104`：**流星轨迹** —— 一块透明 canvas 罩在 G6 上（* 复用 meteorFx）⚠
  //   · · ★ 与主 effect 同一次提交执行 ⇒* 此时 `graphRef.current` 已就绪 ✅
  //   · · ★ 卸载 / 关开关时调停止函数（* ⛔ 不取消会泄漏 rAF）⚠
  useEffect(() => {
    const g = graphRef.current
    const box = boxRef.current
    if (!g || !box || !graph || !meteors) return
    // ★ 无障碍：* 用户要求「减少动态效果」时不启动 ✅
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      console.debug('[meteor] 跳过：系统设置了「减少动态效果」')
      return
    }
    // ★★ `D104`：**等布局稳了再出流星**（布局动画 2.5s ⇒ 流星延迟 2.6s）⚠
    //   · · ★ 布局还在动的时候，节点位置每帧都在变，* 流星会乱窜 ⚠
    //   · · ★ 延迟完全没影响：* 用户先看图散开，* 然后流星才亮起来 ✅
    let stop: (() => void) | null = null
    // ★★ 等「布局稳定」信号（* `layoutDoneRef` 非 0）再启动 ——*
    //   布局还在散的时候画流星 ⇒* 满屏糊成一团（* 实测）⚠
    let timer: number | null = null
    const tryStart = () => {
      if (!layoutDoneRef.current) {
        timer = window.setTimeout(tryStart, 150)
        return
      }
      onPhase?.('流星已启动')
      stop = startMeteor(
        g,
        box,
        graph.edges.map((e) => ({ from: String(e.from), to: String(e.to) })),
      )
    }
    timer = window.setTimeout(tryStart, 150)
    return () => {
      if (timer != null) window.clearTimeout(timer)
      stop?.()
    }
  }, [graph, meteors])

  // ★★ `D104`：**必须 `position:'relative'`** ——* 流星罩层是 `position:absolute;inset:0`，
  //   * 没有这个就会相对外层已定位祖先定位，* 整个跑到画布外面去（* 流星"不显示"的根因）⚠
  return <div ref={boxRef} style={{ width: '100%', height: '100%', position: 'relative' }} />
}
