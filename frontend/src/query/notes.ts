import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPatch, apiPost, getCsrfToken, upload } from '../api/client'
import { unwrap } from '../api/errors'
import { IS_PERSONAL } from '../lib/personal'
import { personalApi } from '../api/personal'
import type {
  DeletedNote,
  ImportResult,
  Note,
  NoteBlock,
  NoteDetailData,
  NoteKind,
  NoteListData,
  NoteSearchItem,
} from '../api/types'

/**
 * ★ 笔记数据层（`B187` / `B188` / `B201` / `B210` · 契约 §22.2）
 *
 * ## ⚠★ 三条必须理解的约定
 *
 * | # | 约定 | 前端后果 |
 * |---|---|---|
 * | ① | ★★ `blocks` 由**后端**重算并返回 | ❌ 前端不自己切段落；PATCH 改了 `body` ⇒ **必须**用响应的 `blocks` 刷新段评锚点 |
 * | ② | ★★ 删除是**软删**（`B210`） | 删完进回收站（`useDeletedNotes` 可见），可恢复；⚠ **不得**向用户承诺「彻底删除」 |
 * | ③ | ★★ 被隐藏（`state=hidden`）/ 软删的笔记 | 对非作者**不可见**（列表直接没有），详情 404 |
 *
 * ⚠ 本模块**只做数据层**（F1）—— 编辑器 / 卡片 / 回收站页面在 F2/F3 消费这些钩子。
 */

/** GET /api/projects/<ref>/notes/?kind=&limit=&offset=（② 型） */
export function useNotes(
  projectRef?: string | null,
  opts: { kind?: NoteKind; limit?: number; offset?: number } = {},
) {
  const kind = opts.kind ?? ''
  return useQuery({
    queryKey: ['notes', projectRef, { kind, limit: opts.limit, offset: opts.offset }],
    enabled: !!projectRef,
    queryFn: async (): Promise<Note[]> => {
      // ★★ 个人版：本地边车（列表里没有正文，正文按需再取）
      if (IS_PERSONAL) return personalApi.notes(projectRef!, { kind: kind || undefined })
      const q = new URLSearchParams()
      if (kind) q.set('kind', kind)
      if (opts.limit != null) q.set('limit', String(opts.limit))
      if (opts.offset != null) q.set('offset', String(opts.offset))
      const qs = q.toString()
      const data = unwrap(
        await apiGet<NoteListData>(
          `/api/projects/${encodeURIComponent(projectRef!)}/notes/${qs ? `?${qs}` : ''}`,
          'spread',
        ),
      )
      return data.items || []
    },
  })
}

/** GET /api/notes/<id>/（② 型）⇒ {note, blocks} */
export function useNote(noteId?: string | null) {
  return useQuery({
    queryKey: ['note', noteId],
    enabled: !!noteId,
    queryFn: async (): Promise<NoteDetailData> =>
      IS_PERSONAL
        ? (personalApi.note(noteId!) as unknown as Promise<NoteDetailData>)
        : unwrap(await apiGet<NoteDetailData>(`/api/notes/${noteId!}/`, 'spread')),
  })
}

export interface CreateNoteBody {
  kind: NoteKind
  body: string
  node_id: number
  title?: string
  is_public?: boolean
}

/** POST /api/projects/<ref>/notes/（② 型）⇒ {note, blocks} */
export function useCreateNote(projectRef?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: CreateNoteBody): Promise<NoteDetailData> =>
      IS_PERSONAL
        ? (personalApi.createNote(projectRef!, body) as unknown as Promise<NoteDetailData>)
        : unwrap(
            await apiPost<NoteDetailData>(
              `/api/projects/${encodeURIComponent(projectRef!)}/notes/`,
              body,
              'spread',
            ),
          ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['notes', projectRef] })
    },
  })
}

export interface UpdateNoteBody {
  kind?: NoteKind
  title?: string
  body?: string
  card_skin?: string
  is_public?: boolean
  /** ★★ 重挂锚点（`D125`）—— stable_vid；⛔ 不是主键、不是 uid ⚠ */
  node_id?: number
}

/**
 * PATCH /api/notes/<id>/（② 型）⇒ {note, blocks}
 *
 * ⚠★ **改了 `body` ⇒ 后端重算段落**：失锚的段评按项目策略处置
 *   （`hide` 默认不进章评区 / `move_to_chapter` 进且标 `orphaned:true`）——
 *   ★★ 调用方**必须**用返回的 `blocks` 刷新锚点，❌ 不能继续用旧 block_id ⚠
 */
/**
 * ★★★ **批量改公开 / 私有**（* 2026-10-21 · 所有者）⚠
 *
 * `POST /api/projects/<ref>/notes/batch-visibility/`
 * body: `{is_public, exclude_ids}` —— 勾上的那些**不动**，其余全改
 */
export function useBatchVisibility(projectRef: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { is_public: boolean; exclude_ids: number[] }) =>
      unwrap(
        await apiPost<{ updated: number; is_public: boolean; excluded: number }>(
          `/api/projects/${encodeURIComponent(projectRef)}/notes/batch-visibility/`,
          payload,
          'spread',
        ),
      ),
    onSuccess: () => {
      // ★ 列表 / 搜索都要重拉（* 可见性变了，搜索结果也会变）⚠
      void qc.invalidateQueries({ queryKey: ['notes'] })
      void qc.invalidateQueries({ queryKey: ['notes-search'] })
    },
  })
}

export function useUpdateNote(noteId?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: UpdateNoteBody): Promise<NoteDetailData> =>
      IS_PERSONAL
        ? (personalApi.updateNote(noteId!, body) as unknown as Promise<NoteDetailData>)
        : unwrap(await apiPatch<NoteDetailData>(`/api/notes/${noteId!}/`, body, 'spread')),
    onSuccess: (data) => {
      qc.setQueryData(['note', noteId], data)
      void qc.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}

/**
 * DELETE /api/notes/<id>/ —— ★★ **软删**（`B210`）
 *
 * ⚠ 删完不级联消失：段落 / 评论 / 点赞**原样留着**，恢复即全文回来 ✅
 * ⚠ 删除确认框必须写明「可从回收站恢复」（`D86`③）—— ❌ 不许承诺「彻底删除」⚠
 */
export function useDeleteNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (noteId: string): Promise<{ deleted: boolean }> =>
      IS_PERSONAL
        ? personalApi.deleteNote(noteId).then(() => ({ deleted: true }))
        : unwrap(await apiDelete<{ deleted: boolean }>(`/api/notes/${noteId}/`, undefined, 'spread')),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['notes'] })
      void qc.invalidateQueries({ queryKey: ['deleted-notes'] })
    },
  })
}

/**
 * GET /api/me/notes/deleted/（② 型）—— ★★ **回收站**（`B210` / `D86`）
 *
 * ⚠★ 装什么：`deleted_at` 非空 ∧（我是作者 ∨ 项目 owner ∨ 项目协作者）
 *   ⇒ ★★ **协作者删的自己的笔记也在这里**，列表带 `deleted_by`（谁删的）✅
 * ⚠ 列表**不含正文**（无 `body` 字段）—— 先看元信息，恢复后再看内容 ✅
 */
export function useDeletedNotes(opts: { limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: ['deleted-notes', { limit: opts.limit, offset: opts.offset }],
    queryFn: async (): Promise<{ total: number; items: DeletedNote[] }> => {
      const q = new URLSearchParams()
      if (opts.limit != null) q.set('limit', String(opts.limit))
      if (opts.offset != null) q.set('offset', String(opts.offset))
      const qs = q.toString()
      const data = unwrap(
        await apiGet<{ total: number; limit: number; offset: number; items: DeletedNote[] }>(
          `/api/me/notes/deleted/${qs ? `?${qs}` : ''}`,
          'spread',
        ),
      )
      return { total: data.total, items: data.items || [] }
    },
  })
}

/**
 * POST /api/notes/<id>/undelete/（② 型）—— ★★ **从回收站恢复**
 *
 * ⚠ 谁能恢复 = 谁能删（作者 ∨ 协作者 ∨ owner）；不在回收站里 ⇒ 404
 * ⚠ 恢复后段落按 `realign` 重算并返回新 `blocks`（`D86`②）✅
 */
export function useUndeleteNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (noteId: string): Promise<NoteDetailData> =>
      unwrap(await apiPost<NoteDetailData>(`/api/notes/${noteId}/undelete/`, undefined, 'spread')),
    onSuccess: (data) => {
      qc.setQueryData(['note', data.note.ref], data)
      void qc.invalidateQueries({ queryKey: ['notes'] })
      void qc.invalidateQueries({ queryKey: ['deleted-notes'] })
    },
  })
}

/** ★ 导出给 F2 编辑器用：从响应里取 blocks 的便捷类型 */
export type { Note, NoteBlock }


/**
 * ★★★ `B231`：**把回收站按项目分组**（* 前端据此渲染项目卡片）⚠
 *
 * ```
 * ★★ 分组键 = `project_ref`（* 项目已删的用快照里的那个）✅
 * ```
 */
export function groupByProject(notes: DeletedNote[]) {
  const groups = new Map<string, { project_name: string; version_label: string; notes: DeletedNote[] }>()
  for (const n of notes) {
    const key = n.project_ref || `note-${n.id}`
    const g = groups.get(key)
    if (g) {
      g.notes.push(n)
    } else {
      groups.set(key, { project_name: n.project_name, version_label: n.version_label, notes: [n] })
    }
  }
  return [...groups.entries()].map(([project_ref, g]) => ({ project_ref, ...g }))
}

/**
 * POST /api/me/deleted/export/（`B231`）—— ★★ **导出所选笔记**
 *
 * ⚠ 响应是**二进制**（`.astrolabe-backup`，签名容器）⇒ ⛔ 不能走 `apiPost`
 *   （它会把响应当 JSON/text 解析，二进制会被毁）✅
 */
export async function downloadNotesBackup(noteIds: number[]): Promise<void> {
  // ★ B245：导出走 session；B247②：带 CSRF 头 ⚠
  const csrf = getCsrfToken()
  const res = await fetch('/api/me/deleted/export/', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/octet-stream',
      ...(csrf ? { 'X-CSRFToken': csrf } : {}),
    },
    body: JSON.stringify({ note_ids: noteIds }),
  })
  if (!res.ok) {
    let msg = `导出失败（${res.status}）`
    try {
      const data = await res.json()
      msg = data?.error?.message || data?.error || msg
    } catch {
      /* 非 JSON 响应就用默认文案 */
    }
    throw new Error(msg)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `astrolabe-笔记备份-${new Date().toISOString().slice(0, 10)}.backup`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/**
 * POST /api/notes/import/（`B231` / `B232`）—— ★★ **从导出包恢复笔记**
 *
 * ⚠★ 先验签再解包；挂不回原节点的会如实上报（`unanchored_count`）⚠
 */
export function useImportNotes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { file: File; projectRef: string }): Promise<ImportResult> => {
      const handle = upload('/api/notes/import/', vars.file, {
        field: 'file',
        extra: { project_ref: vars.projectRef },
      })
      const result = await handle.promise
      if (!result.ok) throw new Error(result.error?.message || '导入失败')
      return unwrap(result as any)
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}

/**
 * ★★ 全局笔记搜索（`GET /api/notes/search/?q=`）—— 首页搜索框用
 *
 * ⚠ 匹配**标题 + 正文**（后端 `icontains`）✅
 * ⚠ 每篇带 `project` 三件套 ⇒ 前端能链回项目 ✅
 */
/**
 * ★★★ **关键词联想**（`D109` 补充 · 2026-10-22）⚠
 *
 * > 「点联想不要直接进详情，联想只是关键词而已，表示用户选中这个关键词进行搜素。
 * >   这就可以重点字符联想了。比如搜红色，下边出现火红色。」
 *
 * ⚠ 走 `icontains`（标题 / 项目名），⛔ 不是 Meili —— 因为 Meili 只做词前缀，
 *   而联想要的正是**中缀**（输入「红色」提示「火红色」）⚠
 */
export function useSearchSuggest(q: string) {
  const kw = q.trim()
  return useQuery({
    queryKey: ['search-suggest', kw],
    enabled: kw.length > 0,
    staleTime: 30_000,
    // ★ 被限流（429）时不重试：* 联想是可选增强，* 重试只会加重限流 ⚠
    retry: false,
    queryFn: async (): Promise<{ text: string; type: 'note' | 'project' | 'term' }[]> => {
      const data = unwrap(
        await apiGet<{ items: { text: string; type: 'note' | 'project' | 'term' }[] }>(
          `/api/search/suggest/?q=${encodeURIComponent(kw)}`,
          'spread',
        ),
      )
      return data.items || []
    },
  })
}


export interface NoteSearchPage {
  items: NoteSearchItem[]
  total: number
  expanded?: { query: string; terms: string[]; matched: number }
  offset: number
}

/**
 * ★★★ **搜索结果（无限滚动）**（`D109` · 2026-10-23）⚠
 *
 * > 「搜索结构不要分页展示了，这样有些问题，直接就是像CSDN一样，往下滑，就刷出新的就行。」
 *
 * ```
 * 首屏 offset=0；滚到底部 ⇒ fetchNextPage() ⇒ offset+=limit
 * hasNextPage：最后一页条数 == limit 才继续（* 不满就是到底了）
 * ```
 */
export function useNoteSearch(
  q: string,
  opts: { limit?: number; sort?: 'relevance' | 'newest' } = {},
) {
  const kw = q.trim()
  const limit = opts.limit ?? 20
  const sort = opts.sort ?? 'relevance'

  return useInfiniteQuery({
    queryKey: ['notes-search', kw, limit, sort],
    enabled: kw.length > 0,
    initialPageParam: 0,
    staleTime: 30_000,
    // ★ 429 不重试：* 重试会再占一次额度，等于自己把限流放大一倍 ⚠
    retry: false,
    queryFn: async ({ pageParam }): Promise<NoteSearchPage> => {
      const offset = Number(pageParam) || 0
      const params = new URLSearchParams({
        q: kw,
        limit: String(limit),
        offset: String(offset),
      })
      // ★ 相关度 = 不传（* 用 Meilisearch 的默认排名）；最新 = 按时间倒序 ⚠
      if (sort !== 'relevance') params.set('sort', sort)

      const data = unwrap(
        await apiGet<{
          total: number
          items: NoteSearchItem[]
          expanded?: { query: string; terms: string[]; matched: number }
        }>(`/api/notes/search/?${params.toString()}`, 'spread'),
      )
      return {
        items: data.items || [],
        total: data.total || 0,
        expanded: data.expanded,
        offset,
      }
    },
    getNextPageParam: (last) =>
      last.items.length >= limit ? last.offset + limit : undefined,
  })
}


