/**
 * ★ Astrolabe 图数据库层（@ladybugdb/core，纯 JS/TS 栈，独立 schema）
 *
 * 不依赖 Python 版：vid、schema、查询口径都由这个插件自己定义。
 * 参考 GitNexus 的用法：Database → Connection → prepare → execute → getAll。
 *
 * 图库位置：<vault>/astrolabe/graphs/<project>.lbug
 */

/**
 * ★ 用 Obsidian 桌面端暴露的 Node require 加载原生模块 ——
 *   esbuild 打包时不能把 .node 打进 bundle，必须在运行时从插件目录加载。
 *   window.require 是 Obsidian 桌面端提供的（Electron 渲染进程）。
 */
function loadLbug() {
  // ★ eval 绕过 esbuild 的静态 require 分析（browser 平台会把 require 替换掉）
  const nodeRequire = (0, eval)('typeof require === "function" ? require : null')
  const req = (typeof window !== 'undefined' && window.require) || nodeRequire
  if (!req) throw new Error('当前环境没有 Node require（LadybugDB 仅支持桌面端 Obsidian）')
  return req('@ladybugdb/core')
}
const { Database, Connection } = loadLbug()

/** 一个项目一个库；库里的节点/边表 */
const NODE_TABLE = `CREATE NODE TABLE IF NOT EXISTS Code(
  vid INT64,
  kind STRING,
  name STRING,
  qname STRING,
  file STRING,
  line INT64,
  lineEnd INT64,
  PRIMARY KEY (vid)
)`
const REL_TABLE = `CREATE REL TABLE IF NOT EXISTS Rel(
  FROM Code TO Code,
  kind STRING
)`

/** 打开（或新建）一个项目的图库 */
export async function openGraph(dbPath) {
  const db = new Database(dbPath)
  await db.init()
  const conn = new Connection(db)
  await conn.init()
  await conn.execute(await conn.prepare(NODE_TABLE))
  await conn.execute(await conn.prepare(REL_TABLE))
  return { db, conn }
}

/** 清空旧数据（重新解析时调用） */
export async function clearGraph(conn) {
  await conn.execute(await conn.prepare('MATCH (c:Code)-[r]->() DELETE r'))
  await conn.execute(await conn.prepare('MATCH (c:Code) DELETE c'))
}

/**
 * 写入节点 + 边（一次解析的完整结果）。
 * @param {object} conn  openGraph 返回的 conn
 * @param {Array} nodes  {vid, kind, name, qname, file, line, lineEnd}
 * @param {Array} edges  {src, dst, type}
 */
export async function writeGraph(conn, nodes, edges) {
  // 先清旧的
  await clearGraph(conn)

  // 批量插入节点（用参数化 prepared statement，避免拼字符串）
  const insertNode = await conn.prepare(
    'CREATE (:Code {vid: $vid, kind: $kind, name: $name, qname: $qname, file: $file, line: $line, lineEnd: $lineEnd})',
  )
  for (const n of nodes) {
    await conn.execute(insertNode, {
      vid: Number(n.vid),   // 53 位 vid 在 JS Number 安全范围内
      kind: String(n.kind || ''),
      name: String(n.name || ''),
      qname: String(n.qname || ''),
      file: String(n.file || ''),
      // ★ 不用 BigInt：LadybugDB 参数化对 BigInt(0) 处理有 bug
      //   （实测 line=0 写进去变成 133744648564058）
      line: Number(n.line || 0),
      lineEnd: Number(n.lineEnd ?? -1),
    })
  }

  // 批量插入边：按 vid 找到两端节点再连
  const matchPair = await conn.prepare(
    'MATCH (a:Code), (b:Code) WHERE a.vid = $src AND b.vid = $dst CREATE (a)-[:Rel {kind: $kind}]->(b)',
  )
  for (const e of edges) {
    await conn.execute(matchPair, {
      src: Number(e.src),
      dst: Number(e.dst),
      kind: String(e.type || 'call'),
    })
  }
}

/** 查询所有节点/边（供图谱视图用） */
export async function readGraph(conn) {
  const nodeStmt = await conn.prepare(
    'MATCH (c:Code) RETURN c.vid AS vid, c.kind AS kind, c.name AS name, c.qname AS qname, c.file AS file, c.line AS line, c.lineEnd AS lineEnd',
  )
  const edgeStmt = await conn.prepare(
    'MATCH (a:Code)-[r:Rel]->(b:Code) RETURN a.vid AS src, b.vid AS dst, r.kind AS kind',
  )
  const nodeResult = await conn.execute(nodeStmt)
  const edgeResult = await conn.execute(edgeStmt)
  const nodeRows = await nodeResult.getAll()
  const edgeRows = await edgeResult.getAll()
  return {
    nodes: nodeRows.map((r) => ({
      vid: Number(r.vid), kind: r.kind, name: r.name, qname: r.qname,
      file: r.file, line: Number(r.line), lineEnd: Number(r.lineEnd),
    })),
    edges: edgeRows.map((r) => ({ src: Number(r.src), dst: Number(r.dst), type: r.kind })),
  }
}

/** 关闭连接和库 */
export async function closeGraph({ db, conn }) {
  try { await conn.close() } catch { /* 忽略 */ }
  try { await db.close() } catch { /* 忽略 */ }
}
