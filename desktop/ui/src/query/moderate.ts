import { useMutation, useQuery } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import type { ModerateAction, ModerateResult, ModeratedList } from '../api/types'

/**
 * ★ 管理处置数据层（`B208` · 契约 §22.6）—— ★★ **管理员唯一的权力**
 *
 * ## ★★★ 所有者原话（逐字）
 *
 * > 「**网站管理员有权限修改图和笔记，不行。管理员只有隐藏下架项目和笔记的权限，
 * > 而且一旦被管理员隐藏下架，非管理员不可恢复。**」
 *
 * ## ⚠★ 三个动作的语义（前端文案必须照这个说）
 *
 * | 动作 | 语义 | 文案口径 |
 * |---|---|---|
 * | `hide` | ★★ **隐藏**：只有作者/owner 可见（协作者也不可、直链也不可） | 「先藏着，核查中」 |
 * | `take_down` | ★★ **下架**：**物理删除**数据，**没有恢复机制** | 「彻底删除、不可恢复」 |
 * | `restore` | ★★ **恢复**：仅 `hidden → active` | 「解除隐藏」 |
 *
 * ⚠★ `reason` 对 `hide` / `take_down` **必填**（400 `missing_reason`）——
 *   作者来问「为什么」必须答得出（`B196`）；`restore` 可空。
 *
 * ⚠ 本模块**只做数据层**（F1）—— 管理处置页 UI 在 F4 消费这些钩子；
 *   入口仅对 `is_staff` 渲染，但⚠ **真正的拦截在后端**（整条 `@staff_only`）✅
 */

/** POST /api/admin/projects/<ref>/moderate/（① 型） */
export function useModerateProject(projectRef?: string | null) {
  return useMutation({
    mutationFn: async (body: { action: ModerateAction; reason: string }): Promise<ModerateResult> =>
      unwrap(
        await apiPost<ModerateResult>(
          `/api/admin/projects/${encodeURIComponent(projectRef!)}/moderate/`,
          body,
          'data',
        ),
      ),
  })
}

/** POST /api/admin/notes/<id>/moderate/（① 型） */
export function useModerateNote(noteId?: number | null) {
  return useMutation({
    mutationFn: async (body: { action: ModerateAction; reason: string }): Promise<ModerateResult> =>
      unwrap(
        await apiPost<ModerateResult>(`/api/admin/notes/${noteId!}/moderate/`, body, 'data'),
      ),
  })
}

/**
 * GET /api/admin/moderated/（① 型）—— ★★ **已处置列表**（`B215`）
 *
 * ⚠★ 为什么需要它：隐藏的项目/笔记对 staff 也 404（`B208`：管理员无额外读权限）
 *   ⇒ 没有这个列表，「恢复」在 UI 里够不着 ✅
 * ⚠★ `take_down` 的项不在列表（物理删除，行都没了）✅
 */
export function useModeratedItems() {
  return useQuery({
    queryKey: ['moderated-items'],
    queryFn: async (): Promise<ModeratedList> =>
      unwrap(await apiGet<ModeratedList>('/api/admin/moderated/', 'data')),
  })
}
