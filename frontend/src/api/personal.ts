/**
 * ★★★ **个人版适配层** —— 把边车的简洁形状，翻译成前端组件认识的形状
 *
 * ## 为什么需要这一层
 *
 * ```\n * 社区版 Django 返回   {ok, data:{...}} / 平铺 / 字段叫 seq、node_snapshot、is_public…\n * 个人版边车返回       {ok, data:{items:[{vid,kind,name,no,rel_path}]}}   （只有真需要的字段）\n * ```\n *
 * 所有者 2026-10-29 定：**让边车保持简洁，适配放在前端**（`query/` 本来就是适配层）。
 *
 * ⚠★ 因此个人版**不模拟** Django 的响应：不在边车里堆 `is_public` / `state` /
 *   `moderation_reason` 这些个人版根本不存在的字段，而是这里补默认值。
 *
 * ## 用法
 *
 * ```ts\n * const hooks = IS_PERSONAL ? personalApi : null\n * queryFn: () => hooks ? hooks.graphNodes(ref, limit, offset) : unwrap(await apiGet(...))\n * ```\n */

import type { Note, NoteKind } from './types'
import type { GraphNode } from '../lib/mergeGraph'

// ---------------------------------------------------------------- 基础请求

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const j = await r.json()
  if (!j || j.ok !== true) throw new Error((j && j.error) || `请求失败（${r.status}）`)
  return j.data as T
}

const get = <T>(p: string) => call<T>('GET', p)
const post = <T>(p: string, b?: unknown) => call<T>('POST', p, b ?? {})
const patch = <T>(p: string, b: unknown) => call<T>('PATCH', p, b)
const del = <T>(p: string) => call<T>('DELETE', p)

// ---------------------------------------------------------------- 形状适配

/** 边车节点 → `GraphNode`（组件只认这一种） */
function toGraphNode(n: any): GraphNode {
  return {
    vid: Number(n.vid),
    // ⚠ 个人版没有 uid 概念；用「kind#路径#名字」合成一个稳定的可读标识
    uid: `${n.kind}#${n.file_path}#${n.name}`,
    kind: String(n.kind || ''),
    name: String(n.name || ''),
    qname: String(n.qname || ''),
    file_path: String(n.file_path || ''),
    line: Number(n.line || 0),
    line_end: Number(n.line_end ?? -1),
    lang: '',
    origin: String(n.origin || 'parsed'),
    parent_uid: '',
  } as unknown as GraphNode
}

/** 边车笔记 → `Note`（补上个人版不存在的字段，保持组件不用改） */
function toNote(n: any, body = ''): Note {
  const vid = Number(n.node_vid || 0)
  return {
    id: Number(n.id || 0),
    ref: String(n.ref || ''),
    created_by_display: '我',
    node_id: vid,
    kind: (n.kind || 'flash') as NoteKind,
    title: String(n.title || ''),
    seq: Number(n.no || 0),
    node_snapshot: {
      vid,
      name: String(n.node_name || ''),
      kind: '',
      qname: '',
      file_path: String(n.file_path || ''),
      line: Number(n.line || 0),
      line_end: -1,
    },
    body,
    card_skin: '',
    is_public: true,
    state: 'active',
    moderation_reason: '',
    moderated_at: '',
    deleted_at: '',
    deleted_by: '',
    created_at: String(n.created_at || ''),
    updated_at: String(n.created_at || ''),
    // ⚠ 个人版没有评论/点赞 ⇒ 这三个计数恒为 0，组件照常渲染不报错
    comment_count: 0,
    like_count: 0,
    paragraph_comment_count: 0,
  } as unknown as Note
}

/** 边车项目 → `ProjectSummary`（个人版恒为"我的""已就绪"） */
export function toProjectSummary(raw: any, stats?: any): any {
  return {
    project_ref: String(raw.ref || ''),
    name: String(raw.name || ''),
    desc: '',
    is_public: true,
    owner: 'me',
    owner_display: '我',
    mine: true,
    /** ★ 个人版自己是作者 ⇒ 可写；真正的门槛在 parse_state（图不完整不给写）*/
    can_edit: true,
    parse_state: String(raw.parse_state || 'none'),
    /** ★ 空白结构：没有源码目录，节点与连线全靠手补（`B184`）*/
    is_blank: !String(raw.root || '').trim(),
    parse_error: String(raw.parse_error || ''),
    // ⚠ 个人版没有"排队/拉取"这些状态：有图就是 done
    status: String(raw.parsed_at ? 'done' : 'none'),
    progress: raw.parsed_at ? 100 : 0,
    // ⚠ 个人版的项目行里没有 node_count（那是 Django 侧聚合的）⇒ 用 stats 补
    node_count: Number(raw.node_count ?? stats?.nodes ?? 0),
    note_count: Number(
      raw.note_count ??
        Object.values(stats?.notesByKind || {}).reduce((a: number, b: any) => a + Number(b || 0), 0),
    ),
    created_at: String(raw.created_at || ''),
  }
}

// ---------------------------------------------------------------- 对外

export const personalApi = {
  // ---- 项目
  listProjects: () => get<{ items: any[] }>('/api/projects/'),

  createProject: (path: string, name: string) =>
    post<{ project: any }>('/api/projects/', { path, name }),

  getProject: async (ref: string) => {
    const d = await get<{ project: any; stats: any }>(`/api/projects/${encodeURIComponent(ref)}/`)
    return toProjectSummary(d.project, d.stats)
  },

  /** ★ 解析代码目录 → 图（个人版唯一的重活） */
  parseProject: (ref: string) =>
    post<{ stats: any; project: any }>(`/api/projects/${encodeURIComponent(ref)}/parse`),

  // ---- 节点
  graphNodes: async (ref: string, limit: number, offset: number) => {
    const d = await get<{ total: number; items: any[] }>(
      `/api/projects/${encodeURIComponent(ref)}/nodes/?limit=${limit}&offset=${offset}`,
    )
    return { total: Number(d.total || 0), items: (d.items || []).map(toGraphNode) }
  },

  /** ★★ 整张图（个人版一次给全，不走分页）⚠ */
  fullGraph: async (ref: string) => {
    const d = await get<{ rev: number; nodes: any[]; edges: any[] }>(
      `/api/projects/${encodeURIComponent(ref)}/graph/`,
    )
    const nodes = (d.nodes || []).map(toGraphNode)
    const edges = (d.edges || []).map((e) => ({
      id: Number(e.id),
      from: Number(e.from),
      to: Number(e.to),
      type: String(e.type || ''),
      line: null,
      origin: String(e.origin || 'parsed'),
      confidence: 'syntax',
    }))
    return { rev: Number(d.rev || 0), nodes, edges }
  },

  // ---- 笔记
  notes: async (ref: string, opts: { kind?: string; limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams()
    if (opts.kind) q.set('kind', opts.kind)
    const qs = q.toString()
    const d = await get<{ items: any[] }>(
      `/api/projects/${encodeURIComponent(ref)}/notes/${qs ? '?' + qs : ''}`,
    )
    // ⚠ 列表里没有正文（正文在单独文件里）⇒ body 留空，组件需要正文时会再取一次
    return (d.items || []).map((n) => toNote(n, ''))
  },

  note: async (ref: string) => {
    const d = await get<{ note: any; body: string }>(`/api/notes/${encodeURIComponent(ref)}/`)
    return { note: toNote(d.note, d.body), body: d.body }
  },

  createNote: async (
    projectRef: string,
    body: { node_id: number; kind: NoteKind; title?: string; body: string },
  ) => {
    const d = await post<{ note: any }>(
      `/api/projects/${encodeURIComponent(projectRef)}/notes/`,
      { node_vid: body.node_id, kind: body.kind, title: body.title || '', body: body.body },
    )
    return { note: toNote(d.note, body.body), body: body.body }
  },

  updateNote: async (ref: string, patchBody: { body?: string; title?: string; kind?: string }) => {
    const d = await patch<{ note: any }>(`/api/notes/${encodeURIComponent(ref)}/`, patchBody)
    return { note: toNote(d.note, patchBody.body || ''), body: patchBody.body || '' }
  },

  deleteNote: (ref: string) => del<{ deleted: string }>(`/api/notes/${encodeURIComponent(ref)}/`),
}
