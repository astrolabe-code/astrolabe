import { useEffect, useMemo, useState } from 'react'
import { invoke } from '../api'
import { highlightCode } from '../lib/highlight'

interface Props {
  projectRef: string
}

export default function CodePane({ projectRef }: Props) {
  const [files, setFiles] = useState<string[]>([])
  const [active, setActive] = useState('')
  const [text, setText] = useState('')
  const [lang, setLang] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    invoke('source.tree', projectRef)
      .then((t) => {
        setFiles(t.items)
        setError('')
      })
      .catch((e) => setError(String(e)))
  }, [projectRef])

  const pick = async (file: string) => {
    setActive(file)
    try {
      const r = await invoke('source.read', projectRef, file)
      setText(r.text)
      setLang(r.lang)
      setError('')
    } catch (e) {
      setText('')
      setError(String(e))
    }
  }

  // highlightCode 先转义再包 span，dangerouslySetInnerHTML 不会执行代码里的 HTML
  const html = useMemo(() => highlightCode(text, lang), [text, lang])
  const lineCount = text ? text.split('\n').length : 0

  return (
    <div className="pane code-pane">
      <div className="filetree">
        {files.map((f) => (
          <button
            key={f}
            type="button"
            className={`filetree-item${f === active ? ' active' : ''}`}
            onClick={() => void pick(f)}
          >
            {f}
          </button>
        ))}
        {files.length === 0 && !error && (
          <div className="faint filetree-empty">没有可显示的文件</div>
        )}
      </div>

      <div className="code-view">
        <div className="code-view-bar faint">
          {active ? `${active} · ${lang || 'text'} · ${lineCount} 行` : '代码'}
        </div>
        <div className="code-scroll">
          {error ? (
            <div className="code-placeholder faint">{error}</div>
          ) : !text ? (
            <div className="code-placeholder faint">点击左侧文件查看代码</div>
          ) : (
            <>
              <div className="code-gutter" aria-hidden="true">
                {Array.from({ length: lineCount }, (_, i) => (
                  <div key={i}>{i + 1}</div>
                ))}
              </div>
              <pre className="code-text" dangerouslySetInnerHTML={{ __html: html }} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
