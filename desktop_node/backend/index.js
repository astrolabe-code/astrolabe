const store = require('./store')
const notes = require('./notes')
const boards = require('./boards')
const source = require('./source')

/** @type {import('../shared/contract').BackendHandlers} */
const handlers = {
  'projects.list': () => store.readProjects(),
  'projects.add': (root) => store.addProject(root),
  'projects.remove': (ref) => store.removeProject(ref),

  'notes.list': (ref, nodeVid) => notes.list(ref, nodeVid),
  'notes.get': (ref, noteRef) => notes.get(ref, noteRef),
  'notes.save': (ref, noteRef, body, title, nodeVid) => notes.save(ref, noteRef, body, title, nodeVid),
  'notes.remove': (ref, noteRef) => notes.remove(ref, noteRef),

  'boards.list': (ref, nodeVid) => boards.list(ref, nodeVid),
  'boards.get': (ref, id) => boards.get(ref, id),
  'boards.create': (ref, nodeVid, name) => boards.create(ref, nodeVid, name),
  'boards.save': (ref, id, layout, name) => boards.save(ref, id, layout, name),
  'boards.remove': (ref, id) => boards.remove(ref, id),

  'graph.full': (ref) => {
    const conn = store.db(ref)
    return {
      nodes: conn.prepare('SELECT vid, kind, name, qname, file, line FROM node').all(),
      edges: conn.prepare('SELECT id, src AS "from", dst AS "to", type FROM edge').all(),
      rev: 0,
    }
  },
  'source.tree': (ref) => source.tree(ref),
  'source.read': (ref, relPath) => source.read(ref, relPath),
}

module.exports = { handlers, init: store.init }
