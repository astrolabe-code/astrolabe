import { cloneElement, isValidElement } from 'react'
import type { ReactNode } from 'react'

/**
 * ★★ 轻量 Markdown 渲染（`F2` 补充）—— **不引第三方依赖**
 *
 * 支持（够笔记用）：
 * - 标题 `# ~ ######`
 * - 段落（空行分段）
 * - **粗体** / *斜体* / `行内代码`
 * - 无序列表 `- ` / 有序列表 `1. `
 * - 代码块 ``` ```
 * - 引用 `> `
 * - 分隔线 `---`
 * - 链接 `[文字](url)`
 *
 * ⚠★ 全部走 **React 节点**渲染 —— ⛔ 不用 `dangerouslySetInnerHTML`
 *   ★ 用户写的内容不能变成可执行 HTML（XSS）✅
 */
export default function Markdown({
  text,
  trailing,
}: {
  text: string
  /**
   * ★★ **尾随节点**（* 追加到**最后一个块级元素的末尾**，* 保持内联）——
   *    · · 用途：* 段评气泡要「跟着相应段落之后」，* ⛔ 不是浮在最右边自成一排 ⚠
   */
  trailing?: ReactNode
}) {
  const nodes = renderBlocks(text)

  if (trailing && nodes.length > 0) {
    const last = nodes[nodes.length - 1] as ReactNode
    // ★ 只有段落 / 标题能安全地内联追加；* 列表 / 代码块 ⇒ 另起一行 ⚠
    if (isValidElement<{ children?: ReactNode }>(last)) {
      const tag = typeof last.type === 'string' ? last.type : ''
      if (/^(p|h[1-6])$/.test(tag)) {
        const kids = last.props.children
        const arr = Array.isArray(kids) ? kids : [kids]
        nodes[nodes.length - 1] = cloneElement(
          last,
          undefined,
          ...arr,
          <span key="md-trailing" style={{ marginLeft: 6, verticalAlign: 'middle' }}>
            {trailing}
          </span>,
        )
      } else {
        nodes.push(
          <p key="md-trailing-wrap" style={{ margin: '2px 0 0' }}>
            {trailing}
          </p>,
        )
      }
    }
  }

  return <div className="md-body">{nodes}</div>
}

/** ★ 这些行开头都算「块级元素」，段落遇到它们要断开 */
const isBlockStart = (line: string): boolean =>
  /^(#{1,6}\s|```|>\s|\s*[-*+]\s|\s*\d+[.)]\s|-{3,}$|\*{3,}$)/.test(line.trimStart())

function renderBlocks(src: string): ReactNode[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const out: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]

    // ---- 代码块 ----
    if (line.trimStart().startsWith('```')) {
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        buf.push(lines[i])
        i++
      }
      i++ // 跳过结束的 ```
      out.push(
        <pre key={key++} className="md-pre">
          <code>{buf.join('\n')}</code>
        </pre>,
      )
      continue
    }

    // ---- 空行 ----
    if (!line.trim()) {
      i++
      continue
    }

    // ---- 标题 ----
    const h = /^(#{1,6})\s+(.*)$/.exec(line.trimStart())
    if (h) {
      const level = h[1].length
      const content = inline(h[2], key)
      key += 100
      const style: React.CSSProperties = {
        fontSize: level === 1 ? 20 : level === 2 ? 17 : level === 3 ? 15 : 13.5,
        fontWeight: 700,
        margin: '12px 0 6px',
        lineHeight: 1.4,
      }
      if (level === 1) out.push(<h1 key={`h${key++}`} style={style}>{content}</h1>)
      else if (level === 2) out.push(<h2 key={`h${key++}`} style={style}>{content}</h2>)
      else if (level === 3) out.push(<h3 key={`h${key++}`} style={style}>{content}</h3>)
      else out.push(<h4 key={`h${key++}`} style={style}>{content}</h4>)
      // ⚠⚠ **必须推进行号** ——* 漏了这行 ⇒ 遇到 `# 标题` 就死循环、页面卡死 ⚠⚠
      i++
      continue
    }

    // ---- 分隔线 ----
    if (/^(-{3,}|\*{3,})$/.test(line.trim())) {
      out.push(<hr key={key++} style={{ border: 'none', borderTop: '1px solid var(--card-border)', margin: '12px 0' }} />)
      // ⚠ 同上：* 不推进就会卡在 `---` 这一行无限循环 ⚠
      i++
      continue
    }

    // ---- 引用 ----
    if (line.trimStart().startsWith('>')) {
      const buf: string[] = []
      while (i < lines.length && lines[i].trimStart().startsWith('>')) {
        buf.push(lines[i].trimStart().replace(/^>\s?/, ''))
        i++
      }
      out.push(
        <blockquote
          key={key++}
          style={{
            margin: '8px 0',
            padding: '6px 10px',
            borderLeft: '3px solid var(--accent)',
            background: 'var(--accent-dim)',
            borderRadius: 4,
            color: 'var(--text-sub)',
          }}
        >
          {inline(buf.join(' '), key)}
        </blockquote>,
      )
      key += 100
      continue
    }

    // ---- 无序列表 ----
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ''))
        i++
      }
      out.push(
        <ul key={key++} style={{ margin: '6px 0', paddingLeft: 22 }}>
          {items.map((t, k) => (
            <li key={k} style={{ margin: '2px 0' }}>
              {inline(t, key + k)}
            </li>
          ))}
        </ul>,
      )
      key += 100
      continue
    }

    // ---- 有序列表 ----
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ''))
        i++
      }
      out.push(
        <ol key={key++} style={{ margin: '6px 0', paddingLeft: 22 }}>
          {items.map((t, k) => (
            <li key={k} style={{ margin: '2px 0' }}>
              {inline(t, key + k)}
            </li>
          ))}
        </ol>,
      )
      key += 100
      continue
    }

    // ---- 段落（连续的普通行合成一段）----
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
      buf.push(lines[i].trim())
      i++
    }
    // ★★★ **兜底：绝不能原地踏步**（* 万一某行被 `isBlockStart` 判为块级、
    //   · · 却没有分支接管 ⇒ `i` 不推进 ⇒ 死循环、* 页面卡死）⚠⚠
    if (buf.length === 0) {
      i++
      continue
    }
    out.push(
      <p key={key++} style={{ margin: '6px 0', lineHeight: 1.85 }}>
        {inline(buf.join(' '), key)}
      </p>,
    )
    key += 100
  }

  return out
}

/** ★ 行内：`代码` / **粗** / *斜* / [文字](url) */
const INLINE_RE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(\[[^\]\n]+\]\([^)\n]+\))/

function inline(text: string, seed: number): ReactNode[] {
  const out: ReactNode[] = []
  let rest = text
  let k = seed

  while (rest) {
    const m = INLINE_RE.exec(rest)
    if (!m) {
      out.push(rest)
      break
    }
    if (m.index > 0) out.push(rest.slice(0, m.index))
    const tok = m[0]

    if (tok.startsWith('`')) {
      out.push(
        <code
          key={`c${k++}`}
          style={{
            padding: '1px 5px',
            borderRadius: 4,
            background: 'var(--bg-deep)',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            fontSize: '0.92em',
          }}
        >
          {tok.slice(1, -1)}
        </code>,
      )
    } else if (tok.startsWith('**')) {
      out.push(<strong key={`b${k++}`}>{tok.slice(2, -2)}</strong>)
    } else if (tok.startsWith('*')) {
      out.push(<em key={`i${k++}`}>{tok.slice(1, -1)}</em>)
    } else {
      const lm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok)
      if (lm) {
        out.push(
          <a
            key={`a${k++}`}
            href={lm[2]}
            target="_blank"
            rel="noreferrer noopener"
            style={{ color: 'var(--accent)', textDecoration: 'underline' }}
          >
            {lm[1]}
          </a>,
        )
      } else {
        out.push(tok)
      }
    }
    rest = rest.slice(m.index + tok.length)
  }

  return out
}
