/**
 * 统一请求层(D31:envelope 归一改为「按端点显式声明」,不做结构猜测)
 *
 * 后端现有 4 种响应形态(见 docs/frontend-contract.md §11):
 *   data         → {ok:true, data:{...}}                        (edit / notes / 新 authapi)
 *   spread       → {ok:true, ...展开字段}                        (summary/search/analysis/...)
 *   legacy-error → {error:"文案"} + HTTP status                  (大量只读接口)
 *   coded-error  → {ok:false, error:{code,message}} + status     (edit.py CAS)
 *
 * 上传(D15)独立实现:fetch 无上传进度,改用 XMLHttpRequest。
 *
 * ★★★ 认证(2026-10-25 · B245)：**改用 Django session，⛔ 不再用 Bearer 令牌**
 *   · · 所有者原话：「我的天呐，你把django设计好的维持登陆状态和身份识别的令牌系统给了后台了吗？」
 *   · · 登录后 `sessionid` 由浏览器自动带(HttpOnly，JS 读不到)⇒ **不能也不会**放 localStorage
 *   · · 代价：cookie 认证必须带 CSRF 头 ⇒ 所有非 GET 带 `X-CSRFToken`(B247②)⚠
 */
import type { ApiError, ApiResult, EnvelopeKind } from './types'

/** 401(unauthenticated)统一处理钩子:由 App 注册(清登录态 + 跳登录页) */

/**
 * ★ 登出后的本地清理(B245 后 session 由服务端管)
 *
 * ⚠ localStorage 里**不再存任何凭证** —— 只需清掉遗留的旧键
 *   (老版本曾把 `api_token` 放在这里,升级后要扫掉,否则用户永远登不出)⚠
 */

function normalize<T>(status: number, body: any, kind: EnvelopeKind): ApiResult<T> {
  // ④ 编码错误(优先判失败,避免字段名恰为 ok 时误判)
  if (body && typeof body === 'object' && body.ok === false) {
    const e = body.error || {}
    return {
      ok: false,
      error: { code: e.code || 'error', message: e.message || '请求失败', status, data: body.data },
    }
  }
  // ①/② 成功
  if (body && typeof body === 'object' && body.ok === true) {
    if (kind === 'spread' || !('data' in body)) {
      const { ok, ...rest } = body
      return { ok: true, data: rest as T }
    }
    return { ok: true, data: body.data as T }
  }
  // ③ 旧式错误文案
  if (body && typeof body === 'object' && typeof body.error === 'string') {
    return { ok: false, error: { message: body.error, status } }
  }
  if (!status || status >= 400) {
    return { ok: false, error: { message: `请求失败(${status || 0})`, status } }
  }
  // 少数接口直接返回裸对象
  return { ok: true, data: body as T }
}

export async function api<T = any>(
  path: string,
  kind: EnvelopeKind = 'spread',
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  const headers = new Headers(init.headers || {})
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  let res: Response
  try {
    res = await fetch(path, { ...init, headers })
  } catch (e) {
    console.error('network error', e)
    return { ok: false, error: { message: '网络异常,请稍后重试', status: 0 } }
  }

  let body: any = null
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) {
    body = await res.json().catch((e) => {
      console.error('json parse failed', e)
      return null
    })
  } else if (res.status !== 204) {
    body = await res.text().catch(() => null)
  }

  return normalize<T>(res.status, body, kind)
}

export function apiGet<T = any>(path: string, kind: EnvelopeKind = 'spread') {
  return api<T>(path, kind, { method: 'GET' })
}

export function apiPost<T = any>(path: string, body?: unknown, kind: EnvelopeKind = 'data') {
  return api<T>(path, kind, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
}

export function apiPut<T = any>(path: string, body?: unknown, kind: EnvelopeKind = 'spread') {
  return api<T>(path, kind, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) })
}

/**
 * ★ PATCH（`B164` 新增）
 *
 * ⚠★ 为什么需要它：新后端 `projects.detail` 的写方法是
 * `@require_http_methods(["GET", "PATCH", "DELETE"])` —— ★★ **是 PATCH，❌ 不是 PUT**。
 * ★ 旧前端只有 `apiPut`（旧站用 PUT）⇒ ★ 照搬会得到 **405**。
 */
export function apiPatch<T = any>(path: string, body?: unknown, kind: EnvelopeKind = 'spread') {
  return api<T>(path, kind, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) })
}

export function apiDelete<T = any>(path: string, body?: unknown, kind: EnvelopeKind = 'spread') {
  return api<T>(path, kind, { method: 'DELETE', body: body === undefined ? undefined : JSON.stringify(body) })
}

export type { ApiError, ApiResult, EnvelopeKind }
