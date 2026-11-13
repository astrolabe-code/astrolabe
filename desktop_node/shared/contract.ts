/** 前后端唯一的契约：方法名、参数、返回值。后端用 JSDoc 引用 Handlers。 */

export interface Project {
  ref: string
  name: string
  root: string
  dataDir: string
  createdAt: string
}

export interface NoteItem {
  ref: string
  nodeVid: number
  kind: string
  title: string
  mtime: number
}

export interface NoteDoc {
  meta: Record<string, string>
  body: string
}

export interface BoardItem {
  id: string
  nodeVid: number
  name: string
  mtime: number
}

export interface BoardDoc {
  id: string
  name: string
  layout: Record<string, unknown>
}

export interface GraphNode {
  vid: number
  kind: string
  name: string
  qname: string
  file: string
  line: number
}

export interface GraphEdge {
  id: number
  from: number
  to: number
  type: string
}

export interface Graph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  rev: number
}

export interface SourceFile {
  items: string[]
}

export interface SourceText {
  text: string
  lang: string
}

export interface ParseReport {
  nodes: number
  edges: number
  files: number
}

export interface Api {
  'window.minimize': () => void
  'window.toggleMaximize': () => void
  'window.close': () => void

  'projects.list': () => Project[]
  'projects.add': (root: string) => Project
  'projects.remove': (ref: string) => void

  'notes.list': (projectRef: string, nodeVid?: number) => NoteItem[]
  'notes.get': (projectRef: string, ref: string) => NoteDoc
  'notes.save': (projectRef: string, ref: string, body: string, title?: string, nodeVid?: number) => NoteItem
  'notes.remove': (projectRef: string, ref: string) => void

  'boards.list': (projectRef: string, nodeVid: number) => BoardItem[]
  'boards.get': (projectRef: string, id: string) => BoardDoc
  'boards.create': (projectRef: string, nodeVid: number, name: string) => BoardItem
  'boards.save': (projectRef: string, id: string, layout: Record<string, unknown>, name?: string) => BoardItem
  'boards.remove': (projectRef: string, id: string) => void

  'graph.nodes': (projectRef: string) => GraphNode[]
  'graph.full': (projectRef: string) => Graph
  'project.parse': (projectRef: string) => ParseReport
  'source.tree': (projectRef: string) => SourceFile
  'source.read': (projectRef: string, relPath: string) => SourceText
}

export type Handlers = {
  [K in keyof Api]: (
    ...args: Parameters<Api[K]>
  ) => ReturnType<Api[K]> | Promise<ReturnType<Api[K]>>
}

/** 后端实现的那部分（窗口控制与解析调度由 Electron 主进程自己处理） */
export type BackendHandlers = Omit<Handlers, `window.${string}` | 'project.parse'>
