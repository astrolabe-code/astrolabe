/**
 * ★★ **代码块语法高亮**（2026-10-24）⚠
 *
 * ## ★ 为什么自己算区间
 *
 * ```\n * Prism 默认输出 **HTML 字符串** —— 渲染页是 ProseMirror 文档，⛔ 不能塞 HTML\n * ⇒ 这里把 token 流换算成「字符区间 + 类名」，交给 `Decoration.inline` 上色 ✅\n * ```
 *
 * ## ★ 配色
 *
 * ⚠ 不引入 Prism 自带主题（* 那是固定的浅色/深色两套），
 *   ★ 改用站点已有的 `--code-*` 变量 ⇒ 深浅主题自动跟随 ✅
 */
import Prism from 'prismjs'
import { $prose } from '@milkdown/utils'
import type { EditorState } from 'prosemirror-state'
import { Plugin } from 'prosemirror-state'
import { Decoration, DecorationSet } from 'prosemirror-view'
// ★ 常用语言（* prismjs 默认只带 markup / css / clike / javascript）⚠
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-bash'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-sql'
import 'prismjs/components/prism-go'
import 'prismjs/components/prism-rust'
import 'prismjs/components/prism-java'
import 'prismjs/components/prism-yaml'
import 'prismjs/components/prism-markdown'
import 'prismjs/components/prism-diff'

/** 一段需要上色的字符区间（* 相对代码块内容起点）⚠ */
export interface HighlightRange {
  from: number
  to: number
  cls: string
}

/** ★ token 类型 → 站点变量对应的类名（* 见 `index.css` 的 `.md-tok-*`）⚠ */
const CLASS_OF: Record<string, string> = {
  keyword: 'md-tok-key',
  builtin: 'md-tok-key',
  tag: 'md-tok-key',
  important: 'md-tok-key',

  number: 'md-tok-num',
  boolean: 'md-tok-num',
  constant: 'md-tok-num',
  symbol: 'md-tok-num',
  deleted: 'md-tok-num',

  string: 'md-tok-str',
  char: 'md-tok-str',
  regex: 'md-tok-str',
  'attr-value': 'md-tok-str',
  selector: 'md-tok-str',
  inserted: 'md-tok-str',

  function: 'md-tok-fn',
  'class-name': 'md-tok-fn',
  'maybe-class-name': 'md-tok-fn',

  comment: 'md-tok-com',
  prolog: 'md-tok-com',
  doctype: 'md-tok-com',
  cdata: 'md-tok-com',

  operator: 'md-tok-dim',
  punctuation: 'md-tok-dim',

  property: 'md-tok-dec',
  'attr-name': 'md-tok-dec',
  variable: 'md-tok-dec',
  parameter: 'md-tok-dec',
}

/** ★ 常见别名 → Prism 的语言名 ⚠ */
const ALIAS: Record<string, string> = {
  js: 'javascript',
  ts: 'typescript',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yml: 'yaml',
  md: 'markdown',
  html: 'markup',
  xml: 'markup',
  vue: 'markup',
  rs: 'rust',
  golang: 'go',
  'c++': 'cpp',
  kt: 'kotlin',
}

/** ⚠ 缓存：同一段代码反复渲染时不必重算（* 会话内有效）⚠ */
const cache = new Map<string, HighlightRange[]>()

function lengthOf(content: string | Prism.Token | (string | Prism.Token)[]): number {
  if (typeof content === 'string') return content.length
  if (Array.isArray(content)) return content.reduce((n, t) => n + lengthOf(t), 0)
  return lengthOf(content.content)
}

function walk(
  tokens: (string | Prism.Token)[],
  base: number,
  out: HighlightRange[],
): void {
  let offset = base
  for (const token of tokens) {
    if (typeof token === 'string') {
      offset += token.length
      continue
    }

    const len = lengthOf(token.content)
    const cls = CLASS_OF[token.type]
    if (cls && len > 0) out.push({ from: offset, to: offset + len, cls })

    // ★ 嵌套 token（如 JSX 里的表达式）继续下钻，* 内层会覆盖外层颜色 ⚠
    if (Array.isArray(token.content)) walk(token.content, offset, out)
    offset += len
  }
}

/**
 * ★ 计算一段代码的高亮区间（* 语言不认识 ⇒ 返回空，按纯文本渲染）⚠
 */
export function highlightRanges(code: string, language: string): HighlightRange[] {
  const lang = (language || '').trim().toLowerCase()
  if (!code || !lang) return []

  const key = `${lang}\u0000${code}`
  const hit = cache.get(key)
  if (hit) return hit

  const grammar = Prism.languages[ALIAS[lang] ?? lang]
  if (!grammar) return []

  let ranges: HighlightRange[] = []
  try {
    ranges = []
    walk(Prism.tokenize(code, grammar), 0, ranges)
  } catch {
    return []
  }

  // ⚠ 缓存别无限长（* 长文滚动时会有很多代码块）⚠
  if (cache.size > 200) cache.clear()
  cache.set(key, ranges)
  return ranges
}


/** ★ 行号元素（* 不可选中、不参与复制）⚠ */
function lineNoEl(n: number): HTMLElement {
  const el = document.createElement('span')
  el.className = 'md-line-no'
  el.textContent = String(n)
  el.setAttribute('contenteditable', 'false')
  return el
}

/**
 * ★★ **代码块高亮 + 行号插件**（2026-10-24）⚠
 *
 * ```
 * 高亮：Prism 区间 ⇒ Decoration.inline
 * 行号：每行行首插一个 Decoration.widget（* 纯文本节点，不影响文档结构）
 * ⚠ 行号要对得齐 ⇒ 代码块必须 `white-space: pre`（不自动折行），横向滚动 ⚠
 * ```
 *
 * ★ 阅读页与**编辑器**共用同一个插件 ✅
 */
export function makeHighlightPlugin() {
  return $prose(
    () =>
      new Plugin({
        props: {
          decorations(state: EditorState) {
            const decos: Decoration[] = []

            state.doc.descendants((node, pos) => {
              if (node.type.name !== 'code_block') return

              const lang = (node.attrs.language as string) || ''
              const code = node.textContent
              const start = pos + 1 // ★ 代码块内容起点

              // ① 语法着色（* 只在写了语言时做）⚠
              if (lang && code) {
                for (const r of highlightRanges(code, lang)) {
                  decos.push(
                    Decoration.inline(start + r.from, start + r.to, { class: r.cls }),
                  )
                }
              }

              // ② 行号（* 从 1 开始，逐行行首）⚠
              if (code) {
                // ⚠ 每行一个闭包 ⇒ 必须**当场取值**，否则全部捕获到最后一行的数字 ⚠
                const addNo = (at: number, n: number) => {
                  decos.push(Decoration.widget(at, () => lineNoEl(n), { side: -1 }))
                }
                addNo(start, 1)
                let line = 1
                for (let i = 0; i < code.length; i++) {
                  if (code[i] === '\n') {
                    line += 1
                    addNo(start + i + 1, line)
                  }
                }
              }
            })

            return decos.length ? DecorationSet.create(state.doc, decos) : DecorationSet.empty
          },
        },
      }),
  )
}
