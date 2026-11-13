import { lazy, Suspense, useEffect, useState } from 'react'
import { BookOpen, Pencil } from 'lucide-react'
import { invoke } from '../api'

const RichEditor = lazy(() => import('./RichEditor'))

interface Props {
  projectRef: string
  noteRef: string
}

export default function NoteView({ projectRef, noteRef }: Props) {
  const [title, setTitle] = useState('')
  const [initial, setInitial] = useState('')
  const [body, setBody] = useState('')
  const [mode, setMode] = useState<'read' | 'edit'>('read')
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [ready, setReady] = useState(false)

  useEffect(() => {
    setReady(false)
    invoke('notes.get', projectRef, noteRef)
      .then((doc) => {
        setTitle(doc.meta.title || '')
        setInitial(doc.body)
        setBody(doc.body)
        setMode('read')
        setDirty(false)
        setStatus('')
        setReady(true)
      })
      .catch((e) => setStatus(String(e)))
  }, [projectRef, noteRef])

  const change = (md: string) => {
    setBody(md)
    setDirty(md !== initial)
    setStatus('')
  }

  const save = async () => {
    try {
      await invoke('notes.save', projectRef, noteRef, body, title)
      setInitial(body)
      setDirty(false)
      setStatus('已保存')
    } catch (e) {
      setStatus(String(e))
    }
  }

  return (
    <div className="pane note-pane">
      <div className="pane-bar">
        {mode === 'edit' ? (
          <input
            className="note-title"
            value={title}
            onChange={(e) => {
              setTitle(e.target.value)
              setDirty(true)
            }}
            placeholder="笔记标题"
          />
        ) : (
          <span className="note-title-text">{title || '（无标题）'}</span>
        )}
        <span className="faint">{status}</span>
        <button
          type="button"
          className="btn ghost"
          onClick={() => setMode(mode === 'read' ? 'edit' : 'read')}
        >
          {mode === 'read' ? <><Pencil size={13} /> 编辑</> : <><BookOpen size={13} /> 阅读</>}
        </button>
        <button type="button" className="btn primary" disabled={!dirty} onClick={() => void save()}>
          保存
        </button>
      </div>
      {ready && (
        <Suspense fallback={<div className="pane-loading faint">正在加载编辑器…</div>}>
          <RichEditor
            key={noteRef}
            initialMarkdown={initial}
            editable={mode === 'edit'}
            onChange={change}
          />
        </Suspense>
      )}
    </div>
  )
}
