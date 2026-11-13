import { useEffect, useState } from 'react'
import { Minus, Square, X } from 'lucide-react'
import { Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { invoke } from './api'
import HomePage from './pages/HomePage'
import ProjectPage from './pages/ProjectPage'
import GraphPage from './pages/GraphPage'

interface Visit {
  path: string
  title: string
}

function defaultTitle(path: string): string {
  if (path === '/') return '首页'
  const parts = path.split('/').filter(Boolean)
  const last = decodeURIComponent(parts[parts.length - 1] || '')
  if (parts[0] === 'p' && parts.length === 2) return '项目'
  return last || '首页'
}

function TitleBar() {
  return (
    <div className="titlebar">
      <span className="titlebar-name">Astrolabe</span>
      <div className="titlebar-actions">
        <button type="button" title="最小化" onClick={() => void invoke('window.minimize')}>
          <Minus size={13} />
        </button>
        <button type="button" title="最大化" onClick={() => void invoke('window.toggleMaximize')}>
          <Square size={11} />
        </button>
        <button type="button" title="关闭" onClick={() => void invoke('window.close')}>
          <X size={13} />
        </button>
      </div>
    </div>
  )
}

function TabBar() {
  const loc = useLocation()
  const nav = useNavigate()
  const [visits, setVisits] = useState<Visit[]>([{ path: '/', title: '首页' }])
  const current = loc.pathname + loc.search
  const state = loc.state as { title?: string } | null

  useEffect(() => {
    const title = state?.title ?? defaultTitle(loc.pathname)
    setVisits((prev) => {
      const i = prev.findIndex((v) => v.path === current)
      if (i < 0) return [...prev, { path: current, title }]
      if (prev[i].title === title) return prev
      const next = [...prev]
      next[i] = { path: current, title }
      return next
    })
  }, [current, state])

  const close = (path: string) => {
    const next = visits.filter((v) => v.path !== path)
    const final = next.length ? next : [{ path: '/', title: '首页' }]
    setVisits(final)
    if (path === current) nav(final[final.length - 1].path)
  }

  return (
    <div className="tabbar">
      {visits.map((v) => (
        <div key={v.path} className={`tabbar-item${v.path === current ? ' active' : ''}`}>
          <button type="button" className="tabbar-label" onClick={() => nav(v.path)}>
            {v.title}
          </button>
          <button type="button" className="tabbar-close" title="关闭" onClick={() => close(v.path)}>
            <X size={11} />
          </button>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  return (
    <div className="app-shell">
      <TitleBar />
      <TabBar />
      <div className="app-body">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/p/:ref/*" element={<ProjectPage />} />
          <Route path="/graph/:ref" element={<GraphPage />} />
          <Route path="*" element={<HomePage />} />
        </Routes>
      </div>
    </div>
  )
}
