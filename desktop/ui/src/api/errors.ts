/**
 * 统一错误类型与结果解包(D31)。
 *
 * client.ts 把 4 种 envelope 归一为 `ApiResult`;React Query 需要「失败即抛」,
 * 所以这里提供 `unwrap()` 统一转换,页面 hook 只处理数据与异常两种分支。
 */
import type { ApiError, ApiResult } from './types'

export class ApiRequestError extends Error {
  code?: string
  status: number
  data?: any

  constructor(e: ApiError) {
    super(e.message || '请求失败')
    this.name = 'ApiRequestError'
    this.code = e.code
    this.status = e.status
    this.data = e.data
  }
}

/** 成功取 data,失败抛 ApiRequestError */
export function unwrap<T>(r: ApiResult<T>): T {
  if (r.ok) return r.data
  throw new ApiRequestError(r.error)
}

/** 从任意异常里取可展示文案(后端文案优先,不做二次改写) */
export function errorMessage(e: unknown, fallback = '请求失败,请稍后重试'): string {
  if (e instanceof ApiRequestError) return e.message || fallback
  if (e instanceof Error) return e.message || fallback
  return fallback
}

/** 冲突/门禁类错误码(§1 关键错误码)——用于页面差异化提示 */
export const BUSY_CODES = ['project_busy', 'graph_not_ready', 'stale_rev', 'too_many_changes']

export function isBusyError(e: unknown): boolean {
  return e instanceof ApiRequestError && BUSY_CODES.includes(e.code || '')
}
