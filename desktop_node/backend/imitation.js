const crypto = require('node:crypto')
const store = require('./store')

const MAX_BYTES = 512 * 1024

function list(projectRef, nodeVid) {
  return store
    .db(projectRef)
    .prepare(
      `SELECT id, node_vid AS nodeVid, title, ext, mtime FROM imitation
       WHERE node_vid = ? AND deleted_at IS NULL ORDER BY mtime`,
    )
    .all(nodeVid)
}

function get(projectRef, id) {
  const row = store
    .db(projectRef)
    .prepare('SELECT id, title, ext, text FROM imitation WHERE id = ? AND deleted_at IS NULL')
    .get(id)
  if (!row) throw new Error('仿写不存在')
  return row
}

function create(projectRef, nodeVid, ext) {
  const conn = store.db(projectRef)
  const count = conn
    .prepare('SELECT COUNT(*) AS c FROM imitation WHERE node_vid = ? AND deleted_at IS NULL')
    .get(nodeVid).c
  const item = {
    id: `i${Date.now().toString(36)}-${crypto.randomBytes(2).toString('hex')}`,
    nodeVid,
    title: `第 ${count + 1} 版`,
    ext: String(ext || 'txt').replace(/[^a-zA-Z0-9]/g, '').slice(0, 8) || 'txt',
    mtime: Date.now() / 1000,
  }
  conn
    .prepare('INSERT INTO imitation (id, node_vid, title, ext, text, mtime) VALUES (?, ?, ?, ?, ?, ?)')
    .run(item.id, nodeVid, item.title, item.ext, '', item.mtime)
  return item
}

function save(projectRef, id, text, title) {
  const conn = store.db(projectRef)
  const old = conn
    .prepare('SELECT title, node_vid, ext FROM imitation WHERE id = ? AND deleted_at IS NULL')
    .get(id)
  if (!old) throw new Error('仿写不存在')
  const body = String(text ?? '')
  if (Buffer.byteLength(body, 'utf8') > MAX_BYTES) throw new Error('单份仿写不能超过 512KB')
  const nextTitle = String(title ?? old.title).trim().slice(0, 80) || old.title
  const mtime = Date.now() / 1000
  conn
    .prepare('UPDATE imitation SET text = ?, title = ?, mtime = ? WHERE id = ?')
    .run(body, nextTitle, mtime, id)
  return { id, nodeVid: old.node_vid, title: nextTitle, ext: old.ext, mtime }
}

function remove(projectRef, id) {
  store
    .db(projectRef)
    .prepare('UPDATE imitation SET deleted_at = ? WHERE id = ?')
    .run(new Date().toISOString(), id)
}

module.exports = { list, get, create, save, remove }
