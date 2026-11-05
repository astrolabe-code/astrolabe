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
    queryFn: async (): Promise<{ total: number; items: GraphNode[] }> => {
      // ⚠★ `'spread'` —— ★ 这个端点是**平铺**的（`ok_flat`），❌ 没有 `data` 包一层 ⚠
      return unwrap(
        await apiGet<{ total: number; items: GraphNode[] }>(
          `/api/projects/${encodeURIComponent(projectRef!)}/graph/nodes/?limit=${limit}&offset=${offset}`,
          'spread',
        ),
      )
    },
  })
}

/** ★★ 基图边 */
export function useGraphEdges(
  projectRef?: string | null,
  opts: { limit?: number; offset?: number; enabled?: boolean } = {},
) {
  const { limit = EDGES_PAGE_MAX, offset = 0, enabled = true } = opts
  return useQuery({
    queryKey: ['graph', 'edges', projectRef, limit, offset],
    enabled: !!projectRef && enabled,
    queryFn: async (): Promise<{ total: number; items: GraphEdge[] }> =>
      unwrap(
        await apiGet<{ total: number; items: GraphEdge[] }>(
          `/api/projects/${encodeURIComponent(projectRef!)}/graph/edges/?limit=${limit}&offset=${offset}`,
          'data',
        ),
      ),
  })
}

/**
 * ★★★ **第二份数据：用户对基图的修改**（★ `B180` / `B181`）
 *
 * ★★ 服务端**只发修改**，★ **不做合并** ⚠ —— ★ 合并是 `mergeGraph()` 的事 ✅
 *
 * ⚠★ 返回值里的 `graph_rev` 与基图那份**是同一个值** ——
 *   ★★ 前端据此判断"我手上的两份是不是同一代" ⚠
 */
export function useGraphPatches(
  projectRef?: string | null,
  opts: { enabled?: boolean } = {},
) {
  const { enabled = true } = opts
  return useQuery({
    queryKey: ['graph', 'patches', projectRef],
    enabled: !!projectRef && enabled,
    queryFn: async (): Promise<{
      graph_rev: number
      total: number
      items: GraphPatch[]
    }> =>
      unwrap(
        await apiGet<{ graph_rev: number; total: number; items: GraphPatch[] }>(
          `/api/projects/${encodeURIComponent(projectRef!)}/graph/patches/`,
          'data',
        ),
      ),
  })
}


/**
 * ★★★ **整张图**（* 图谱页用，`D98`）——★ 循环分页拉全 + 前端合并补丁 ⚠
 *
 * ## ★★ 为什么要一个查询而不是三个 hook 拼
 *
 * ```
 * ★★ 节点 / 边 / 补丁必须来自**同一代**（`graph_rev` 相同）——
 *   · · ★ 三个独立 hook 各自取，* 中间可能隔了一次重解析 ⇒* 拼出**错代**的图 ⚠
 * ★★ 合并用 `mergeGraph()`（`B180`）：* 基图 + 补丁 ⇒* EffectiveGraph ✅
 * ```
 *
 * ⚠ 分页循环：* 每次 500 条（* 契约上限），* 顺序请求（* 不并发）✅
 */
const FULL_PAGE = 500

export function useFullGraph(projectRef?: string | null) {
  return useQuery({
    queryKey: ['graph', 'full', projectRef],
    enabled: !!projectRef,
    // ★ 图谱是重查询 ⇒ 30 秒内不重取（* `graph_rev` 变了会自然失效）
    staleTime: 30_000,
    queryFn: async (): Promise<EffectiveGraph & { graph_rev: number }> => {
      const ref = encodeURIComponent(projectRef!)

      // ① 节点（② 型扁平：`ok_flat`，没有 data 包一层）
      const nodes: GraphNode[] = []
      for (let offset = 0; ; ) {
        const page = unwrap(
          await apiGet<{ total: number; items: GraphNode[] }>(
            `/api/projects/${ref}/graph/nodes/?limit=${FULL_PAGE}&offset=${offset}`,
            'spread',
          ),
        )
        nodes.push(...(page.items || []))
        offset += page.items?.length || 0
        if (offset >= page.total || !page.items?.length) break
      }

      // ② 边（① 型：data 包装）
      const edges: GraphEdge[] = []
      for (let offset = 0; ; ) {
        const page = unwrap(
          await apiGet<{ total: number; items: GraphEdge[] }>(
            `/api/projects/${ref}/graph/edges/?limit=${FULL_PAGE}&offset=${offset}`,
            'data',
          ),
        )
        edges.push(...(page.items || []))
        offset += page.items?.length || 0
        if (offset >= page.total || !page.items?.length) break
      }

      // ③ 补丁（① 型；* 一次性全量）
      const patches = unwrap(
        await apiGet<{ graph_rev: number; total: number; items: GraphPatch[] }>(
          `/api/projects/${ref}/graph/patches/`,
          'data',
        ),
      )

      return { ...mergeGraph(nodes, edges, patches.items || []), graph_rev: patches.graph_rev }
    },
  })
}
