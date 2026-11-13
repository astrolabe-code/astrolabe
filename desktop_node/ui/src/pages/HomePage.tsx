import { useEffect, useState } from 'react'
import { FolderPlus, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { invoke } from '../api'
import type { Project } from '../../../shared/contract'

export default function HomePage() {
  const nav = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [root, setRoot] = useState('')
  const [quick, setQuick] = useState('')
  const [error, setError] = useState('')

  const load = async () => {
    try {
      setProjects(await invoke('projects.list'))
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const add = async () => {
    if (!root.trim()) return
    try {
      const p = await invoke('projects.add', root.trim())
      setRoot('')
      setError('')
      await load()
      nav(`/p/${p.ref}`, { state: { title: p.name } })
    } catch (e) {
      setError(String(e))
    }
  }

  const quickNote = async () => {
    if (!quick.trim() || !projects.length) return
    try {
      const p = projects[0]
      const n = await invoke('notes.save', p.ref, '', quick.trim(), '写一笔', 0)
      setQuick('')
      setError('')
      nav(`/p/${p.ref}/notes/${n.ref}`, { state: { title: '写一笔' } })
    } catch (e) {
      setError(String(e))
    }
  }

  const remove = async (ref: string) => {
    await invoke('projects.remove', ref)
    await load()
  }

  return (
    <div className="home">
      <div className="home-head">
        <h1>Astrolabe</h1>
        <div className="faint">把笔记钉在代码结构上</div>
      </div>

      <div className="home-quick card">
        <div className="home-quick-title">写一笔</div>
        <textarea
          value={quick}
          onChange={(e) => setQuick(e.target.value)}
          placeholder="随手记下来…"
          rows={3}
        />
        <button type="button" className="btn primary" onClick={() => void quickNote()}>
          保存并打开
        </button>
      </div>

      <div className="home-add card">
        <input
          value={root}
          onChange={(e) => setRoot(e.target.value)}
          placeholder="项目源码目录的绝对路径"
        />
        <button type="button" className="btn primary" onClick={() => void add()}>
          <FolderPlus size={13} /> 导入项目
        </button>
      </div>

      {error && <div className="home-error">{error}</div>}

      <div className="home-grid">
        {projects.map((p) => (
          <div key={p.ref} className="card home-card">
            <button
              type="button"
              className="home-card-main"
              onClick={() => nav(`/p/${p.ref}`, { state: { title: p.name } })}
            >
              <div className="home-card-title">{p.name}</div>
              <div className="faint home-card-path">{p.root}</div>
            </button>
            <button
              type="button"
              className="home-card-del"
              title="从清单移除"
              onClick={() => void remove(p.ref)}
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
        {projects.length === 0 && <div className="faint">还没有项目，先导入一个源码目录</div>}
      </div>
    </div>
  )
}
