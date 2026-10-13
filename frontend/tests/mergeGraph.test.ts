import { mergeGraph, type GraphEdge, type GraphNode, type GraphPatch } from '../src/lib/mergeGraph'

const base: GraphNode[] = [
  { vid: 1, uid: 'f#a#alpha', kind: 'function', name: 'alpha', qname: '', file_path: 'a.py', line: 1, line_end: 9, lang: 'python', signature: 'def alpha()', origin: 'parsed' },
  { vid: 2, uid: 'f#a#beta',  kind: 'function', name: 'beta',  qname: '', file_path: 'a.py', line: 20, line_end: 29, lang: 'python', signature: 'def beta()',  origin: 'parsed' },
  { vid: 3, uid: 'f#a#gamma', kind: 'function', name: 'gamma', qname: '', file_path: 'a.py', line: 40, line_end: 49, lang: 'python', signature: 'def gamma()', origin: 'parsed' },
]
const edges: GraphEdge[] = [
  { id: 100, from: 1, to: 2, type: 'calls', line: 5,  origin: 'parsed', confidence: 'syntax' },
  { id: 101, from: 2, to: 3, type: 'calls', line: 22, origin: 'parsed', confidence: 'syntax' },
  // ★ 这条【不碰 2 号】⇒ ★ 用来验"删节点只连带删相连的边" ✅
  { id: 102, from: 1, to: 3, type: 'calls', line: 7,  origin: 'parsed', confidence: 'syntax' },
]
const patches: GraphPatch[] = [
  { patch_id: 1, action: 'update_node', at: '2026-10-13T10:00', by: 'u', note: '', target_vid: 1,
    payload: { name: 'alpha_renamed', signature: 'def alpha_renamed()' } },
  { patch_id: 2, action: 'remove_node', at: '2026-10-13T10:01', by: 'u', note: '', target_vid: 2 },
  { patch_id: 3, action: 'add_node',  at: '2026-10-13T10:02', by: 'u', note: '',
    node: { vid: 9001, uid: 'f#a#delta', kind: 'function', name: 'delta', qname: '', file_path: 'a.py', line: 90, line_end: 99, lang: 'python', signature: 'def delta()', origin: 'manual' } },
  { patch_id: 4, action: 'add_edge',  at: '2026-10-13T10:03', by: 'u', note: '', from: 1, to: 9001,
    payload: { type: 'calls', line: 6 } },
  { patch_id: 5, action: 'update_edge', at: '2026-10-13T10:04', by: 'u', note: '', target_edge: 101,
    payload: { type: 'called_by' } },
]

const g = mergeGraph(base, edges, patches)
let bad = 0
const chk = (label: string, got: unknown, want: unknown) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) bad++
  console.log(`  ${ok ? '✅' : '❌'} ${label.padEnd(52)} got=${JSON.stringify(got)}${ok ? '' : ` want=${JSON.stringify(want)}`}`)
}

console.log('=== ① 节点：改 / 删 / 增 ===')
chk('节点总数 = 3（3 基图 - 1 删 + 1 增）', g.nodes.length, 3)
const alpha = g.nodes.find((n) => n.vid === 1)!
chk('被改的节点：名字已覆盖', alpha.name, 'alpha_renamed')
chk('被改的节点：签了名也覆盖了', alpha.signature, 'def alpha_renamed()')
chk('被改的节点：标了 patched', alpha.patched, true)
chk('被删的节点：不见了', g.nodes.some((n) => n.vid === 2), false)
chk('新加的节点：在，且 origin=manual', g.nodes.find((n) => n.vid === 9001)?.origin, 'manual')

console.log('=== ② 边：删节点连带 + 改边 + 增边 ===')
// ⚠★ 100 与 101 都连着被删的 2 号 ⇒ ★ 都该被丢掉（★ 否则是悬空边）⚠
chk('边 101（连着被删的 2 号）已被丢掉', g.edges.some((e) => e.id === 101), false)
chk('边 100（也连着被删的 2 号）同样被丢掉', g.edges.some((e) => e.id === 100), false)
// ★★ 102 不碰 2 号 ⇒ ★ 必须还在（★ 这条才是"没有误删"的证据）✅
chk('边 102（不碰被删节点）★ 仍在', g.edges.some((e) => e.id === 102), true)
const added = g.edges.find((e) => e.from === 1 && e.to === 9001)!
chk('新增的边在', !!added, true)
chk('新增的边 origin=manual', added.origin, 'manual')
chk('新增的边用负数占位 id', added.id < 0, true)

console.log('=== ③ 索引：快速比对靠它 ===')
chk('索引里有 1 号节点的修改', g.patchesByVid.get(1)?.length, 1)
chk('索引里有 101 号边的修改', g.patchesByEdge.get(101)?.length, 1)

console.log('=== ④ 计数 ===')
chk('人工节点数 = 1', g.manualNodeCount, 1)
chk('人工边数 = 1', g.manualEdgeCount, 1)

console.log('=== ⑤ 空补丁 ⇒ 原样返回 ===')
const g0 = mergeGraph(base, edges, [])
chk('节点数不变', g0.nodes.length, 3)
chk('边数不变', g0.edges.length, 3)
chk('没有任何 patched 标记', g0.nodes.some((n) => n.patched), false)

console.log('=== ⑥ 原数据没被改动（纯函数）===')
chk('base[0].name 没被改', base[0].name, 'alpha')
chk('edges[1].type 没被改', edges[1].type, 'calls')

console.log(bad === 0 ? '\n  ★★★★★ 全部通过' : `\n  ❌ ${bad} 项不符`)
process.exit(bad === 0 ? 0 : 1)
