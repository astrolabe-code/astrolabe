/**
 * ★★★ **前台可读的站点配置**（`D120` · 2026-10-27）⚠
 *
 * ## 为什么要有这一层
 *
 * 站点参数以前只活在 Python 里（`appsettings.get()`），前端一个都拿不到
 * ⇒ 任何「后台可调」的界面阈值都没法实现 ⚠
 *
 * 现在后端开了 `GET /api/site-config/`（**白名单**，见 `app/views/site_config.py`），
 * 这里只是把它包成 react-query ✅
 *
 * ## ⚠ 缓存口径
 *
 * ```\n * staleTime 5 分钟  ⇒ 后台改完参数，最迟 5 分钟前台生效（⛔ 不是立即）\n * ```\n *
 * ⚠ 这是**刻意**的：参数是低频调整项，不值得每次打开都请求一次 ⚠
 */
import { useQuery } from '@tanstack/react-query'

import { apiGet } from '../api/client'
import { unwrap } from '../api/errors'

export interface SiteConfig {
  /** ★ 停留多少秒才记「上次看到的位置」；**0 = 关闭「继续上次」** ⚠ */
  resumeDwellSeconds: number
}

/** ★ 兜底值 —— 和后端 `ui.resume_dwell_seconds` 的 default 保持一致 ⚠ */
const FALLBACK: SiteConfig = { resumeDwellSeconds: 20 }

export function useSiteConfig() {
  return useQuery({
    queryKey: ['site-config'],
    queryFn: async (): Promise<SiteConfig> => {
      // ⚠★ `apiGet` 返回的是 `ApiResult`（`{ok, data}`）—— **必须 `unwrap`** ⚠
      //   ⛔ 少了这一步，`{...FALLBACK, ...result}` 里永远没有 `resumeDwellSeconds`
      //      ⇒ 一直吃兜底的 20 秒，后台怎么改都不生效（踩过）
      const d = unwrap(await apiGet<Partial<SiteConfig>>('/api/site-config/', 'spread'))
      return { ...FALLBACK, ...d }
    },
    // ★ 5 分钟不重取；窗口聚焦也不重取（参数不是实时数据）⚠
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    // ★ 拿不到就用兜底值，⛔ 不要让首页因为配置接口挂了而白屏 ⚠
    placeholderData: FALLBACK,
  })
}
