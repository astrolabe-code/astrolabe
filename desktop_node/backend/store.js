const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const Database = require('better-sqlite3')

let dataDir = ''
let projectsPath = ''
const connections = new Map()

const SCHEMA = `
CREATE TABLE IF NOT EXISTS node (
  vid INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
  qname TEXT NOT NULL DEFAULT '', file TEXT NOT NULL DEFAULT '', line INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS edge (
  id INTEGER PRIMARY KEY, src INTEGER NOT NULL, dst INTEGER NOT NULL, type TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS note (
  ref TEXT PRIMARY KEY, node_vid INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'flash',
  title TEXT NOT NULL DEFAULT '', mtime REAL NOT NULL DEFAULT 0,
  rel_path TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_note_node ON note (node_vid);
CREATE TABLE IF NOT EXISTS board (
  id TEXT PRIMARY KEY, node_vid INTEGER NOT NULL, name TEXT NOT NULL DEFAULT '',
  layout TEXT NOT NULL DEFAULT '{}', mtime REAL NOT NULL DEFAULT 0, deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_board_node ON board (node_vid);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
`

function init(dir) {
  dataDir = dir
  fs.mkdirSync(dir, { recursive: true })
  projectsPath = path.join(dir, 'projects.json')
  if (!fs.existsSync(projectsPath)) fs.writeFileSync(projectsPath, '[]', 'utf8')
}

function readProjects() {
  try {
    return JSON.parse(fs.readFileSync(projectsPath, 'utf8'))
  } catch {
    return []
  }
}

function writeProjects(list) {
  const tmp = projectsPath + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(list, null, 2), 'utf8')
  fs.renameSync(tmp, projectsPath)
}

function getProject(ref) {
  const p = readProjects().find((x) => x.ref === ref)
  if (!p) throw new Error('项目不存在')
  return p
}

function addProject(root) {
  const abs = path.resolve(root)
  if (!fs.existsSync(abs) || !fs.statSync(abs).isDirectory()) throw new Error('目录不存在')
  const name = path.basename(abs)
  const ref = `${name.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-')}-${crypto.randomBytes(2).toString('hex')}`
  const project = {
    ref,
    name,
    root: abs,
    dataDir: path.join(abs, '.astrolabe'),
    createdAt: new Date().toISOString(),
  }
  const list = readProjects()
  list.push(project)
  writeProjects(list)
  db(ref)
  return project
}

function removeProject(ref) {
  const conn = connections.get(ref)
  if (conn) {
    conn.close()
    connections.delete(ref)
  }
  writeProjects(readProjects().filter((x) => x.ref !== ref))
}

function db(ref) {
  if (connections.has(ref)) return connections.get(ref)
  const p = getProject(ref)
  fs.mkdirSync(path.join(p.dataDir, 'notes'), { recursive: true })
  fs.mkdirSync(path.join(p.dataDir, 'trash'), { recursive: true })
  const conn = new Database(path.join(p.dataDir, 'index.db'))
  conn.pragma('journal_mode = WAL')
  conn.exec(SCHEMA)
  try {
    conn.exec('CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(ref UNINDEXED, title, body)')
  } catch {
    /* 没编进 FTS5 时退化成文件扫描，不影响主流程 */
  }
  connections.set(ref, conn)
  return conn
}

function notesDir(ref) {
  return path.join(getProject(ref).dataDir, 'notes')
}

function trashDir(ref) {
  return path.join(getProject(ref).dataDir, 'trash')
}

module.exports = {
  init,
  readProjects,
  getProject,
  addProject,
  removeProject,
  db,
  notesDir,
  trashDir,
  get dataDir() {
    return dataDir
  },
}
