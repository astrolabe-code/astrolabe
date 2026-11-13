const store = require('./store')

function list(projectRef, nodeVid) {
  return store
    .db(projectRef)
    .prepare(
      `SELECT id, node_vid AS nodeVid, name, mtime FROM board
       WHERE node_vid = ? AND deleted_at IS NULL ORDER BY mtime DESC`,
    )
    .all(nodeVid)
}

function get(projectRef, id) {
  const row = store
    .db(projectRef)
    .prepare('SELECT id, name, layout FROM board WHERE id = ? AND deleted_at IS NULL')
    .get(id)
  if (!row) throw new Error('白板不存在')
  let layout = {}
  try {
    layout = JSON.parse(row.layout || '{}')
  } catch {
    layout = {}
  }
  return { id: row.id, name: row.name, layout }
}

function create(projectRef, nodeVid, name) {
  const id = `${nodeVid}_${Date.now()}`
  const mtime = Date.now() / 1000
  store
    .db(projectRef)
    .prepare('INSERT INTO board (id, node_vid, name, layout, mtime) VALUES (?, ?, ?, ?, ?)')
    .run(id, nodeVid, name || '白板', '{}', mtime)
  return { id, nodeVid, name: name || '白板', mtime }
}

function save(projectRef, id, layout, name) {
  const conn = store.db(projectRef)
  const old = conn.prepare('SELECT name, node_vid FROM board WHERE id = ? AND deleted_at IS NULL').get(id)
  if (!old) throw new Error('白板不存在')
  const nextName = name ?? old.name
  const mtime = Date.now() / 1000
  conn
    .prepare('UPDATE board SET layout = ?, name = ?, mtime = ? WHERE id = ?')
    .run(JSON.stringify(layout || {}), nextName, mtime, id)
  return { id, nodeVid: old.node_vid, name: nextName, mtime }
}

function remove(projectRef, id) {
  store
    .db(projectRef)
    .prepare('UPDATE board SET deleted_at = ? WHERE id = ?')
    .run(new Date().toISOString(), id)
}

module.exports = { list, get, create, save, remove }
