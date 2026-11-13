const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const store = require('./store')

function parse(text) {
  if (!text.startsWith('---\n')) return { meta: {}, body: text }
  const end = text.indexOf('\n---\n', 4)
  if (end < 0) return { meta: {}, body: text }
  const meta = {}
  for (const line of text.slice(4, end).split('\n')) {
    const i = line.indexOf(':')
    if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim()
  }
  return { meta, body: text.slice(end + 5) }
}

function serialize(meta, body) {
  const head = Object.entries(meta)
    .map(([k, v]) => `${k}: ${v}`)
    .join('\n')
  return `---\n${head}\n---\n${body}`
}

function fileOf(projectRef, noteRef) {
  return path.join(store.notesDir(projectRef), `${noteRef}.md`)
}

function syncFts(conn, ref, title, body) {
  try {
    conn.prepare('DELETE FROM note_fts WHERE ref = ?').run(ref)
    conn.prepare('INSERT INTO note_fts (ref, title, body) VALUES (?, ?, ?)').run(ref, title, body)
  } catch {
    /* 没有 FTS5 就跳过 */
  }
}

function list(projectRef, nodeVid) {
  const conn = store.db(projectRef)
  const sql =
    'SELECT ref, node_vid AS nodeVid, kind, title, mtime FROM note ' +
    (nodeVid == null ? '' : 'WHERE node_vid = ? ') +
    'ORDER BY mtime DESC'
  return nodeVid == null ? conn.prepare(sql).all() : conn.prepare(sql).all(nodeVid)
}

function get(projectRef, noteRef) {
  const file = fileOf(projectRef, noteRef)
  if (!fs.existsSync(file)) throw new Error('笔记不存在')
  return parse(fs.readFileSync(file, 'utf8'))
}

function save(projectRef, noteRef, body, title, nodeVid) {
  const conn = store.db(projectRef)
  const old = noteRef ? conn.prepare('SELECT * FROM note WHERE ref = ?').get(noteRef) : null
  const ref = noteRef || `n${Date.now().toString(36)}-${crypto.randomBytes(2).toString('hex')}`
  const meta = {
    ref,
    title: title ?? old?.title ?? '',
    node_vid: String(nodeVid ?? old?.node_vid ?? 0),
    kind: old?.kind ?? 'flash',
    created: old?.created_at ?? new Date().toISOString(),
  }
  const file = fileOf(projectRef, ref)
  const tmp = file + '.tmp'
  fs.writeFileSync(tmp, serialize(meta, body), 'utf8')
  fs.renameSync(tmp, file)
  const mtime = fs.statSync(file).mtimeMs / 1000
  conn
    .prepare(
      `INSERT INTO note (ref, node_vid, kind, title, mtime, rel_path, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(ref) DO UPDATE SET
         node_vid = excluded.node_vid, title = excluded.title, mtime = excluded.mtime`,
    )
    .run(ref, Number(meta.node_vid), meta.kind, meta.title, mtime, `notes/${ref}.md`, meta.created)
  syncFts(conn, ref, meta.title, body)
  return { ref, nodeVid: Number(meta.node_vid), kind: meta.kind, title: meta.title, mtime }
}

function remove(projectRef, noteRef) {
  const conn = store.db(projectRef)
  const file = fileOf(projectRef, noteRef)
  if (fs.existsSync(file)) {
    fs.renameSync(file, path.join(store.trashDir(projectRef), `${noteRef}.md`))
  }
  conn.prepare('DELETE FROM note WHERE ref = ?').run(noteRef)
  try {
    conn.prepare('DELETE FROM note_fts WHERE ref = ?').run(noteRef)
  } catch {
    /* 没有 FTS5 就跳过 */
  }
}

module.exports = { parse, serialize, list, get, save, remove }
