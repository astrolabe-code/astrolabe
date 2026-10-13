/**
 * Astrolabe · 前端：**从仓库地址反推 `owner/repo`**
 *
 * ★★ `B182` 起前端要自己在浏览器里查 commit sha（★ 不烧服务端的 API 配额）——
 *   ★ 而查询要知道 `owner/repo` ⇒ ★ 这就是把它算出来的地方 ✅
 *
 * ⚠★ 与后端 `core/fetch.py::repo_full_from_url()` **同一套口径** ⚠
 *   · ★ 两边不一致就会出现「前端查得到、后端说地址不对」的怪事
 *   · ★ 改一边**必须**同步改另一边
 */

/**
 * @example
 *   repoFullOf('https://github.com/kennethreitz/records')  // 'kennethreitz/records'
 *   repoFullOf('https://github.com/kennethreitz/records/') // 'kennethreitz/records'
 *   repoFullOf('https://github.com/kennethreitz/records.git') // 'kennethreitz/records'
 *   repoFullOf('git@github.com:kennethreitz/records.git')  // 'kennethreitz/records'
 *   repoFullOf('https://github.com/kennethreitz/records/tree/main') // 'kennethreitz/records'
 */
export function repoFullOf(repoUrl: string): string {
  let s = (repoUrl || '').trim()
  if (!s) return ''
  s = s.replace(/^git@([^:]+):/, 'https://$1/') // ★ SSH 形态
  s = s.replace(/\.git$/, '') // ★ 结尾的 .git
  s = s.replace(/^[a-z]+:\/\//i, '') // ★ 协议
  s = s.replace(/^[^/]*@/, '') // ★ 可能的 user@ 前缀
  const parts = s.split('/').filter(Boolean)
  // ★ 只认「主机 / owner / repo」—— ★ 多出来的段（tree/main 之类）一律砍掉
  return parts.length >= 3 ? `${parts[1]}/${parts[2]}` : ''
}
