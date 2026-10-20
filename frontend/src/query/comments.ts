import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import type {
  AnchorKind,
  Comment,
  CommentCreateResult,
  CommentKind,
  CommentListData,
} from '../api/types'

/**
 * ★ 评论数据层（`B201` / `B203`④ · 契约 §22.3）
 *
 * ## ⚠★ 五条必须理解的约定
 *
 * | # | 约定 | 前端后果 |
 * |---|---|---|
 * | ① | ★★ **只删不改**（`B201③`） | ❌ 没有 PATCH；编辑他人内容一律不提供（并列新增） |
 * | ② | ★★ `anchor_kind` **创建时定死** | 章评/段评建成后永不互换；不随失锚而变 |
 * | ③ | ★★ `quote` 后端快照 | 段评显示「那一刻的原文」；`orphaned=true` ⇒ 显示「原段落已变更」 |
 * | ④ | ★★ 楼中楼 B 站口径 | 默认只要顶层（带 `reply_count`）；`?parent=<id>` 拉回复（旧→新） |
 * | ⑤ | ★★ 删除是**软删 + 幂等** | 删过的再删照样 200；楼中楼不断链 |
 *
 * ⚠ 本模块**只做数据层**（F1）—— 章评/段评/楼中楼 UI 在 F3 消费这些钩子。
 */

export interface CommentsQuery {
  anchor_kind: AnchorKind
  /** 段评必填；章评不传 */
  block_id?: number
  /** 楼中楼：拉某条的回复 */
  parent?: number
  /** 失锚且被策略隐藏的段评也列出来（仅有权者有效） */
  include_hidden?: boolean
  /**
   * ★★ `F3` 新增：**要不要自动拉**（默认 true）⚠
   *   · · ★ 段评 / 楼中楼回复默认**折叠** ⇒* 没展开的就是 0 请求 ✅
   *   · · ★ 展开时由调用方 `refetch()`（* ⛔ 不用 `enabled: open` ——* 那会在
   *     关闭时也保留一份已取数据，* 没必要）✅
   */
  enabled?: boolean
  limit?: number
  offset?: number
}

/** GET /api/notes/<id>/comments/（① 型） */
export function useComments(noteId?: number | null, q: CommentsQuery = { anchor_kind: 'chapter' }) {
  const params = new URLSearchParams({ anchor_kind: q.anchor_kind })
  if (q.block_id != null) params.set('block_id', String(q.block_id))
  if (q.parent != null) params.set('parent', String(q.parent))
  if (q.include_hidden) params.set('include_hidden', '1')
  if (q.limit != null) params.set('limit', String(q.limit))
  if (q.offset != null) params.set('offset', String(q.offset))
  const key = ['comments', noteId, q.anchor_kind, q.block_id ?? null, q.parent ?? null, !!q.include_hidden]
  return useQuery({
    queryKey: key,
    // ⚠★ `enabled` 默认 true ——* 显式传 false 时**永不自动取**（* 展开后 refetch）✅
    enabled: !!noteId && q.enabled !== false,
    queryFn: async (): Promise<{ total: number; items: Comment[] }> => {
      const data = unwrap(
        await apiGet<CommentListData>(`/api/notes/${noteId!}/comments/?${params.toString()}`, 'data'),
      )
      return { total: data.total, items: data.items || [] }
    },
  })
}

export interface CreateCommentBody {
  body: string
  anchor_kind: AnchorKind
  /** 段评必填（且必须属于这篇笔记）；章评带了 ⇒ 400 */
  block_id?: number
  /**
   * ★★ `B214`：评论类型 —— `comment`（默认）/ `reply` / `mention` / `both` ⚠
   *   · · ★ 非 `comment` 时正文**必须带 @**（后端 400 `missing_mention`）✅
   *   · · ★★ 「回复谁」就在正文的 @ 里（* ⛔ 不再有 `parent_id`）⚠
   */
  kind?: CommentKind
}

/** POST /api/notes/<id>/comments/（① 型）⇒ {comment, note_comment_count, block_comment_count} */
export function useCreateComment(noteId?: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: CreateCommentBody): Promise<CommentCreateResult> =>
      unwrap(await apiPost<CommentCreateResult>(`/api/notes/${noteId!}/comments/`, body, 'data')),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['comments', noteId] })
      void qc.invalidateQueries({ queryKey: ['note', noteId] })
    },
  })
}

/**
 * DELETE /api/comments/<id>/（① 型）—— ★★ 软删、**幂等**
 *
 * ⚠ 删过的再删照样 200（`deleted:true`）✅
 * ⚠ 删除按钮仅对**作者本人 / 项目 owner / 协作者 / 管理员**渲染（契约 §22.3）⚠
 */
export function useDeleteComment(noteId?: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (commentId: number): Promise<{ deleted: boolean }> =>
      unwrap(await apiDelete<{ deleted: boolean }>(`/api/comments/${commentId}/`, undefined, 'data')),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['comments', noteId] })
      void qc.invalidateQueries({ queryKey: ['note', noteId] })
    },
  })
}

/**
 * ★★ 评论赞（* `POST /api/comments/<id>/like/`）—— 一次 +1
 *
 * ★★ **开关语义**：* 没赞过 ⇒ 点赞（+1）；* 赞过 ⇒ 取消（−1）
 *   回包 `{liked, like_count}`，前端乐观切换、失败回滚 ⚠
 */
export function useCommentLike() {
  return useMutation({
    mutationFn: async (
      commentId: number,
    ): Promise<{ liked: boolean; like_count: number }> =>
      unwrap(
        await apiPost<{ liked: boolean; like_count: number }>(
          `/api/comments/${commentId}/like/`,
          {},
          'data',
        ),
      ),
  })
}
