/**
 * ★★ **@ 提及的两个小工具**（`B214` · 前端侧）⚠
 *
 * ★★ 后端规则（`comments.py::MENTION_RE`）：`@` + Django 用户名允许的字符
 *   （* 字母数字 `. _ - +`）—— ★ 两边**必须一致**，* 否则「前端认为有 @、
 *   * 后端认为没有」⇒ * 400 挡在门口 ⚠
 *
 * ⚠★ 「回复谁」也是正文里的 @（* 没有 reply_to 列）⇒* 这两个工具同时服务
 *   · · ★ 渲染（高亮 / 回复头取第一个 @）
 *   · · ★ 校验（kind 需要 @ 时数一数）✅
 */

/** ★ 与后端 `MENTION_RE` 一致的 token 规则 */
const MENTION_RE = /@[A-Za-z0-9._+-]+/g

/** ★★ 正文里有几个 @ 提及（* `kind` 的判定依据）✅ */
export function countMentions(body: string): number {
  return (body.match(MENTION_RE) || []).length
}

/** ★★ 正文里**第一个** @ 的人（* 回复头显示用）✅ */
export function firstMention(body: string): string | null {
  const m = body.match(MENTION_RE)
  return m && m.length > 0 ? m[0].slice(1) : null
}

/**
 * ★★ 把正文切成「普通段 / @段 / 换行」三段式（* 渲染高亮用）✅
 *
 * ⚠ 返回的是**片段数组**，不是 HTML —— * ⛔ 不 dangerouslySetInnerHTML
 *   （* 正文是用户输入，* 拼 HTML 就是 XSS 的入口）⚠
 */
export type BodyPart = { text: string; mention: boolean }
export function splitByMentions(body: string): BodyPart[] {
  const parts: BodyPart[] = []
  let last = 0
  for (const m of body.matchAll(MENTION_RE)) {
    const idx = m.index ?? 0
    if (idx > last) parts.push({ text: body.slice(last, idx), mention: false })
    parts.push({ text: m[0], mention: true })
    last = idx + m[0].length
  }
  if (last < body.length) parts.push({ text: body.slice(last), mention: false })
  return parts
}

/**
 * ★★ **回复头用的正文**：去掉第一个 @token（* 它已经提到头部去了）
 *
 * B站口径：* 头部「回复 @X」+ 正文不再重复「@X」✅
 * ⚠ 只去第一个（* 回复目标）；* 正文里 @ 的其他人**留着**（* `both` 时高亮）⚠
 */
export function bodyAfterReplyHead(body: string): string {
  const m = body.match(MENTION_RE)
  if (!m || m.length === 0) return body
  const first = m[0]
  const idx = body.indexOf(first)
  if (idx < 0) return body
  return body.slice(0, idx) + body.slice(idx + first.length)
}
