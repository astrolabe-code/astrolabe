import { useEffect, useState } from 'react'
import { invoke } from '../api'

interface Props {
  projectRef: string
}

export default function CodePane({ projectRef }: Props) {
  const [files, setFiles] = useState<string[]>([])
  const [active, setActive] = useState('')
  const [text, setText] = useState('')

  useEffect(() => {
    invoke('source.tree', projectRef)
      .then((t) => setFiles(t.items))
      .catch((e) => setText(String(e)))
  }, [projectRef])

  const pick = async (file: string) => {
    setActive(file)
    try {
      const r = await invoke('source.read', projectRef, file)
      setText(r.text)
    } catch (e) {
      setText(String(e))
    }
  }

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
      </div>
      <pre className="code-text">{text || '点击左侧文件查看代码'}</pre>
    </div>
  )
}
