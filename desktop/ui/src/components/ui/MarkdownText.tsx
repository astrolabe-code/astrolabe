import { useMemo, type ReactNode } from 'react'
import { remark } from 'remark'
import remarkGfm from 'remark-gfm'

/**
 * ★★ **轻量 markdown 渲染**（问答回答用）
 *
 * 所有者原话（2026-11-17）：
 * 「你这没有把回答用markdown渲染呀？你参考一下openwebui的设计呢？」
 *
 * ## 为什么自己渲染，而不是 innerHTML
 *
 * OpenWebUI 的做法是 `marked` + `DOMPurify` 再塞 `innerHTML`。
 * 我们这里：
 *   · 没有 marked，但 Milkdown 依赖里已有 `remark` / `remark-gfm`
 *   · **不拼 HTML 字符串**、不用 `dangerouslySetInnerHTML` ⇒ 天然没有 XSS 面
 *   · 直接产出 React 元素，样式跟着主题变量走
 *
 * ## 支持范围（够回答用）
 *
 * 段落 / 一到六级标题 / 无序与有序列表 / 代码块 / 行内代码 /
 * 粗体 / 斜体 / 删除线 / 链接 / 引用 / 分隔线 / GFM 表格
 *
 * ⚠ 流式输出时**每个 chunk 都重新解析一次**：回答通常几百字，
 *   remark 解析是毫秒级，`useMemo` 按文本缓存，不卡。
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

const mono: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '0.94em',
}

function renderInline(nodes: any[], keyBase: string): ReactNode[] {
  return (nodes || []).map((n: any, i: number) => {
    const k = `${keyBase}-${i}`
    switch (n.type) {
      case 'text':
        return n.value as string
      case 'inlineCode':
        return (
          <code
            key={k}
            style={{
              ...mono,
              padding: '0 4px',
              borderRadius: 3,
              background: 'rgba(127,127,127,.18)',
            }}
          >
            {n.value}
          </code>
        )
      case 'strong':
        return <strong key={k}>{renderInline(n.children, k)}</strong>
      case 'emphasis':
        return <em key={k}>{renderInline(n.children, k)}</em>
      case 'delete':
        return <del key={k}>{renderInline(n.children, k)}</del>
      case 'link':
        return (
          <a
            key={k}
            href={n.url}
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--accent)' }}
          >
            {renderInline(n.children, k)}
          </a>
        )
      case 'break':
        return <br key={k} />
      default:
        return n.children ? (
          <span key={k}>{renderInline(n.children, k)}</span>
        ) : null
    }
  })
}

function renderBlocks(nodes: any[], keyBase: string): ReactNode[] {
  return (nodes || []).map((n: any, i: number) => {
    const k = `${keyBase}-${i}`
    switch (n.type) {
      case 'paragraph':
        return (
          <p key={k} style={{ margin: '0 0 8px' }}>
            {renderInline(n.children, k)}
          </p>
        )

      case 'heading': {
        const size = [17, 15.5, 14.5, 13.5, 13, 12.5][Math.min(n.depth - 1, 5)]
        return (
          <div
            key={k}
            style={{
              margin: '10px 0 6px',
              fontWeight: 600,
              fontSize: size,
              lineHeight: 1.5,
            }}
          >
            {renderInline(n.children, k)}
          </div>
        )
      }

      case 'code':
        return (
          <pre
            key={k}
            style={{
              margin: '8px 0',
              padding: '8px 10px',
              borderRadius: 6,
              background: 'rgba(127,127,127,.12)',
              overflowX: 'auto',
              lineHeight: 1.6,
            }}
          >
            <code style={mono}>{n.value}</code>
          </pre>
        )

      case 'list': {
        const Tag = n.ordered ? 'ol' : 'ul'
        return (
          <Tag
            key={k}
            style={{
              margin: '0 0 8px',
              paddingLeft: 22,
              listStyleType: n.ordered ? 'decimal' : 'disc',
            }}
          >
            {(n.children || []).map((li: any, j: number) => (
              <li key={`${k}-${j}`} style={{ margin: '2px 0' }}>
                {(li.children || []).map((c: any, m: number) =>
                  c.type === 'paragraph' ? (
                    <span key={m}>{renderInline(c.children, `${k}-${j}-${m}`)}</span>
                  ) : (
                    <span key={m}>{renderBlocks([c], `${k}-${j}-${m}`)}</span>
                  ),
                )}
              </li>
            ))}
          </Tag>
        )
      }

      case 'blockquote':
        return (
          <div
            key={k}
            style={{
              margin: '6px 0',
              paddingLeft: 10,
              borderLeft: '3px solid var(--card-border)',
              color: 'var(--text-sub)',
            }}
          >
            {renderBlocks(n.children, k)}
          </div>
        )

      case 'thematicBreak':
        return (
          <hr
            key={k}
            style={{ border: 0, borderTop: '1px solid var(--card-border)', margin: '10px 0' }}
          />
        )

      case 'table':
        return (
          <div key={k} style={{ overflowX: 'auto', margin: '8px 0' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: '0.96em' }}>
              <tbody>
                {(n.children || []).map((row: any, r: number) => (
                  <tr key={`${k}-${r}`}>
                    {(row.children || []).map((cell: any, c: number) => (
                      <td
                        key={`${k}-${r}-${c}`}
                        style={{
                          border: '1px solid var(--card-border)',
                          padding: '3px 8px',
                        }}
                      >
                        {renderInline(cell.children, `${k}-${r}-${c}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )

      default:
        // 认不出的块：能显示文字就显示，⛔ 不要整段消失
        return n.children ? (
          <div key={k}>{renderBlocks(n.children, k)}</div>
        ) : n.value ? (
          <p key={k} style={{ margin: '0 0 8px' }}>
            {String(n.value)}
          </p>
        ) : null
    }
  })
}

interface MarkdownTextProps {
  text: string
  /** 紧凑模式：问答气泡里用，行距小一点 */
  compact?: boolean
}

export default function MarkdownText({ text, compact }: MarkdownTextProps) {
  const tree = useMemo(() => {
    try {
      // GFM：表格、删除线、任务列表、自动链接
      return remark().use(remarkGfm).parse(String(text || ''))
    } catch {
      return null
    }
  }, [text])

  const body = tree ? renderBlocks((tree as any).children, 'md') : text

  return (
    <div
      style={{
        fontSize: 12.5,
        lineHeight: compact ? 1.7 : 1.75,
        wordBreak: 'break-word',
      }}
    >
      {body}
    </div>
  )
}
