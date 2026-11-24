/**
 * ★ Astrolabe 解析核心（WASM tree-sitter，纯 JS，桌面/移动通用）
 *
 * 从 desktop_node/backend/parse/scan.js 移植，两处关键改动：
 *   1. 文件来源：node:fs → Obsidian app.vault（vault 内文件）
 *   2. wasm 来源：node:fs → app.vault.adapter.readBinary（桌面/移动都能读）
 *
 * vid 用 blakejs BLAKE2b-64 取低 53 位 —— 已验证与 Python 版逐位一致。
 */

import { blake2b } from 'blakejs'

/** 支持的语言 → grammar wasm 文件名（在插件 wasm/ 目录下） */
export const LANGS = {
  '.c': 'tree-sitter-c.wasm',
  '.h': 'tree-sitter-c.wasm',
  '.cc': 'tree-sitter-cpp.wasm',
  '.cpp': 'tree-sitter-cpp.wasm',
  '.cxx': 'tree-sitter-cpp.wasm',
  '.hpp': 'tree-sitter-cpp.wasm',
  '.hh': 'tree-sitter-cpp.wasm',
  '.hxx': 'tree-sitter-cpp.wasm',
  '.java': 'tree-sitter-java.wasm',
  '.py': 'tree-sitter-python.wasm',
  '.pyi': 'tree-sitter-python.wasm',
}

/** 声明节点类型 → 产品里的 kind */
const DEFS = {
  function_definition: 'function',
  method_declaration: 'function',
  function_declarator: 'function',
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
const INCLUDES = new Set(['preproc_include', 'import_statement', 'import_from_statement'])

/** vid = BLAKE2b-64(canonical) & 低53位，与 Python identity.hash53 完全一致 */
export function hash53(text) {
  const d = blake2b(new TextEncoder().encode(String(text)), null, 8)
  // ★ 大端序 —— 与 Python 的 int.from_bytes(digest, "big") 一致。
  //   ⛔ 用 i 从后往前（小端）会得到完全不同的 vid（实测差 4.8 倍）。
  let n = 0n
  for (let i = 0; i < d.length; i++) n = (n << 8n) | BigInt(d[i])
  return Number(n & 0x1fffffffffffffn)
}

/** canonical 规范串：kind|rel_path|name|line|line_end（与 Python 一致） */
export function canonical(kind, relPath, name, line, lineEnd) {
  const k = typeof kind === 'number' ? kind : 0
  const ln = Number.isInteger(line) && line >= 0 ? line : -1
  const end = Number.isInteger(lineEnd) && lineEnd >= 0 ? lineEnd : -1
  return `${k}|${relPath || ''}|${name || ''}|${ln}|${end}`
}

/** 确定性分配 vid（撞车按排序后规范串重哈希），与 Python assign_vids 一致 */
export function assignVids(canons) {
  const used = new Map()
  const out = new Map()
  for (const canon of [...new Set(canons)].sort()) {
    let vid = hash53(canon)
    let n = 0
    while (used.has(vid) && used.get(vid) !== canon) {
      n++
      vid = hash53(`${canon}|${n}`)
    }
    used.set(vid, canon)
    out.set(canon, vid)
  }
  return out
}

/** WASM 运行时：整个插件只初始化一次 */
let runtimePromise = null
export async function getRuntime(app, pluginDir) {
  if (!runtimePromise) {
    runtimePromise = (async () => {
      const WTS = await import('web-tree-sitter')
      const runtimeBytes = await app.vault.adapter.readBinary(`${pluginDir}/wasm/web-tree-sitter.wasm`)
      // ★★ 必须传 locateFile：web-tree-sitter 0.27 在 CJS 环境里
      //   import.meta.url 为空，不设 locateFile 会报 "Invalid URL"（实测）。
      //   设了之后它用我们给的 wasmBinary，不再自己找文件。
      await WTS.Parser.init({
        wasmBinary: new Uint8Array(runtimeBytes),
        locateFile: () => 'web-tree-sitter.wasm',
      })
      return WTS
    })().catch((e) => {
      runtimePromise = null
      throw e
    })
  }
  return runtimePromise
}

/** 加载某个语言的 grammar（每种语言只加载一次） */
async function languageFor(WTS, app, pluginDir, file, cache) {
  if (cache.has(file)) return cache.get(file)
  const bytes = await app.vault.adapter.readBinary(`${pluginDir}/wasm/${file}`)
  const lang = await WTS.Language.load(new Uint8Array(bytes))
  cache.set(file, lang)
  return lang
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

function importPath(node) {
  const p = node.childForFieldName('path') || node.childForFieldName('source')
  if (!p) return null
  return p.text.replace(/^["'<]/, '').replace(/["'>]$/, '')
}

/**
 * 扫描 vault 内的代码文件，产出 { nodes, edges, files, errors }。
 * @param {object} app  Obsidian app
 * @param {string} pluginDir 插件目录（this.manifest.dir）
 * @param {object} [opts] { maxFiles, maxBytes, onProgress }
 */
export async function scanVault(app, pluginDir, opts = {}) {
  const maxFiles = opts.maxFiles || 500
  const maxBytes = opts.maxBytes || 512 * 1024
  const WTS = await getRuntime(app, pluginDir)
  const langCache = new Map()
  const parsers = new Map()

  // ★ Obsidian 的 TFile.extension **不带点**（'py' 不是 '.py'）
  const extKey = (ext) => {
    const e = String(ext || '').toLowerCase()
    return e.startsWith('.') ? e : '.' + e
  }
  const allFiles = app.vault.getFiles().filter((f) => !!LANGS[extKey(f.extension)])
  const targets = allFiles.slice(0, maxFiles)

  const nodes = []
  const calls = []
  const imports = []
  const errors = []
  let files = 0

  for (const file of targets) {
    try {
      let text = await app.vault.read(file)
      if (text.length > maxBytes) continue
      const grammar = LANGS[extKey(file.extension)]
      if (!parsers.has(grammar)) {
        const lang = await languageFor(WTS, app, pluginDir, grammar, langCache)
        const p = new WTS.Parser()
        p.setLanguage(lang)
        parsers.set(grammar, p)
      }
      const tree = parsers.get(grammar).parse(text)
      files++

      const rel = file.path
      const fileVid = hash53(canonical('file', rel, rel, 0, -1))
      nodes.push({
        vid: fileVid, kind: 'file', name: file.name,
        qname: rel, file: rel, line: 0, lineEnd: -1,
      })

      const visit = (n, stack, ownerVid) => {
        let nextStack = stack
        let nextOwner = ownerVid
        const kind = DEFS[n.type]
        if (kind) {
          const name = nodeName(n)
          if (name) {
            const qname = [...stack, name].join('.')
            const vid = hash53(canonical(kind, rel, qname, n.startPosition.row + 1, n.endPosition.row + 1))
            nodes.push({
              vid, kind, name, qname, file: rel,
              line: n.startPosition.row + 1, lineEnd: n.endPosition.row + 1,
            })
            nextStack = [...stack, name]
            nextOwner = vid
          }
        }
        if (CALLS.has(n.type)) {
          const name = calleeName(n)
          if (name) calls.push({ name, from: nextOwner })
        }
        if (INCLUDES.has(n.type)) {
          const p = importPath(n)
          if (p) imports.push({ path: p, from: nextOwner })
        }
        for (const c of n.namedChildren) visit(c, nextStack, nextOwner)
      }
      visit(tree.rootNode, [], fileVid)
    } catch (e) {
      errors.push({ file: file.path, error: String(e && e.message || e) })
    }
    if (opts.onProgress) opts.onProgress(files, targets.length)
  }

  // 同名定义唯一才连边（宁可漏不要错，与 Python 个人版口径一致）
  const byName = new Map()
  for (const n of nodes) {
    if (!byName.has(n.name)) byName.set(n.name, [])
    byName.get(n.name).push(n.vid)
  }
  const byBase = new Map()
  for (const n of nodes) {
    if (n.kind !== 'file') continue
    const b = n.name
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
  for (const inc of imports) {
    const hit = byBase.get(inc.path.split('/').pop()) || byName.get(inc.path.split('/').pop())
    if (hit && hit.length === 1) push(inc.from, hit[0], 'import')
  }

  return { nodes, edges, files, scanned: targets.length, errors }
}
