/**
 * ★ Astrolabe 图数据库层（@ladybugdb/wasm-core，纯 WASM）
 *
 * 为什么用 WASM 版而不是原生 @ladybugdb/core：
 *   Obsidian 插件的 Electron 渲染进程禁止加载原生 .node ——
 *   · window.require 解析不到插件 node_modules
 *   · process.dlopen 只接受 electron.asar 内的包（Invalid package）
 *   ⇒ 只能走 WASM（WebView 原生支持，桌面/移动端通吃）。
 *
 * API 是 **同步** 的（sync 版不需要 Web Worker）：
 *   await lbug.init() → new Database(path) → new Connection(db) → conn.query(cypher)
 *
 * 图库位置：<vault>/astrolabe/graphs/<project>.lbug
 */
import lbug from '@ladybugdb/wasm-core/sync'

let initPromise = null
/** WASM 只能初始化一次 */
async function ensureInit() {
  if (!initPromise) initPromise = lbug.init()
  await initPromise
}

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

const REL_TABLE = `CREATE REL TABLE IF NOT EXISTS Rel(FROM Code TO Code, kind STRING)`

/**
 * ★★★ WASM 版 LadybugDB 运行在自己的 **虚拟文件系统（MEMFS）** 里，
 *   ⛔ 它看不到宿主机的 `D:/...` 路径（实测报
 *     "IO exception: Cannot open file D:/...: No such file or directory"）。
 *   而且它的 FS 接口不完整（没有 readFile/writeFile）⇒ 也没法把库文件
 *   导出到 vault。
 *
 *   ⇒ 库路径固定用 MEMFS 的 `/tmp/<项目>.lbug`（`/tmp` 是预置可用的）。
 *   语义：图库是「解析结果的缓存」——每次解析全量重建，
 *         Obsidian 重启后内存库清空，重新解析即可（解析本身很快）。
 */
const memPath = (project) =>
  `/tmp/${String(project || 'vault').replace(/[^\w\u4e00-\u9fa5-]/g, '_')}.lbug`

/** 打开（或新建）一个项目的图库 */
export async function openGraph(project) {
  await ensureInit()
  const dbPath = memPath(project)
  const db = new lbug.Database(dbPath)
  const conn = new lbug.Connection(db)
  conn.query(NODE_TABLE)
  conn.query(REL_TABLE)
  return { db, conn, dbPath }
}

/** 清空旧数据 */
export async function clearGraph(conn) {
  conn.query('MATCH (c:Code)-[r]->() DELETE r')
  conn.query('MATCH (c:Code) DELETE c')
}

/**
 * 写入节点 + 边。
 * @param {object} conn
 * @param {Array} nodes {vid, kind, name, qname, file, line, lineEnd}
 * @param {Array} edges {src, dst, type}
 */
export async function writeGraph(conn, nodes, edges) {
  await clearGraph(conn)

  // ★ 用 UNWIND 批量插入（比逐条快一个量级）
  if (nodes.length) {
    const rows = nodes.map((n) => ({
      vid: Number(n.vid),
      kind: String(n.kind || ''),
      name: String(n.name || ''),
      qname: String(n.qname || ''),
      file: String(n.file || ''),
      line: Number(n.line || 0),
      lineEnd: Number(n.lineEnd ?? -1),
    }))
    const stmt = conn.prepare(
      'UNWIND $rows AS r CREATE (:Code {vid: r.vid, kind: r.kind, name: r.name, qname: r.qname, file: r.file, line: r.line, lineEnd: r.lineEnd})',
    )
    conn.execute(stmt, { rows })
  }

  if (edges.length) {
    const rows = edges.map((e) => ({
      src: Number(e.src),
      dst: Number(e.dst),
      kind: String(e.type || 'call'),
    }))
    const stmt = conn.prepare(
      'UNWIND $rows AS r MATCH (a:Code), (b:Code) WHERE a.vid = r.src AND b.vid = r.dst CREATE (a)-[:Rel {kind: r.kind}]->(b)',
    )
    conn.execute(stmt, { rows })
  }
}

/** 查询所有节点/边（供图谱视图用） */
export async function readGraph(conn) {
  const nodeResult = conn.query(
    'MATCH (c:Code) RETURN c.vid AS vid, c.kind AS kind, c.name AS name, c.qname AS qname, c.file AS file, c.line AS line, c.lineEnd AS lineEnd',
  )
  const edgeResult = conn.query(
    'MATCH (a:Code)-[r:Rel]->(b:Code) RETURN a.vid AS src, b.vid AS dst, r.kind AS kind',
  )
  const nodeRows = nodeResult.getAllObjects()
  const edgeRows = edgeResult.getAllObjects()
  return {
    nodes: nodeRows.map((r) => ({
      vid: Number(r.vid), kind: r.kind, name: r.name, qname: r.qname,
      file: r.file, line: Number(r.line), lineEnd: Number(r.lineEnd),
    })),
    edges: edgeRows.map((r) => ({ src: Number(r.src), dst: Number(r.dst), type: r.kind })),
  }
}

/**
 * 执行任意 Cypher 查询。
 * @returns {{ columns: string[], rows: object[], elapsedMs: number }}
 */
export async function runQuery(conn, cypher) {
  const t0 = Date.now()
  let result
  try {
    result = conn.query(String(cypher || '').trim())
  } catch (e) {
    throw new Error(String(e && e.message || e))
  }
  if (!result.isSuccess()) {
    throw new Error(result.getErrorMessage() || '查询失败')
  }
  // 多条语句时取最后一条的结果
  const rows = result.getAllObjects()
  const columns = rows.length ? Object.keys(rows[0]) : []
  return { columns, rows, elapsedMs: Date.now() - t0 }
}

/** 关闭 */
export async function closeGraph({ db, conn }) {
  try { conn.close() } catch { /* 忽略 */ }
  try { db.close() } catch { /* 忽略 */ }
}
