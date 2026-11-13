import type { Api } from '../../shared/contract'

declare global {
  interface Window {
    api: {
      invoke(method: string, ...args: unknown[]): Promise<unknown>
    }
  }
}

/** 唯一的后端入口：方法名与参数由 shared/contract.ts 约束 */
export function invoke<K extends keyof Api>(
  method: K,
  ...args: Parameters<Api[K]>
): Promise<Awaited<ReturnType<Api[K]>>> {
  return window.api.invoke(method, ...args) as Promise<Awaited<ReturnType<Api[K]>>>
}
