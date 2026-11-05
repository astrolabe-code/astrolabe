/**
 * Astrolabe · 前端：**把【基图】与【用户修改】合起来**（★ `B180` · 2026-10-13）
 *
 * ★★★ 所有者原话（逐字）：
 *
 * > 「**基图与用户修改存在不同模型里，请求时，直接请求这两份数据，
 * > 前端负责整合**，这就要求节点索引一定要设计好，能迅速对比出修改的部分，
 * > **不是在服务器上整合了，再发出去**哦。」
 *
 * > 「**对，修改不会太多，前端完全扛得住**，流量相比整合了在发也不会太多。
 * > 这样服务器才能专心接受许多用户几乎同时写解释上传到服务器，
 * > 把，无关的，不重要的放到前端」
 *
 * ## ★★ 本模块只做一件事
 *
 * ```
 * ✅ 把【两份数据】合成一份可用的图
 * ❌ 它【不】请求任何东西（★ 取数在 `query/graph.ts`）
 * ❌ 它【不】改任何一份原数据（★ 纯函数）
 * ```
 *
 * ## ★★★ 「迅速对比出修改的部分」是怎么做到的
 *
 * ★★ 关键在**索引**：★ 把补丁按目标摊成 `Map` ⚠
 *
 * ```
 * ❌ 对每个节点去补丁数组里 find 一遍 ⇒ O(节点数 × 补丁数) ⚠
 *    ★ 10 万节点 × 100 条补丁 = 1000 万次比较 ⇒ 页面卡死 ⚠
 * ✅ 先把补丁摊成 Map ⇒ 每个节点 O(1) 查一次
 *    ★ 10 万节点 × 1 次查表 = 10 万次 ⇒ 毫秒级 ✅
 * ```
 */

/** ★ 基图节点（★ 与后端 `GET …/graph/nodes/` 的单项**逐字对应**）*/
export interface GraphNode {
  /** ★★ 权威标识（`B117`）—— ★ 补丁靠它指认"我改的是哪个" */
  vid: number
  uid: string
  kind: string
  name: string
  qname: string
  file_path: string
  line: number
  line_end: number | null
  lang: string
  signature: string
  /** ★ `parsed`（基图那份）· `manual`（用户新增的）*/
  origin: string
  /** ★★ 永久链接（★ 服务端已拼好）—— ★ `B179` 所有者明确要的 ⚠ */
  blob_url?: string
  /** ★★ 前端加的：★ 这个节点被**改过**（★ 用来做视觉标记）*/
  patched?: boolean
}

/** ★ 基图边（★ 与后端 `GET …/graph/edges/` 的单项对应）*/
export interface GraphEdge {
  /** ★★ 边的权威标识 —— ★ **补丁靠它指认"我改的是哪条边"** ⚠ */
  id: number
  from: number
  to: number
  type: string
  line: number | null
  origin: string
  confidence: string
  /** ★★ 前端加的：★ 这条边被改过 */
  patched?: boolean
}

/** ★★ 一条修改（★ 与后端 `GET …/graph/patches/` 的单项**逐字对应**）*/
export interface GraphPatch {
  patch_id: number
  /** ★ 六种动作之一 */
  action:
    | 'add_node'
    | 'update_node'
    | 'remove_node'
    | 'add_edge'
    | 'update_edge'
    | 'remove_edge'
  at: string
  by: string
  note: string
  /** ★ 改 / 删的是哪个基图节点（★ `add_node` 时是**新节点的 vid**）*/
  target_vid?: number
  /** ★ 改 / 删的是哪条基图边 */
  target_edge?: number
  /** ★ 加 / 改边时的两端 */
  from?: number
  to?: number
  /** ★ 覆盖内容（★ 字段与后端 `graph/curate.py::_NODE_FIELDS` 同口径）*/
  payload?: Record<string, unknown>
  /** ★★ `add_node` 时**自带新节点的完整内容**（★ 前端不必再查）✅ */
  node?: GraphNode
}

/** ★★ 合并结果 */
export interface EffectiveGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  /** ★★ `vid ⇒ 它身上的修改`（★ 「迅速对比」那个索引的副产物）*/
  patchesByVid: Map<number, GraphPatch[]>
  /** ★★ `边 id ⇒ 它身上的修改` */
  patchesByEdge: Map<number, GraphPatch[]>
  /** ★ 人工项计数（★ UI 上显示「N 项是维护者补的」）*/
  manualNodeCount: number
  manualEdgeCount: number
}

/**
 * ★★★ **把两份数据合成一份**（★ `B180` 的落点）。
 *
 * ⚠★ `patches` 为空 ⇒ ★ 结果**就等于基图原样**（★ 这是绝大多数项目的情形）✅
 *
 * @param baseNodes 基图那份节点（★ 服务端**没有**掺任何修改）
 * @param baseEdges 基图那份边
 * @param patches   修改那份
 */
export function mergeGraph(
  baseNodes: GraphNode[],
  baseEdges: GraphEdge[],
  patches: GraphPatch[],
): EffectiveGraph {
  // ==========================================================================
  // ⓵ ★★ 先摊索引 —— ★ 「迅速对比」的关键就在这一步 ⚠
  // ==========================================================================
  const byVid = new Map<number, GraphPatch[]>()
  const byEdge = new Map<number, GraphPatch[]>()
  const addedNodes: GraphNode[] = []
  const addedEdges: GraphEdge[] = []

  const push = <K, V>(m: Map<K, V[]>, k: K, v: V) => {
    const arr = m.get(k)
    if (arr) arr.push(v)
    else m.set(k, [v])
  }

  for (const p of patches) {
    if (p.action === 'add_node') {
      // ⚠★ 它**不认**已存在的目标（★ 是"新增"，★ 内容直接带在补丁里）⚠
      if (p.node) addedNodes.push({ ...p.node, origin: p.node.origin || 'manual' })
    } else if (p.action === 'add_edge') {
      if (typeof p.from === 'number' && typeof p.to === 'number') {
        addedEdges.push({
          // ⚠★ 新边**还没有服务端发的 id**（★ 它是前端先画出来的）——
          //   ★ 用负数占位，★ ❌ 不与真实 id 冲突 ✅
          id: -(addedEdges.length + 1),
          from: p.from,
          to: p.to,
          type: String(p.payload?.type ?? 'calls'),
          line: (p.payload?.line as number) ?? null,
          origin: 'manual',
          confidence: String(p.payload?.confidence ?? ''),
        })
      }
    } else {
      // ★ 剩下四种都是"改 / 删已存在的东西" ⇒ ★ 按目标摊进索引 ⚠
      if (typeof p.target_vid === 'number') push(byVid, p.target_vid, p)
      if (typeof p.target_edge === 'number') push(byEdge, p.target_edge, p)
    }
  }

  // ==========================================================================
  // ⓶ ★ 基图节点：逐个查索引（O(1)）⇒ 覆盖 / 隐藏
  // ==========================================================================
  const nodes: GraphNode[] = []
  const hidden = new Set<number>()

  for (const n of baseNodes) {
    const mine = byVid.get(n.vid)
    if (!mine) {
      nodes.push(n) // ★ 没被动过 ⇒ 原样（★ 绝大多数）
      continue
    }
    // ⚠★ 一个节点可能有多条补丁 ⇒ ★ 按**时间顺序**依次套用，★ 最后一条说了算 ⚠
    let cur: GraphNode | null = { ...n }
    let touched = false
    for (const p of mine) {
      if (p.action === 'remove_node') {
        // ★★ 被删 ⇒ **前端隐藏它**（★ 而基图那一行还在服务端 —— ★ 那正是设计）⚠
        cur = null
        touched = true
      } else if (p.action === 'update_node' && cur) {
        cur = { ...cur, ...(p.payload as Partial<GraphNode>) }
        touched = true
      }
    }
    if (cur === null) hidden.add(n.vid)
    else nodes.push(touched ? { ...cur, patched: true } : cur)
  }

  // ★ 用户新增的接在后面（★ `origin='manual'` ⇒ ★ UI 做视觉标记）
  for (const a of addedNodes) nodes.push({ ...a, origin: 'manual' })

  // ==========================================================================
  // ⓷ ★ 基图边：按 `id` 查索引（★ 与节点同一套）
  // ==========================================================================
  const edges: GraphEdge[] = []

  for (const e of baseEdges) {
    const mine = byEdge.get(e.id)
    if (!mine) {
      edges.push(e)
      continue
    }
    let cur: GraphEdge | null = { ...e }
    let touched = false
    for (const p of mine) {
      if (p.action === 'remove_edge') {
        cur = null
        touched = true
      } else if (p.action === 'update_edge' && cur) {
        cur = { ...cur, ...(p.payload as Partial<GraphEdge>) }
        touched = true
      }
    }
    if (cur !== null) edges.push(touched ? { ...cur, patched: true } : cur)
  }

  for (const a of addedEdges) edges.push(a)

  // ==========================================================================
  // ⓸ ★ 丢掉【两端有隐藏节点】的边 ⚠
  //   ★★ 否则前端画不出来（悬空边），★ 而且看起来像 bug ⚠
  // ==========================================================================
  const alive = new Set(nodes.map((n) => n.vid))
  const safeEdges = edges.filter((e) => alive.has(e.from) && alive.has(e.to))

  return {
    nodes,
    edges: safeEdges,
    patchesByVid: byVid,
    patchesByEdge: byEdge,
    manualNodeCount: nodes.filter((n) => n.origin === 'manual').length,
    manualEdgeCount: safeEdges.filter((e) => e.origin === 'manual').length,
  }
}
