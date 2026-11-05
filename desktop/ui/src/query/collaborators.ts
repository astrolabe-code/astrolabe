import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import type {
  CollaboratorAddResult,
  CollaboratorList,
  CollaboratorRemoveResult,
} from '../api/types'

/**
 * ★ 协作者数据层（`B202` / `B206` / `B207` · 契约 §22.5）
 *
 * ## ⚠★ 五条必须理解的约定
 *
 * | # | 约定 | 前端后果 |
 * |---|---|---|
 * | ① | ★★ **不发链接、不要 token** | 管理页 = 一个用户名输入框 + 确认按钮（`D84`）；⛔ 不做邀请链接/待接受状态 |
 * | ② | ★★ 幂等 | 已是对员 ⇒ 200 `already:true`（⛔ 不是 409）⇒ 可直接当成功提示 |
 * | ③ | ★★ 错误要可读 | 用户名不存在 ⇒ 404 `user_not_found`「没有这个用户」；输 owner 自己 ⇒ 400 `owner_not_allowed` |
 * | ④ | ★★ 谁能管 | 加人/移除 = owner/管理员；看名单 = owner/协作者/管理员（齐平） |
 * | ⑤ | ★★ 协作者权到哪 | 除删项目外与 owner 同权（`B207`）；⛔ 不能删项目、不能加/移协作者 |
 *
 * ⚠ 本模块**只做数据层**（F1）—— 管理页 UI 在 F4 消费这些钩子。
 */

/** GET /api/projects/<ref>/collaborators/（① 型） */
export function useCollaborators(projectRef?: string | null) {
  return useQuery({
    queryKey: ['collaborators', projectRef],
    enabled: !!projectRef,
    queryFn: async (): Promise<CollaboratorList> =>
      unwrap(
        await apiGet<CollaboratorList>(
          `/api/projects/${encodeURIComponent(projectRef!)}/collaborators/`,
          'data',
        ),
      ),
  })
}

/**
 * POST /api/projects/<ref>/collaborators/（① 型）—— ★★ **按用户名直接加**
 *
 * ⚠ `username` 不存在 ⇒ 404 `user_not_found`；输 owner 自己 ⇒ 400 `owner_not_allowed`；
 *   空用户名 ⇒ 400 `missing_username`；非 owner/管理员 ⇒ 403。
 */
export function useAddCollaborator(projectRef?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (username: string): Promise<CollaboratorAddResult> =>
      unwrap(
        await apiPost<CollaboratorAddResult>(
          `/api/projects/${encodeURIComponent(projectRef!)}/collaborators/`,
          { username },
          'data',
        ),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['collaborators', projectRef] })
    },
  })
}

/**
 * DELETE /api/projects/<ref>/collaborators/<username>/（① 型）—— ★★ 移除
 *
 * ⚠ 幂等：移一个不是成员的用户 ⇒ 200 `removed:false` ✅
 * ⚠ 被移除者已建的笔记/评论**全留着**（`B202③`）—— 没有「冻结」这个动作 ✅
 */
export function useRemoveCollaborator(projectRef?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (username: string): Promise<CollaboratorRemoveResult> =>
      unwrap(
        await apiDelete<CollaboratorRemoveResult>(
          `/api/projects/${encodeURIComponent(projectRef!)}/collaborators/${encodeURIComponent(username)}/`,
          undefined,
          'data',
        ),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['collaborators', projectRef] })
    },
  })
}
