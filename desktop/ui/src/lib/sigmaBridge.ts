import type Sigma from 'sigma'
import type DirectedGraph from 'graphology'
import type { GraphNode } from './mergeGraph'

/**
 * ★★ sigma 适配层：把原 G6 的常用操作映射成 graphology + sigma 调用。
 * 让 GraphCanvas 的 effect 改动尽量小。
 */

/** G6 getElementPosition(id) → graphology 节点坐标 */
export function nodePos(G: DirectedGraph, id: string): { x: number; y: number } | null {
  if (!G.hasNode(id)) return null
  const x = G.getNodeAttribute(id, 'x')
  const y = G.getNodeAttribute(id, 'y')
  return typeof x === 'number' && typeof y === 'number' ? { x, y } : null
}

/** G6 getCanvasByViewport([x,y]) → sigma viewportToGraph */
export function toGraph(sigma: Sigma, x: number, y: number) {
  return sigma.viewportToGraph({ x, y })
}

/** G6 getViewportByCanvas([x,y]) → sigma graphToViewport */
export function toViewport(sigma: Sigma, x: number, y: number) {
  return sigma.graphToViewport({ x, y })
}

/** G6 getZoom() → 1 / camera.ratio */
export function zoomOf(sigma: Sigma): number {
  return 1 / sigma.getCamera().getState().ratio
}

/** G6 setElementState(id, states) → 改 graphology 的 flow/selected 属性 */
export function setStates(G: DirectedGraph, id: string, states: string[]) {
  if (!G.hasNode(id)) return
  G.updateNodeAttribute(id, 'flow', () => states.includes('flow'))
  G.updateNodeAttribute(id, 'selected', () => states.includes('selected'))
}

/** 节点显示尺寸（与 GraphCanvas.nodeSize 保持一致） */
export function applyVisual(
  G: DirectedGraph,
  id: string,
  patch: { stroke?: string; lineWidth?: number; size?: number; label?: string },
) {
  if (!G.hasNode(id)) return
  if (patch.stroke !== undefined) G.updateNodeAttribute(id, 'border', () => patch.stroke)
  if (patch.lineWidth !== undefined) G.updateNodeAttribute(id, 'borderWidth', () => patch.lineWidth)
  if (patch.size !== undefined) G.updateNodeAttribute(id, 'size', () => patch.size)
  if (patch.label !== undefined) G.updateNodeAttribute(id, 'label', () => patch.label)
}

/** 读节点 size（供流星用） */
export function nodeSizeOf(G: DirectedGraph, id: string): number {
  if (!G.hasNode(id)) return 14
  return Number(G.getNodeAttribute(id, 'size')) || 14
}

/** 读节点颜色（供流星用） */
export function nodeColorOf(G: DirectedGraph, id: string): string {
  if (!G.hasNode(id)) return '#94a3b8'
  return String(G.getNodeAttribute(id, 'color') || '#94a3b8')
}

/** 添加节点（原 G6 addNodeData） */
export function addNode(
  G: DirectedGraph,
  id: string,
  attrs: Record<string, unknown>,
) {
  if (!G.hasNode(id)) G.addNode(id, attrs)
}

/** 添加边（原 G6 addEdgeData，带 key 避免重复） */
export function addEdge(
  G: DirectedGraph,
  source: string,
  target: string,
  attrs: Record<string, unknown> & { key?: string },
) {
  if (!G.hasNode(source) || !G.hasNode(target)) return false
  G.addEdge(source, target, attrs)
  return true
}

/** 删除节点与其所有边（原 G6 removeNodeData） */
export function dropNodes(G: DirectedGraph, ids: string[]) {
  for (const id of ids) if (G.hasNode(id)) G.dropNode(id)
}

/** 聚焦节点（原 G6 focusElement） */
export function focusOn(sigma: Sigma, G: DirectedGraph, id: string) {
  const p = nodePos(G, id)
  if (!p) return
  const v = sigma.graphToViewport(p)
  const rect = sigma.getContainer().getBoundingClientRect()
  sigma.getCamera().animate({
    x: p.x + (rect.width / 2 - v.x) * sigma.getCamera().getState().ratio,
    y: p.y + (rect.height / 2 - v.y) * sigma.getCamera().getState().ratio,
  }, { duration: 300 })
}

export type { GraphNode }
