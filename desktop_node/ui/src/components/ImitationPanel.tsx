import { useEffect, useState } from 'react'
import Editor from 'react-simple-code-editor'
import { Plus, Trash2 } from 'lucide-react'
import { invoke } from '../api'
import ConfirmDialog from './ConfirmDialog'
import type { ImitationItem } from '../../../shared/contract'

/** 通用关键字集合：覆盖仿写常见的 C/C++/Java/Python/JS */
const KEYWORDS = new Set([
  'if', 'else', 'elif', 'for', 'while', 'return', 'break', 'continue', 'class', 'struct',
  'enum', 'union', 'typedef', 'const', 'static', 'void', 'int', 'char', 'float', 'double',
  'long', 'short', 'unsigned', 'signed', 'public', 'private', 'protected', 'new', 'delete',
  'this', 'import', 'from', 'package', 'try', 'catch', 'except', 'finally', 'throw', 'raise',
  'function', 'var', 'let', 'def', 'lambda', 'yield', 'pass', 'None', 'True', 'False',
  'null', 'true', 'false', 'async', 'await', 'in', 'is', 'not', 'and', 'or', 'with', 'as',
  'include', 'define', 'namespace', 'using', 'template', 'typename', 'interface',
  'extends', 'implements', 'self', 'super',
])

const TOKEN =
  /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|\b(\d+(?:\.\d+)?)\b|\b([A-Za-z_]\w*)\b/g

function escapeHtml(s: string) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 先转义再包 span，绝不会把代码当 HTML 执行 */
function highlight(code: string): string {
  let out = ''
  let last = 0
  for (const m of code.matchAll(TOKEN)) {
    const at = m.index ?? 0
    out += escapeHtml(code.slice(last, at))
    const token = m[0]
    if (m[1]) out += `<span class="token comment">${escapeHtml(token)}</span>`
    else if (m[2]) out += `<span class="token string">${escapeHtml(token)}</span>`
    else if (m[3]) out += `<span class="token number">${escapeHtml(token)}</span>`
    else if (KEYWORDS.has(m[4])) out += `<span class="token keyword">${escapeHtml(token)}</span>`
    else out += escapeHtml(token)
    last = at + token.length
  }
  return out + escapeHtml(code.slice(last))
}

interface Props {
  projectRef: string
  nodeVid: number
}

export default function ImitationPanel({ projectRef, nodeVid }: Props) {
  const [items, setItems] = useState<ImitationItem[]>([])
  const [active, setActive] = useState('')
  const [title, setTitle] = useState('')
  const [ext, setExt] = useState('txt')
  const [text, setText] = useState('')
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [pendingDel, setPendingDel] = useState(false)

  // 新建版本时按选中节点的源文件扩展名决定语言
  useEffect(() => {
    if (!nodeVid) return
    invoke('graph.nodes', projectRef)
      .then((nodes) => {
        const n = nodes.find((x) => x.vid === nodeVid)
        if (n?.file) setExt(n.file.split('.').pop() || 'txt')
      })
      .catch(() => {})
  }, [projectRef, nodeVid])

  const openVersion = async (id: string) => {
    const doc = await invoke('imitation.get', projectRef, id)
    setActive(id)
    setTitle(doc.title)
    setExt(doc.ext)
    setText(doc.text)
    setDirty(false)
    setStatus('')
  }

  const load = async (prefer?: string) => {
    if (!nodeVid) {
      setItems([])
      setActive('')
      setText('')
      return
    }
    const list = await invoke('imitation.list', projectRef, nodeVid)
    setItems(list)
    const pick = prefer && list.some((x) => x.id === prefer) ? prefer : list.length ? list[list.length - 1].id : ''
    if (!pick) {
      setActive('')
      setTitle('')
      setText('')
      setDirty(false)
      return
    }
    await openVersion(pick)
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectRef, nodeVid])

  const saveNow = async () => {
    if (!active || !dirty) return
    await invoke('imitation.save', projectRef, active, text, title)
    setDirty(false)
    setStatus('已保存')
    setItems(await invoke('imitation.list', projectRef, nodeVid))
  }

  // 停止输入 800ms 自动保存；切换版本前也会先 flush
  useEffect(() => {
    if (!active || !dirty) return
    const timer = window.setTimeout(() => void saveNow(), 800)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, title, active, dirty])

  const switchTo = async (id: string) => {
    if (id === active) return
    await saveNow()
    await openVersion(id)
  }

  const create = async () => {
    await saveNow()
    const it = await invoke('imitation.create', projectRef, nodeVid, ext)
    await load(it.id)
  }

  const remove = async () => {
    if (!active) return
    await invoke('imitation.remove', projectRef, active)
    setPendingDel(false)
    setDirty(false)
    await load()
  }

  if (!nodeVid) {
    return <div className="pane-empty faint">先选中一个节点，再写仿写。</div>
  }

  return (
    <div className="pane imitation-pane">
      <div className="imitation-bar">
        <div className="imitation-versions">
          {items.map((it) => (
            <button
              key={it.id}
              type="button"
              className={`imitation-chip${it.id === active ? ' active' : ''}`}
              onClick={() => void switchTo(it.id)}
            >
              {it.title}
            </button>
          ))}
        </div>
        <button type="button" className="btn ghost" onClick={() => void create()}>
          <Plus size={13} /> 新建版本
        </button>
      </div>

      {active ? (
        <>
          <div className="pane-bar">
            <input
              className="note-title"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value)
                setDirty(true)
                setStatus('')
              }}
              placeholder="版本标题"
            />
            <span className="faint">.{ext}</span>
            <span className="faint">{status || (dirty ? '编辑中…' : '')}</span>
            <button type="button" className="link-btn" onClick={() => setPendingDel(true)}>
              <Trash2 size={11} /> 删除
            </button>
          </div>
          <div className="imitation-editor">
            <Editor
              value={text}
              onValueChange={(v) => {
                setText(v)
                setDirty(true)
                setStatus('')
              }}
              highlight={highlight}
              padding={16}
              className="imitation-code"
              textareaClassName="imitation-code-input"
            />
          </div>
        </>
      ) : (
        <div className="pane-empty faint">还没有仿写，点「新建版本」开始默写</div>
      )}

      <ConfirmDialog
        open={pendingDel}
        title="删除仿写"
        message={`删除「${title}」？删除后不可恢复。`}
        onConfirm={() => void remove()}
        onCancel={() => setPendingDel(false)}
      />
    </div>
  )
}
