import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '../store/authStore'
import { apiGet } from '../api/client'

export interface Me {
  authenticated: boolean
  username?: string
  is_staff?: boolean
  is_superuser?: boolean
  is_coadmin?: boolean
  avatar?: string | null
}

/**
 * ★ 当前身份（B163 精简）
 *
 * ## ⚠★ 与原版的差别
 *
 * ★ 原版有**两条路**：★ 有 token 走 `/api/auth/me/`，
 *   ⚠ 无 token 时**回退旧站 session** 的 `/api/whoami/` ——
 *   ★★ 那是给「迁移期新旧并存」用的。
 *
 * ★★★ **本项目没有旧站，且新后端【没有 `whoami/`】**
 *   ⇒ ★ 回退分支**已删除** ✅（★ 否则无 token 时必然多打一次 404）
 *
 * ★ 未登录就直接返回 `{authenticated: false}` —— ★ 一次请求都不发 ✅
 */
export function useMe() {
  // ★ B245：登录态在 HttpOnly sessionid 里 ⇒ **每次都问后端**（⛔ 不能再凭本地字段跳过）
  //   · · 代价：多一次 GET；收益：登出 / 禁用 / 过期都能正确反映 ⚠
  return useQuery({
    queryKey: ['me'],
    staleTime: 60_000,
    queryFn: async (): Promise<Me> => {
      const r = await apiGet<{ user: Record<string, unknown> }>('/api/auth/me/', 'data')
      if (r.ok) {
        return { authenticated: true, ...(r.data.user || {}) }
      }
      // ★ 401 ⇒ 会话没了（过期 / 已登出 / 被禁用）⚠
      if (r.error.status === 401) return { authenticated: false }
      // ⚠ 其它错误（网络 / 5xx）也按未登录处理 —— ★ 不给调用方一个"薛定谔的登录态"
      return { authenticated: false }
    },
  })
}
