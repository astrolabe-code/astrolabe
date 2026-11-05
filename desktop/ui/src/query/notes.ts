import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import { personalApi } from '../api/personal'
import type {
  Note,
  NoteBlock,
  NoteDetailData,
  NoteKind,
  NoteListData,
} from '../api/types'

/**
 * ★ 笔记数据层（`B187` / `B188` / `B201` / `B210` · 契约 §22.2）
 *
 * ## ⚠★ 三条必须理解的约定
 *
 * | # | 约定 | 前端后果 |
 * |---|---|---|
 * | ① | ★★ `blocks` 由**后端**重算并返回 | ❌ 前端不自己切段落；PATCH 改了 `body` ⇒ **必须**用响应的 `blocks` 刷新段评锚点 |
 * | ② | ★★ 个人版的删除是**直接删**（边车无软删/回收站） | ⚠ 删除不可恢复，UI 文案不要暗示能撤销 |
 * | ③ | ★★ 被隐藏（`state=hidden`）/ 软删的笔记 | 对非作者**不可见**（列表直接没有），详情 404 |
 *
 * ⚠ 本模块**只做数据层**：编辑器 / 卡片 / 阅读页消费这些钩子。
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
      return personalApi.notes(projectRef!, { kind: kind || undefined })
    },
  })
}

/** GET /api/notes/<id>/（② 型）⇒ {note, blocks} */
export function useNote(noteId?: string | null) {
  return useQuery({
    queryKey: ['note', noteId],
    enabled: !!noteId,
    queryFn: async (): Promise<NoteDetailData> =>
      personalApi.note(noteId!) as unknown as Promise<NoteDetailData>,
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
      personalApi.createNote(projectRef!, body) as unknown as Promise<NoteDetailData>,
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
export function useUpdateNote(noteId?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: UpdateNoteBody): Promise<NoteDetailData> =>
      personalApi.updateNote(noteId!, body) as unknown as Promise<NoteDetailData>,
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
      personalApi.deleteNote(noteId).then(() => ({ deleted: true })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['notes'] })
      void qc.invalidateQueries({ queryKey: ['deleted-notes'] })
    },
  })
}

export type { Note, NoteBlock }
