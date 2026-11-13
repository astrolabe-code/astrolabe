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

export interface BoardCard {
  id: string
  x: number
  y: number
  w: number
  h: number
  text: string
  /** 关联一篇笔记：双击卡片就打开它 */
  noteRef?: string
}

export interface BoardEdge {
  from: string
  to: string
}

export interface BoardLayoutData {
  cards: BoardCard[]
  edges: BoardEdge[]
  canvas: { w: number; h: number }
}

export interface BoardDoc {
  id: string
  name: string
  layout: BoardLayoutData
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

/** 仿写：一个节点下的多份默写 / 重写代码卡 */
export interface ImitationItem {
  id: string
  nodeVid: number
  title: string
  ext: string
  mtime: number
}

export interface ImitationDoc {
  id: string
  title: string
  ext: string
  text: string
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
  'boards.save': (projectRef: string, id: string, layout: BoardLayoutData, name?: string) => BoardItem
  'boards.remove': (projectRef: string, id: string) => void

  'imitation.list': (projectRef: string, nodeVid: number) => ImitationItem[]
  'imitation.get': (projectRef: string, id: string) => ImitationDoc
  'imitation.create': (projectRef: string, nodeVid: number, ext: string) => ImitationItem
  'imitation.save': (projectRef: string, id: string, text: string, title?: string) => ImitationItem
  'imitation.remove': (projectRef: string, id: string) => void

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
