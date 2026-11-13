import { useEffect, useState } from 'react'
import { invoke } from '../api'

interface Props {
  projectRef: string
  noteRef: string
}

export default function NoteView({ projectRef, noteRef }: Props) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saved, setSaved] = useState('')

  useEffect(() => {
    invoke('notes.get', projectRef, noteRef)
      .then((doc) => {
        setTitle(doc.meta.title || '')
        setBody(doc.body)
        setDirty(false)
      })
      .catch((e) => setSaved(String(e)))
  }, [projectRef, noteRef])

  const save = async () => {
    await invoke('notes.save', projectRef, noteRef, body, title)
    setDirty(false)
    setSaved('已保存')
  }

  return (
    <div className="pane note-pane">
      <div className="pane-bar">
        <input
          className="note-title"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value)
            setDirty(true)
          }}
          placeholder="笔记标题"
        />
        <span className="faint">{saved}</span>
        <button type="button" className="btn primary" disabled={!dirty} onClick={() => void save()}>
          保存
        </button>
      </div>
      <textarea
        className="note-body"
        value={body}
        onChange={(e) => {
          setBody(e.target.value)
          setDirty(true)
          setSaved('')
        }}
        placeholder="用 Markdown 写点什么…"
      />
    </div>
  )
}
