/**
 * Astrolabe · 前端：**图数据层**（★ `B179` / `B180`）
 *
 * ## ★★★ 这里**取两份数据**（★ 而不是一份合并好的）
 *
 * ★★ 所有者原话（逐字）：
 *
 * > 「**基图与用户修改存在不同模型里，请求时，直接请求这两份数据，
 * > 前端负责整合**，这就要求节点索引一定要设计好，能迅速对比出修改的部分，
 * > **不是在服务器上整合了，再发出去**哦。」
 *
 * ```
 * ★ 第一份：GET …/graph/nodes/  ·  …/graph/edges/       ← 基图（★ 不掺任何修改）
 * ★ 第二份：GET …/graph/patches/                        ← 用户修改
 * ★★ 合成：`mergeGraph()`（★ 在 `lib/mergeGraph.ts`）   ← ★★ 【前端】做 ⚠
 * ```
 *
 * ## ⚠★ 一个必须知道的接口不一致（★ 不是我能改的，★ 照它来）
 *
 * | 端点 | 外层形态 |
 * |---|---|
 * | ★ `/graph/nodes/` | ★ `{ok, total, limit, offset, items}` —— **平铺**（`ok_flat`）|
 * | ★ `/graph/edges/` · `/graph/patches/` | ★ `{ok, data:{…}}` —— **包一层 `data`** |
 *
 * ⇒ ★ 所以 `unwrap()` 的 kind 要**分别传**（★ 平铺传 `'spread'`、★ 包的传 `'data'`）⚠
 */

import { useQuery } from '@tanstack/react-query'

import { apiGet } from '../api/client'
import { personalApi } from '../api/personal'
import { unwrap } from '../api/errors'
import { mergeGraph } from '../lib/mergeGraph'
import type { EffectiveGraph, GraphEdge, GraphNode, GraphPatch } from '../lib/mergeGraph'

/** ★ 一页最多取多少（★ 与后端 `NODES_PAGE_MAX` / `EDGES_PAGE_MAX` 对齐）*/
export const NODES_PAGE_MAX = 500
export const EDGES_PAGE_MAX = 2000

/** ★★ 基图节点（★ ① 型里最特殊的一个：**它是平铺的**）*/
export function useGraphNodes(
  projectRef?: string | null,
  opts: { limit?: number; offset?: number; enabled?: boolean } = {},
) {
  const { limit = NODES_PAGE_MAX, offset = 0, enabled = true } = opts
  return useQuery({
    queryKey: ['graph', 'nodes', projectRef, limit, offset],
    enabled: !!projectRef && enabled,
    // ★★ 个人版：走本地边车（`api/personal.ts` 负责形状翻译）⚠
    queryFn: async (): Promise<{ total: number; items: GraphNode[] }> =>
      personalApi.graphNodes(projectRef!, limit, offset),
  })
}

/** ★★ 基图边 */
export function useFullGraph(projectRef?: string | null) {
  return useQuery({
    queryKey: ['graph', 'full', projectRef],
    enabled: !!projectRef,
    // ★ 图谱是重查询 ⇒ 30 秒内不重取（* `graph_rev` 变了会自然失效）
    staleTime: 30_000,
    queryFn: async (): Promise<EffectiveGraph & { graph_rev: number }> => {
      // ★★ 个人版：一次拿全图（边车不做分页，也没有补丁概念）
      const g = await personalApi.fullGraph(projectRef!)
      return { ...mergeGraph(g.nodes, g.edges, []), graph_rev: g.rev }
    },
  })
}
