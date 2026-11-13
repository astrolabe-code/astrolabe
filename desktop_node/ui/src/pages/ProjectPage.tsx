import { useEffect, useState } from 'react'
import { Network } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { invoke } from '../api'
import NodeListView from '../components/NodeListView'
import NoteListView from '../components/NoteListView'
import NoteView from '../components/NoteView'
import BoardListView from '../components/BoardListView'
import BoardView from '../components/BoardView'
import CodePane from '../components/CodePane'
import type { Project } from '../../../shared/contract'

type Tab = 'code' | 'notes' | 'content' | 'imitation'
type Selection = { vid: number; label: string }

const TABS: { key: Tab; label: string }[] = [
  { key: 'code', label: '代码' },
  { key: 'notes', label: '笔记' },
  { key: 'content', label: '内容' },
  { key: 'imitation', label: '仿写' },
]

function nodeKey(ref: string) {
  return `astrolabe.node.${ref}`
}

function readSelection(ref: string): Selection {
  try {
    const raw = localStorage.getItem(nodeKey(ref))
    if (!raw) return { vid: 0, label: '' }
    const v = JSON.parse(raw)
    return { vid: Number(v.vid) || 0, label: String(v.label || '') }
  } catch {
    return { vid: 0, label: '' }
  }
}

export default function ProjectPage() {
  const { ref = '' } = useParams()
  const loc = useLocation()
  const nav = useNavigate()
  const noteRef = loc.pathname.match(/\/notes\/([^/]+)$/)?.[1]
  const boardId = loc.pathname.match(/\/board\/([^/]+)$/)?.[1]
  const [tab, setTab] = useState<Tab>('notes')
  const [ribbon, setRibbon] = useState<'nodes' | 'think'>('nodes')
  const [project, setProject] = useState<Project | null>(null)
  const [selected, setSelected] = useState<Selection>(() => readSelection(ref))

  useEffect(() => {
    setSelected(readSelection(ref))
  }, [ref])

  useEffect(() => {
    invoke('projects.list')
      .then((list) => setProject(list.find((p) => p.ref === ref) ?? null))
      .catch(() => {})
  }, [ref])

  // 单向同步：URL 打开了笔记 / 白板 ⇒ 视图自动回到「内容」
  useEffect(() => {
    if (noteRef || boardId) setTab('content')
  }, [noteRef, boardId])

  const select = (vid: number, label: string) => {
    setSelected({ vid, label })
    try {
      localStorage.setItem(nodeKey(ref), JSON.stringify({ vid, label }))
    } catch {
      /* 隐私模式下不持久化也能用 */
    }
  }

  const openNote = (id: string, title: string) => {
    nav(`/p/${ref}/notes/${id}`, { state: { title: title || '笔记' } })
  }
  const openBoard = (id: string, name: string) => {
    nav(`/p/${ref}/board/${id}`, { state: { title: name || '白板' } })
  }

  return (
    <div className="project">
      <div className="project-head">
        <div className="project-head-left">
          <span className="project-name">{project?.name ?? ref}</span>
          <span className="faint project-node">
            {selected.label ? `当前节点：${selected.label}` : '未选节点'}
          </span>
        </div>
        <button
          type="button"
          className="btn ghost"
          onClick={() => nav(`/graph/${ref}`, { state: { title: '图谱' } })}
        >
          <Network size={13} /> 图谱
        </button>
      </div>

      <div className="project-body">
        <div className="ribbon">
          <button
            type="button"
            className={ribbon === 'nodes' ? 'active' : ''}
            onClick={() => setRibbon('nodes')}
            title="节点"
          >
            节点
          </button>
          <button
            type="button"
            className={ribbon === 'think' ? 'active' : ''}
            onClick={() => setRibbon('think')}
            title="思考模式"
          >
            白板
          </button>
        </div>

        <div className="ribbon-pane">
          {ribbon === 'nodes' ? (
            <NodeListView projectRef={ref} selectedVid={selected.vid} onSelect={select} />
          ) : (
            <BoardListView projectRef={ref} nodeVid={selected.vid} onOpen={openBoard} />
          )}
        </div>

        <div className="workspace">
          <div className="code-tabs">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                className={`code-tab${tab === t.key ? ' active' : ''}`}
                onClick={() => setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="workspace-body">
            {tab === 'code' ? (
              <CodePane projectRef={ref} />
            ) : tab === 'notes' ? (
              <NoteListView projectRef={ref} nodeVid={selected.vid} onOpen={openNote} />
            ) : tab === 'imitation' ? (
              <div className="pane-empty faint">仿写</div>
            ) : noteRef ? (
              <NoteView projectRef={ref} noteRef={noteRef} />
            ) : boardId ? (
              <BoardView projectRef={ref} boardId={boardId} />
            ) : (
              <div className="pane-empty" />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
