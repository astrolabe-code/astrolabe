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
}

export default function GraphCanvas({
  graph,
  selectedVid,
  onSelect,
  onDeselect,
  focusVid,
  meteors = true,
}: GraphCanvasProps) {
  const boxRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  /** ★ 记住上一次选中的 id ——* 换选时先清旧态（`setElementState` 是附加的）⚠ */
  const selectedRef = useRef<number | null>(null)

  useEffect(() => {
    const box = boxRef.current
    if (!box || !graph) return

    const big = graph.nodes.length > 800

    const g = new Graph({
      container: box,
      autoResize: true,
      // ★ 首次渲染后自适应视图（`autoFit` 的对象形态，v5 口径）
      autoFit: { type: 'view' },
      animation: false,
      data: {
        nodes: graph.nodes.map((n) => {
          const manual = n.origin === 'manual'
          return {
            id: String(n.vid),
            // ★ G6 v5：节点类型在 data 顶层（`NodeData.type`），⛔ 不在 style 里
            type: manual ? 'diamond' : 'circle',
            style: {
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
        // ★ 代码图 = 「谁调谁」⇒* 力导向最直观 ✅
        type: 'd3-force',
        animate: false,
      },
      behaviors: ['zoom-canvas', 'drag-canvas', 'drag-element', 'click-select'],
    })

    void g.render()

    g.on('node:click', (evt: unknown) => {
      const e = evt as { target?: { id?: string | number } }
      const raw = e?.target?.id
      if (raw != null) onSelect(Number(raw))
    })
    g.on('canvas:click', () => onDeselect?.())

    graphRef.current = g
    return () => {
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
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    return startMeteor(
      g,
      box,
      graph.edges.map((e) => ({ from: String(e.from), to: String(e.to) })),
    )
  }, [graph, meteors])

  return <div ref={boxRef} style={{ width: '100%', height: '100%' }} />
}
