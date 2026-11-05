/**
 * ★★★ **目录提取与跳转**（`D114` / `D131` · 2026-10-27）⚠
 *
 * 阅读页和写作页共用这一份 —— ⛔ 不要各写一套（规则迟早跑偏）⚠
 *
 * 口径（`D114`）：**只认 `#` / `##` / `###`**；
 *   「名字」（笔记标题）不参与目录 —— 它是身份，不是章节 ✅
 */

export interface TocItem {
  /** 1..3 */
  level: number
  /** 去掉行内 markdown 记号后的纯文本 */
  text: string
}

/**
 * 从 markdown 正文提取目录。
 *
 * ⚠ 用**逐行正则**，不解析 AST：目录只需要标题文字和级别，
 *   为它引入一次完整解析不划算（阅读页/写作页都是热路径）⚠
 */
export function extractToc(md: string): TocItem[] {
  const out: TocItem[] = []
  for (const raw of (md || '').split('\n')) {
    const m = /^(#{1,3})\s+(.+)$/.exec(raw.trim())
    if (!m) continue
    const text = m[2].replace(/[*`_~]/g, '').trim()
    if (text) out.push({ level: m[1].length, text })
  }
  return out
}

/**
 * 滚到指定标题。
 *
 * ⚠ 不靠锚点 id —— Milkdown 渲染出来的标题**没有 id**，
 *   所以在给定的根容器里按「级别 + 文字」找那个元素再滚 ⚠
 *
 * @param rootSelector 阅读页 `.note-body-card .ProseMirror`、写作页 `.milkdown .ProseMirror`
 * @param fallbackId   找不到时退回到滚到正文顶部（至少有个反应）
 */
export function scrollToHeading(
  text: string,
  level: number,
  rootSelector: string,
  fallbackId?: string,
): void {
  const root = document.querySelector(rootSelector)
  const all = root ? Array.from(root.querySelectorAll('h1,h2,h3')) : []
  const hit =
    all.find((el) => el.tagName === `H${level}` && el.textContent?.trim() === text) ||
    all.find((el) => el.textContent?.trim() === text)
  if (hit) {
    hit.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }
  if (fallbackId) document.getElementById(fallbackId)?.scrollIntoView({ block: 'start' })
}
