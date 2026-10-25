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

/** ★ CSRF Cookie 名 —— 与后端 `settings.CSRF_COOKIE_NAME` 一致(必须是**非** HttpOnly)⚠ */
const CSRF_COOKIE = 'csrftoken'

/** 401(unauthenticated)统一处理钩子:由 App 注册(清登录态 + 跳登录页) */
let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(fn: (() => void) | null) {
  unauthorizedHandler = fn
}

/**
 * ★ 读 CSRF Token(供非 GET 请求带 `X-CSRFToken` 头,B247②)⚠
 *
 * ⚠ 它保护的就是 sessionid —— ⛔ **不是**登录凭证本身,
 *   泄露它没有意义(攻击者仍然拿不到你的 HttpOnly sessionid)✅
 */
export function getCsrfToken(): string | null {
  try {
    const m = document.cookie.match(new RegExp(`(?:^|;\\s*)${CSRF_COOKIE}=([^;]*)`))
    return m ? decodeURIComponent(m[1]) : null
  } catch (e) {
    console.error('read csrf token failed', e)
    return null
  }
}

/**
 * ★ 登出后的本地清理(B245 后 session 由服务端管)
 *
 * ⚠ localStorage 里**不再存任何凭证** —— 只需清掉遗留的旧键
 *   (老版本曾把 `api_token` 放在这里,升级后要扫掉,否则用户永远登不出)⚠
 */
export function clearLegacyAuth() {
  try {
    localStorage.removeItem('api_token')
  } catch (e) {
    console.error('clear legacy auth failed', e)
  }
}

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

/** 统一后置处理:401 清 token 并交给 App 跳登录(只触发一次由 handler 保证) */
function afterResult<T>(result: ApiResult<T>): ApiResult<T> {
  if (!result.ok && result.error.status === 401 && result.error.code === 'unauthenticated') {
    // ★ B245：session 失效由服务端管,前端只需跳登录页(⛔ 不清 Cookie,那归 Django)⚠
    try {
      unauthorizedHandler?.()
    } catch (e) {
      console.error('unauthorized handler failed', e)
    }
  }
  return result
}

export async function api<T = any>(
  path: string,
  kind: EnvelopeKind = 'spread',
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  const headers = new Headers(init.headers || {})
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  // ★★ B247②：非 GET 一律带 CSRF 头(⛔ GET/HEAD 不需要,带了反而多余)⚠
  const method = (init.method || 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD' && !headers.has('X-CSRFToken')) {
    const csrf = getCsrfToken()
    if (csrf) headers.set('X-CSRFToken', csrf)
  }

  let res: Response
  try {
    res = await fetch(path, { credentials: 'same-origin', ...init, headers })
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

  return afterResult(normalize<T>(res.status, body, kind))
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

/* ---------------------------------------------------------------- 上传 */

export interface UploadOptions {
  /** 文件字段名,后端 upload 取 request.FILES */
  field?: string
  /** 额外表单字段(如 max_mb) */
  extra?: Record<string, string>
  onProgress?: (pct: number) => void
}

export interface UploadHandle {
  promise: Promise<ApiResult<any>>
  abort: () => void
}

/**
 * zip 上传(D15):XHR + FormData,**不手设 Content-Type**(浏览器生成 boundary)。
 * 后端 `upload/` 立即返回({ok,key,parsing}),解析进度另走 `/progress/` 轮询。
 */
export function upload(path: string, file: File, opts: UploadOptions = {}): UploadHandle {
  const xhr = new XMLHttpRequest()

  const promise = new Promise<ApiResult<any>>((resolve) => {
    const form = new FormData()
    form.append(opts.field || 'file', file)
    Object.entries(opts.extra || {}).forEach(([k, v]) => form.append(k, v))

    xhr.open('POST', path, true)
    xhr.setRequestHeader('Accept', 'application/json')
    // ★ B245：上传走 session；B247②：带 CSRF 头 ⚠
    xhr.withCredentials = true
    const csrf = getCsrfToken()
    if (csrf) xhr.setRequestHeader('X-CSRFToken', csrf)

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && opts.onProgress) {
        opts.onProgress(Math.round((e.loaded / e.total) * 100))
      }
    }
    xhr.onerror = () => {
      console.error('upload network error', path)
      resolve({ ok: false, error: { message: '网络异常,上传失败', status: 0 } })
    }
    xhr.onabort = () => {
      resolve({ ok: false, error: { message: '上传已取消', status: 0 } })
    }
    xhr.onload = () => {
      const ct = xhr.getResponseHeader('content-type') || ''
      let body: any = null
      if (ct.includes('application/json')) {
        try {
          body = JSON.parse(xhr.responseText)
        } catch (e) {
          console.error('upload json parse failed', e)
          body = null
        }
      }
      resolve(afterResult(normalize(xhr.status, body, 'spread')))
    }

    xhr.send(form)
  })

  return { promise, abort: () => xhr.abort() }
}

export type { ApiError, ApiResult, EnvelopeKind }
