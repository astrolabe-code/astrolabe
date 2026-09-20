import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import type { InviteInfo } from '../api/types'

/**
 * ★ 邀请数据层（`B171` · ★ 管理页用）
 *
 * ## ★★ 权限：**这三个都要求 `is_staff`**（后端 `@staff_only`）
 *
 * ⚠★★ **一句必须记住的话**：★ **前端权限只决定"显不显示按钮"** ——
 * ★ **真正的判定在后端** ⚠
 * ⇒ ★★ 就算有人在控制台里把 `AdminInvites` 强行渲染出来，
 *   ★ 他也**只会拿到 403**（★ 这不是"我们运气好"，★ 而是**本来就这么设计的**）✅
 *
 * ## ★ 端点
 * | 方法 | 路径 | 说明 |
 * |---|---|---|
 * | `GET` | `/api/invites/` | ★ 列表（⚠ `limit ≤ 200`）|
 * | `POST` | `/api/invites/` | ★ 生成（`max_uses` 1–200 · `valid_days` 1–3650 · `note`）|
 * | `POST` | `/api/invites/<token>/revoke/` | ★ 撤销 |
 */

/**
 * ★ 邀请列表 —— ⚠★ **`enabled` 必须由调用方给**（★ 通常传 `me.is_staff`）。
 *
 * ★ 未登录 / 非管理员时调它**必然 403** —— ★ 而那次失败**没有意义**（★ 只是白打一发）⚠
 */
export function useInvites(enabled: boolean) {
  return useQuery({
    queryKey: ['invites'],
    enabled,
    queryFn: async (): Promise<InviteInfo[]> => {
      const d = unwrap(await apiGet<{ invites: InviteInfo[] }>('/api/invites/', 'data'))
      return d.invites || []
    },
  })
}

export interface CreateInviteInput {
  /** ★ 最多可用几次（★ 后端限 1–200，★ 默认 1） */
  max_uses?: number
  /** ★ 有效天数（★ 后端限 1–3650，★ 默认 7；⚠ **填 0 或负数会被拒** —— `U4.7` 规则 2） */
  valid_days?: number
  /** ★ 备注（★ 上限 200 字 —— ★ 记"给谁"很方便） */
  note?: string
}

/**
 * ★ 生成一个邀请 —— ★ 成功返回**新邀请的完整信息**（★ 含 `token`，★ 好让页面立刻显示分享链接）✅
 */
export function useCreateInvite() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: CreateInviteInput): Promise<InviteInfo> =>
      unwrap(
        await apiPost<InviteInfo>(
          '/api/invites/',
          {
            max_uses: input.max_uses ?? 1,
            valid_days: input.valid_days ?? 7,
            note: (input.note || '').trim(),
          },
          'data',
        ),
      ),
    onSuccess: () => {
      // ★ 重新拉列表（★ 别自己往前端数组里塞 —— ★ 后端的排序/状态才是权威）
      qc.invalidateQueries({ queryKey: ['invites'] })
    },
  })
}

/**
 * ★ 撤销一个邀请（★ 还没用完也能收回 —— ★ 比如发现它被转发了）✅
 *
 * ⚠★ 撤销**不改 `used_count`** —— ★ 它只是把凭证作废 ⚠（★ 已经用它注册过的人不受影响）
 */
export function useRevokeInvite() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (token: string): Promise<{ revoked: boolean; token: string }> =>
      unwrap(
        await apiPost<{ revoked: boolean; token: string }>(
          `/api/invites/${encodeURIComponent(token)}/revoke/`,
          undefined,
          'data',
        ),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['invites'] })
    },
  })
}
