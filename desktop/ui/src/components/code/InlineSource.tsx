import { useEffect, useState } from 'react'
import { Copy } from 'lucide-react'

import type { SourceFile } from '../../api/code'
import { personalApi } from '../../api/personal'
import CodeViewer from './CodeViewer'

interface InlineSourceProps {
  projectRef: string
  /** 相对项目根的文件路径（节点的 `file_path`） */
  path: string
  /** 当前节点所在行（1 起），会滚到中间并高亮 */
  line?: number
}

/**
 * ★★ **右栏内联源码**（节点面板的「代码」tab 用）
 *
 * 与 `CodeWorkspace` 的区别：
 * ```
 * CodeWorkspace  占满内容区、带文件树、可沉浸/全屏 —— 看整个项目
 * InlineSource    只在右栏里、不带文件树 —— 看**当前选中节点**那一段
 * ```
 *
 * 两者共用 `CodeViewer`（CodeMirror 6 只读）和 sidecar 的 `/source/` 接口，
 * 所以语法高亮、行号、跳行高亮的行为完全一致。
 */
export default function InlineSource({ projectRef, path, line }: InlineSourceProps) {
  const [source, setSource] = useState<SourceFile | null>(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!path) return
    let alive = true
    setSource(null)
    setError('')
    personalApi
      .readSource(projectRef, path)
      .then((d) => {
        if (!alive) return
        setSource(d)
        setError('')
      })
      .catch((e: Error) => {
        if (!alive) return
        setSource(null)
        setError(e.message || '读取失败')
      })
    return () => {
      alive = false
    }
  }, [projectRef, path])

  if (!path) {
    return (
      <div className="faint" style={{ padding: 16, fontSize: 12.5, lineHeight: 1.8 }}>
        这个节点没有对应的源码文件（手动结构里的节点就是这样）。
      </div>
    )
  }

  const copy = () => {
    if (!source) return
    void navigator.clipboard.writeText(source.text).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div
        className="code-filebar faint"
        style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 8 }}
      >
        <span
          title={path}
          style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {path}
          {line && line > 0 ? ` : ${line}` : ''}
        </span>
        {source && (
          <>
            <span style={{ flex: 'none' }}>{source.lang || '文本'} · {source.lines} 行</span>
            <button
              type="button"
              onClick={copy}
              title="复制全部代码"
              className="code-icon-btn"
              style={{ marginLeft: 'auto', flex: 'none' }}
            >
              <Copy size={14} strokeWidth={1.5} />
              {copied ? '已复制' : ''}
            </button>
          </>
        )}
      </div>

      {error ? (
        <div style={{ padding: 16, fontSize: 12.5, color: 'var(--text-sub)' }}>{error}</div>
      ) : source ? (
        <div style={{ flex: 1, minHeight: 0 }}>
          <CodeViewer text={source.text} lang={source.lang} focus={line && line > 0 ? line : null} />
        </div>
      ) : (
        <div className="faint" style={{ padding: 16, fontSize: 12.5 }}>正在读取源码…</div>
      )}
    </div>
  )
}
