import { create } from 'zustand'
import { clearLegacyAuth } from '../api/client'

export interface AuthUser {
  id: number
  username: string
  is_staff: boolean
  avatar: string | null
}

interface AuthState {
  /** ★ B245 后恒为 null —— 登录态由 HttpOnly sessionid Cookie 承载,⛔ 前端无凭证可存 ⚠ */
  token: string | null
  user: AuthUser | null
  exp: string | null
  setAuth: (p: { user: AuthUser; exp?: string | null }) => void
  clear: () => void
}

/**
 * SPA 登录态(D8 · B245 改写)
 *
 * ```
旧:token 存 localStorage,刷新后由 /api/auth/me 复原
新:sessionid 是 HttpOnly Cookie(浏览器自动带)⇒ 这里只存 user/exp 供 UI 显示
```

 * ⚠ 保留 `token` 字段是为了**不破坏现有调用点**,但它恒为 null ⚠
 */
export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  exp: null,
  setAuth: ({ user, exp }) => {
    // ★ 扫掉旧版本遗留的 localStorage 凭证(否则升级后用户永远登不出)⚠
    clearLegacyAuth()
    set({ token: null, user, exp: exp ?? null })
  },
  clear: () => {
    clearLegacyAuth()
    set({ token: null, user: null, exp: null })
  },
}))
