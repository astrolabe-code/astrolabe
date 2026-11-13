const fs = require('node:fs')
const path = require('node:path')
const store = require('./store')

const SKIP = new Set(['.git', 'node_modules', '.astrolabe', 'dist', '__pycache__', '.venv'])

function walk(base, rel, out, depth) {
  if (depth > 6 || out.length > 3000) return
  let entries
  try {
    entries = fs.readdirSync(path.join(base, rel), { withFileTypes: true })
  } catch {
    return
  }
  for (const e of entries) {
    if (SKIP.has(e.name)) continue
    const r = rel ? `${rel}/${e.name}` : e.name
    if (e.isDirectory()) walk(base, r, out, depth + 1)
    else out.push(r)
  }
}

function tree(projectRef) {
  const out = []
  walk(store.getProject(projectRef).root, '', out, 0)
  return { items: out }
}

function read(projectRef, relPath) {
  const project = store.getProject(projectRef)
  const abs = path.resolve(project.root, relPath)
  if (!abs.startsWith(project.root + path.sep)) throw new Error('路径越界')
  const st = fs.statSync(abs)
  if (!st.isFile()) throw new Error('不是文件')
  if (st.size > 512 * 1024) throw new Error('文件超过 512KB')
  return { text: fs.readFileSync(abs, 'utf8'), lang: path.extname(abs).slice(1) }
}

module.exports = { tree, read }
