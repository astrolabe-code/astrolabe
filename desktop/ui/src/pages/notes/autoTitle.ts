/**
 * ★★★ **名字的自动推导**（`D112` · 2026-10-27）⚠
 *
 * ## 所有者原话（逐字）
 *
 * > 「**真正的困难应该是取名困难**」
 * > 「**笔记每一个要有标题呀，不然以后谁知道这里面写的是什么东西，
 * >   截几个字到标题，也能分辨呀。**」
 * > 「**标题25个字差不多了吧？**」
 *
 * ## ⚠⚠ 这份是**后端 `_auto_title` 的镜像**
 *
 * ```
 * 后端  app/web/views/notes.py :: _auto_title()   ← 真正落库的那份
 * 前端  本文件                                    ← 只为「实时预览」
 * ```
 *
 * ⚠ **两处规则必须一致** —— 改任何一边都要同步另一边，否则会出现
 *   「预览说叫 A，存进去却是 B」这种最难查的错误 ⚠
 *
 * 规则（与后端逐条对应）：
 * ```
 * ① 取第一段（跳过空行）
 * ② 去掉行首的 # / > / - * + / 有序列表序号
 * ③ 去掉行内记号：* ` _ ~ 、[文字](链接)、HTML 标签
 * ④ ≤25 字 ⇒ 原样
 * ⑤ 25 字内有标点 ⇒ 断在【最后一个】标点处，**不加省略号**
 * ⑥ 没有标点 ⇒ 硬切 25 字 + 「…」
 * ```
 */

/** ★ 与后端 `TITLE_FALLBACK_MAX` 保持一致 ⚠ */
export const TITLE_FALLBACK_MAX = 25

/** ★ 与后端 `_TITLE_BREAKS` 保持一致 ⚠ */
const BREAKS = '，。！？；、,.!?;'

/** ★ 去掉行内 Markdown 记号（对齐后端 `_strip_md`）⚠ */
function stripMd(s: string): string {
  return s
    .replace(/[*`_~]/g, '')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .trim()
}

/**
 * ★★ 从正文推一个名字 —— **仅供编辑页预览** ⚠
 *
 * ⛔ 不要用它去保存：落库一律走后端，前端不参与决定最终值
 */
export function autoTitle(body: string): string {
  for (const rawLine of (body || '').split('\n')) {
    let raw = rawLine.trim()
    if (!raw) continue
    raw = raw.replace(/^[#>]+/, '').trim()
    raw = raw.replace(/^[-\*+]+/, '').trim()
    raw = raw.replace(/^\d+[.)]\s*/, '')
    const s = stripMd(raw)
    if (!s) continue

    if (s.length <= TITLE_FALLBACK_MAX) return s

    const window = s.slice(0, TITLE_FALLBACK_MAX)
    let cut = -1
    for (const ch of BREAKS) cut = Math.max(cut, window.lastIndexOf(ch))
    if (cut > 0) {
      const head = window.slice(0, cut).trim()
      if (head) return head
    }
    return s.slice(0, TITLE_FALLBACK_MAX).trimEnd() + '…'
  }
  return ''
}
