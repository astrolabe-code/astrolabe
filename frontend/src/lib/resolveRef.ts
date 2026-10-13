/**
 * Astrolabe · 前端：**把分支 / tag 解析成 commit sha**（★ `B182` · 2026-10-13）
 *
 * ★★★ 所有者原话（逐字）：
 *
 * > 「**不对呀，这个过程应该发生在前端，不是用我服务器的IP地址查询的，
 * > 只有拉源码，才是我服务器做的吧？**」
 *
 * ## ★★ 为什么这件事必须放在前端
 *
 * ```
 * ★ 未认证的 GitHub API 限制是【每 IP 每小时 60 次】，★ 而解析 sha 要 2 次 ⚠
 * ★★ 由服务端做 ⇒ 每小时约 30 次拉取就撞限，★ 而且【所有用户一起被挡】⚠
 * ★★ 由前端做   ⇒ 每个用户花【自己的】配额 ⇒ ★ 互不影响 ✅
 * ```
 *
 * ## ★★ 可行性（★ 已实测，不是推演）
 *
 * | 平台 | 跨域头 | 结论 |
 * |---|---|---|
 * | `api.github.com` | `access-control-allow-origin: *` | ✅ 浏览器可直接调 |
 * | `gitee.com/api/v5` | `Access-Control-Allow-Origin: *` | ✅ 同上 |
 *
 * ## ⚠★ 服务端**不依赖**这里的结果
 *
 * ```
 * ★ 本模块失败 / 没跑到 ⇒ ★ 前端【不传 sha】⇒ ★ 服务端自己解析（兜底）✅
 * ★★ 也就是说：★ 这里省的是配额，★ ❌ 不是功能前提 ⚠
 * ```
 */

/** ★ 解析结论 —— ★ 字段与后端 `core/fetch.py::RefVerdict` 对齐 */
export interface RefVerdict {
  ok: boolean
  /** ★ 失败原因码（★ `repo_unavailable` / `private_repo` / `bad_ref` / `rate_limited`）*/
  reason_code: string
  /** ★ 给用户看的原因（⚠ 必须能读懂）*/
  message: string
  /** ★★ 解析出来的 commit sha —— ★ 基图的「身份证」之源 */
  sha: string
  /** ★ 仓库默认分支（★ 用户没指定时用它）*/
  default_branch: string
}

/** ★ 各平台的 API 根（⚠ 与后端 `core/fetch.py::repo_api_url()` 保持一致）*/
const API_ROOT: Record<string, string> = {
  github: 'https://api.github.com/repos',
  gitee: 'https://gitee.com/api/v5/repos',
}

/** ★ 单次请求超时（ms）—— ★ 国内访问 GitHub 常很慢，★ 别让用户干等 */
const TIMEOUT_MS = 12_000

/**
 * ★★ **把分支 / tag 解析成 commit sha**（★ 在浏览器里做）。
 *
 * @param provider  `github` | `gitee`
 * @param repoFull  `owner/repo`
 * @param ref       分支 / tag；★ 空 ⇒ 用仓库的默认分支
 */
export async function resolveRef(
  provider: string,
  repoFull: string,
  ref = '',
): Promise<RefVerdict> {
  const fail = (reason_code: string, message: string): RefVerdict => ({
    ok: false,
    reason_code,
    message,
    sha: '',
    default_branch: '',
  })

  const root = API_ROOT[(provider || '').toLowerCase()]
  if (!root) return fail('bad_provider', `不支持的托管平台：${provider}`)

  const full = (repoFull || '').trim().replace(/^\/+|\/+$/g, '')
  if (full.split('/').length !== 2 || full.split('/').some((s) => !s || s === '.' || s === '..')) {
    return fail('bad_repo', '仓库格式应为 owner/repo，请检查后重试。')
  }

  const headers = { Accept: 'application/json' }

  // ---- ① 仓库信息：★ 不存在 / 私有 ⇒ 未认证一律 404 ⇒ 直接拒 ----
  let info: any
  try {
    info = await getJson(`${root}/${full}`, headers)
  } catch (err) {
    // ⚠★★ 必须分清【这是谁的错】——
    //   · ★ 403 / 429 ⇒ **我们被限流了**（★ 用户的配额，❌ 不是仓库有问题）⚠
    //   · ★ 404 / 其它 ⇒ 仓库不存在或私有
    const status = (err as { status?: number }).status
    if (status === 403 || status === 429) {
      return fail(
        'rate_limited',
        '查询太频繁了，请过一会儿再试。★（GitHub 对未登录查询有每小时上限）',
      )
    }
    return fail(
      'repo_unavailable',
      '找不到这个仓库，或者它是私有仓库。★ 本站只接受公开仓库 —— 私有仓库不会被拉取。',
    )
  }

  if (!info || !info.full_name) {
    return fail('repo_unavailable', '查不到这个仓库的信息，请确认地址是否正确。')
  }

  if (info.private === true) {
    return fail(
      'private_repo',
      '这是私有仓库。★ 本站只接受公开仓库，私有仓库不会被拉取。',
    )
  }

  const defaultBranch: string = info.default_branch || ''
  // ★★ 用户没指定 ⇒ 用默认分支（★ 所有者原话：「没有指定，就选默认分支」）
  const want = (ref || '').trim() || defaultBranch || 'HEAD'

  // ---- ② 分支 / tag ⇒ commit sha ----
  let commit: any
  try {
    commit = await getJson(`${root}/${full}/commits/${encodeURIComponent(want)}`, headers)
  } catch (err) {
    const status = (err as { status?: number }).status
    if (status === 403 || status === 429) {
      return fail(
        'rate_limited',
        '查询太频繁了，请过一会儿再试。★（GitHub 对未登录查询有每小时上限）',
      )
    }
    return fail('bad_ref', `找不到分支 / tag：${want}。请确认名字写对了。`)
  }

  const sha = String((commit && commit.sha) || '').trim()
  if (!sha) {
    return fail('bad_ref', `解析不出 ${want} 对应的 commit，请换一个分支 / tag 再试。`)
  }

  return { ok: true, reason_code: 'ok', message: '', sha, default_branch: defaultBranch }
}

/** ★ 带超时的 GET JSON（★ 超时 / 网络错都抛，★ 由调用方翻译成用户文案）*/
async function getJson(url: string, headers: Record<string, string>): Promise<any> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  try {
    const resp = await fetch(url, { headers, signal: ctrl.signal })
    if (!resp.ok) {
      const err = new Error(`HTTP ${resp.status}`) as Error & { status?: number }
      err.status = resp.status
      throw err
    }
    return await resp.json()
  } finally {
    clearTimeout(timer)
  }
}
