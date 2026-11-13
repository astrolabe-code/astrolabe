const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const Parser = require('tree-sitter')

const LANGS = {
  '.c': 'tree-sitter-c',
  '.h': 'tree-sitter-c',
  '.cc': 'tree-sitter-cpp',
  '.cpp': 'tree-sitter-cpp',
  '.cxx': 'tree-sitter-cpp',
  '.hpp': 'tree-sitter-cpp',
  '.hh': 'tree-sitter-cpp',
  '.hxx': 'tree-sitter-cpp',
  '.java': 'tree-sitter-java',
  '.py': 'tree-sitter-python',
  '.pyi': 'tree-sitter-python',
}

const SKIP = new Set(['.git', 'node_modules', '.astrolabe', 'dist', '__pycache__', '.venv', 'build'])

const DEFS = {
  function_definition: 'function',
  method_declaration: 'function',
  class_specifier: 'type',
  struct_specifier: 'type',
  union_specifier: 'type',
  enum_specifier: 'type',
  class_definition: 'type',
  class_declaration: 'type',
  interface_declaration: 'type',
  type_definition: 'type',
}

const CALLS = new Set(['call_expression', 'method_invocation', 'call'])
const INCLUDES = new Set(['preproc_include'])

/** vid 是 (kind, file, qname) 的稳定哈希：不含行号，函数整体下移也不会漂移 */
function makeVid(kind, file, qname) {
  const h = crypto.createHash('sha256').update(`${kind}\0${file}\0${qname}`).digest()
  return Number(h.readBigUInt64BE(0) & 0xffffffffffffn)
}

function declName(node) {
  if (!node) return null
  if (['identifier', 'field_identifier', 'type_identifier'].includes(node.type)) return node.text
  const d = node.childForFieldName('declarator')
  if (d) return declName(d)
  for (const c of node.namedChildren) {
    const r = declName(c)
    if (r) return r
  }
  return null
}

function nodeName(node) {
  const n = node.childForFieldName('name')
  if (n) return n.text
  return declName(node.childForFieldName('declarator'))
}

function calleeName(node) {
  const f = node.childForFieldName('function') || node.childForFieldName('name')
  if (!f) return null
  if (['identifier', 'field_identifier', 'type_identifier'].includes(f.type)) return f.text
  const tail = f.childForFieldName('field') || f.childForFieldName('attribute')
  return tail ? tail.text : null
}

function includePath(node) {
  const p = node.childForFieldName('path')
  if (!p) return null
  return p.text.replace(/^["<]/, '').replace(/[">]$/, '')
}

function collectFiles(root) {
  const out = []
  const walk = (rel, depth) => {
    if (depth > 8 || out.length > 3000) return
    let entries
    try {
      entries = fs.readdirSync(path.join(root, rel), { withFileTypes: true })
    } catch {
      return
    }
    for (const e of entries) {
      if (SKIP.has(e.name)) continue
      const r = rel ? `${rel}/${e.name}` : e.name
      if (e.isDirectory()) walk(r, depth + 1)
      else if (LANGS[path.extname(e.name).toLowerCase()]) out.push(r)
    }
  }
  walk('', 0)
  return out
}

/** 扫描一个源码目录，产出 nodes/edges；不碰数据库，便于放进独立进程 */
function scan(root) {
  const parsers = new Map()
  const nodes = []
  const calls = []
  const includes = []
  let files = 0

  for (const rel of collectFiles(root)) {
    const abs = path.join(root, rel)
    let text
    try {
      if (fs.statSync(abs).size > 512 * 1024) continue
      text = fs.readFileSync(abs, 'utf8')
    } catch {
      continue
    }
    const pkg = LANGS[path.extname(rel).toLowerCase()]
    if (!parsers.has(pkg)) {
      const p = new Parser()
      p.setLanguage(require(pkg))
      parsers.set(pkg, p)
    }
    let tree
    try {
      tree = parsers.get(pkg).parse(text)
    } catch {
      continue
    }
    files += 1

    const fileVid = makeVid('file', rel, rel)
    nodes.push({
      vid: fileVid,
      kind: 'file',
      name: path.basename(rel),
      qname: rel,
      file: rel,
      line: 0,
    })

    const visit = (n, stack, ownerVid) => {
      let nextStack = stack
      let nextOwner = ownerVid
      const kind = DEFS[n.type]
      if (kind) {
        const name = nodeName(n)
        if (name) {
          const qname = [...stack, name].join('.')
          const vid = makeVid(kind, rel, qname)
          nodes.push({ vid, kind, name, qname, file: rel, line: n.startPosition.row + 1 })
          nextStack = [...stack, name]
          nextOwner = vid
        }
      }
      if (CALLS.has(n.type)) {
        const name = calleeName(n)
        if (name) calls.push({ name, from: nextOwner })
      }
      if (INCLUDES.has(n.type)) {
        const p = includePath(n)
        if (p) includes.push({ path: p, from: nextOwner })
      }
      for (const c of n.namedChildren) visit(c, nextStack, nextOwner)
    }
    visit(tree.rootNode, [], fileVid)
  }

  // 同名定义恰好一个才连边（宁可漏，不要错）；include 按文件名唯一匹配
  const byName = new Map()
  for (const n of nodes) {
    if (!byName.has(n.name)) byName.set(n.name, [])
    byName.get(n.name).push(n.vid)
  }
  const byBase = new Map()
  for (const n of nodes) {
    if (n.kind !== 'file') continue
    const b = path.basename(n.file)
    if (!byBase.has(b)) byBase.set(b, [])
    byBase.get(b).push(n.vid)
  }

  const seen = new Set()
  const edges = []
  const push = (src, dst, type) => {
    const key = `${src}:${dst}:${type}`
    if (src === dst || seen.has(key)) return
    seen.add(key)
    edges.push({ src, dst, type })
  }
  for (const c of calls) {
    const hit = byName.get(c.name)
    if (hit && hit.length === 1) push(c.from, hit[0], 'call')
  }
  for (const inc of includes) {
    const hit = byBase.get(path.basename(inc.path))
    if (hit && hit.length === 1) push(inc.from, hit[0], 'include')
  }

  return { nodes, edges, files }
}

module.exports = { scan, makeVid }
