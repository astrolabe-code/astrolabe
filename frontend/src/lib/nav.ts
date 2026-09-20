/**
 * ★ 站内跳转的小工具（`B170`）
 *
 * ⚠★ 为什么需要它：★ `?next=` 是**用户可控**的 ——
 * ★★ 若直接 `navigate(next)`，攻击者只要构造 `/app/login?next=https://evil.com`
 * ⇒ ★ 登录后就会把人**送去站外**（★ 钓鱼页可以伪装成"刚刚登录的页面"）⚠
 *
 * ★ 后端 `safe_next_url()` **已经挡过一次**（★ 它拦的是「OAuth 回调重定向」那条路）——
 * ★★ 而这是**另一条路**（★ 前端自己 `navigate`）
 * ⇒ ★★★ **两条路都要挡**：⚠ 只挡后端那条，等于给前端留了个洞 ⚠
 */

/**
 * ★★ 只放行**站内绝对路径**。
 *
 * 挡两种形态（★ 与后端 `safe_next_url()` 同一套口径）：
 * - ⚠ `//evil.com` —— ★ **协议相对 URL**，浏览器会当成 `https://evil.com`
 * - ⚠ `/\evil.com` —— ★ 某些浏览器会把它**归一成 `//evil.com`**
 */
export function safeInternalPath(raw: string | null | undefined, fallback = '/'): string {
  const v = (raw || '').trim()
  if (!v) return fallback
  if (!v.startsWith('/') || v.startsWith('//') || v.startsWith('/\\')) return fallback
  return v
}
