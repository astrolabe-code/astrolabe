import { create } from 'zustand'
import { getToken, setToken as persistToken } from '../api/client'

export interface AuthUser {
  id: number
  username: string
  is_staff: boolean
  avatar: string | null
}

interface AuthState {
  token: string | null
  user: AuthUser | null
  exp: string | null
  setAuth: (p: { token: string; user: AuthUser; exp: string | null }) => void
  clear: () => void
}

/** SPA 登录态(D8):token 存 localStorage,user/exp 存内存(刷新后由 /api/auth/me 复原) */
export const useAuthStore = create<AuthState>((set) => ({
  token: getToken(),
  user: null,
  exp: null,
  setAuth: ({ token, user, exp }) => {
    persistToken(token)
    set({ token, user, exp })
  },
  clear: () => {
    persistToken(null)
    set({ token: null, user: null, exp: null })
  },
}))
