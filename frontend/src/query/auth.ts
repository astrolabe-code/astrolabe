import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import type { AuthProvidersData, AuthTokenData } from '../api/types'
import { useAuthStore } from '../store/authStore'

/**
 * ★ 认证数据层（`B170` · ★ 用户名 + 密码）
 *
 * ## ★ 后端端点
 * | 方法 | 路径 | 本文件里 |
 * |---|---|---|
 * | `GET` | `/api/auth/providers/` | ★ `useAuthProviders`（★ 匿名可调） |
 * | `POST` | `/api/auth/login/` | ★ `useLogin` |
 * | `POST` | `/api/auth/register/` | ★ `useRegister` |
 * | `POST` | `/api/auth/logout/` | ★ `useLogout` |
 * | `GET` | `/api/auth/me/` | ★ 已由 `hooks/useMe.ts` 承担（❌ 不重复） |
 *
 * ## ⚠★★ 为什么没有 `useStartOAuth`
 * ★ `B167` 定过：★ **OAuth 不承担登录** —— ★ 它的唯一用途是
 * "**拉代码时验证仓库归属**"（★ 在 `ProjectCard` 的「拉取代码」里走，★ 见 `useStartFetch`）✅
 *
 * ## ★★ 登录 / 注册成功后要做的事（★ 三件，顺序有讲究）
 * ① ★ **写 token 进 `authStore`**（★ 它会 `persist` 到 `localStorage`）
 * ② ★★ **让 `useMe` 重拉身份** —— ★ `token` 变了 ⇒ queryKey 变 ⇒ **自动重拉** ✅
 * ③ ★ 其余缓存**不用动**（★ 它们看的是 `useMe` 的结果）
 */

/* ============================================================================
 * 注册门禁（★ 登录页 / 注册页都要看它）
 * ========================================================================== */

/**
 * ★ 有哪些登录方式 + **注册门禁状态**（★ 匿名可调）
 *
 * ⚠★★ **前端要看的是 `registration.registration_open`**（★ 注册入口可见性），
 * ★ ❌ **不是 `allowed`** —— ★ 两者在"隐藏入口"时会【不同】：
 * ★ `registration_open=false` 时 `allowed` **仍是 `true`**（★ 因为持邀请码者还能注册）⚠
 * ⇒ ★ 用错字段的后果：★ **注册按钮会显示出来**，⚠ 而点进去又要求邀请码（★ 体验很怪）⚠
 */
export function useAuthProviders() {
  return useQuery({
    queryKey: ['auth', 'providers'],
    // ★ 门禁是**运营者手动改的开关**，变得很慢 ⇒ ★ 没必要每次进页面都问一遍
    staleTime: 300_000,
    queryFn: async (): Promise<AuthProvidersData> =>
      unwrap(await apiGet<AuthProvidersData>('/api/auth/providers/', 'data')),
  })
}

/* ============================================================================
 * 登录 / 注册
 * ========================================================================== */

/** ★★ 把登录结果落地（★ 三件事见文件头）*/
function applyAuth(data: AuthTokenData) {
  useAuthStore.getState().setAuth({ token: data.token, user: data.user, exp: data.exp })
}

export interface LoginInput {
  username: string
  password: string
  /** ★ 「记住我」—— ★ 契约 §12：7 天 / 30 天两档 */
  remember?: boolean
}

/**
 * ★ 登录 —— `POST /api/auth/login/`
 *
 * ⚠★ **后端刻意不区分「用户名不存在」与「密码错误」**（★ 防账号枚举）——
 * ★ 所以前端**也别说**"该用户不存在"这类话，★ **直接展示后端文案**即可 ✅
 */
export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: LoginInput): Promise<AuthTokenData> =>
      unwrap(
        await apiPost<AuthTokenData>(
          '/api/auth/login/',
          {
            username: input.username.trim(),
            password: input.password,
            remember: input.remember !== false,
          },
          'data',
        ),
      ),
    onSuccess: (data) => {
      applyAuth(data)
      qc.invalidateQueries({ queryKey: ['me'] })
    },
  })
}

export interface RegisterInput {
  username: string
  password: string
  /** ★ 邀请码（★ `registration.invite_required` 时才需要）*/
  invite_token?: string
}

/**
 * ★ 注册 —— `POST /api/auth/register/`
 *
 * ★ 后端会：★ 校验用户名 / 密码强度 ⇒ ★ 核销邀请码（★ 与建号**同一事务**）⇒ ★ 直接签发 token
 * ⇒ ★★ **注册成功即已登录**（★ 不用再走一次登录）✅
 *
 * ⚠★ 与登录**不同**：★ 注册**必须说清失败原因**（★ 重名 / 码无效 / 密码太弱）——
 * ★ 因为**注册躲不掉**（★ 不说清，用户只会反复试同一个名字）⚠
 */
export function useRegister() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: RegisterInput): Promise<AuthTokenData> =>
      unwrap(
        await apiPost<AuthTokenData>(
          '/api/auth/register/',
          {
            username: input.username.trim(),
            password: input.password,
            invite_token: (input.invite_token || '').trim(),
          },
          'data',
        ),
      ),
    onSuccess: (data) => {
      applyAuth(data)
      qc.invalidateQueries({ queryKey: ['me'] })
    },
  })
}

/* ============================================================================
 * 登出
 * ========================================================================== */

/**
 * ★ 登出 —— ★ **只撤销当前这一个**令牌。
 *
 * ⚠★ 后端是**幂等**的（★ 重复登出不算错）⇒ ★ 所以**照常清本地**：
 * ★ 判断"要不要清本地 token"的依据是**用户的意图**，❌ 不是服务端的返回值 ⚠
 */
export function useLogout() {
  const qc = useQueryClient()
  const clear = useAuthStore((s) => s.clear)
  return useMutation({
    mutationFn: async (): Promise<{ revoked: boolean }> =>
      unwrap(await apiPost<{ revoked: boolean }>('/api/auth/logout/', undefined, 'data')),
    // ⚠★ `onSettled`（❌ 不是 `onSuccess`）—— ★ 哪怕请求失败，★ 本地也要清干净：
    //   ★ 否则用户会卡在"点了退出但还是登录状态"这种别扭的状态里 ⚠
    onSettled: () => {
      clear()
      qc.invalidateQueries({ queryKey: ['me'] })
    },
  })
}
