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
 */
import type { ApiError, ApiResult, EnvelopeKind } from './types'

const TOKEN_KEY = 'api_token'

/** 401(unauthenticated)统一处理钩子:由 App 注册(清登录态 + 跳登录页) */
let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(fn: (() => void) | null) {
  unauthorizedHandler = fn
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch (e) {
    console.error('read token failed', e)
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch (e) {
    console.error('write token failed', e)
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
    setToken(null)
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
  const token = getToken()
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)

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
    const token = getToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

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
