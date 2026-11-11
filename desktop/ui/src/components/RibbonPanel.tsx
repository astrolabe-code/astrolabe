import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Search, X } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

import { personalApi } from '../api/personal'
import { ribbonActions, subscribeRibbon, type PanelKind } from '../lib/ribbonBus'

interface RibbonPanelProps {
  kind: PanelKind
  onClose: () => void
}

const TITLE: Record<PanelKind, string> = {
  search: '搜索',
  thinking: '思考模式',
}

/**
 * ★★ **功能面板**（Obsidian 的侧边 dock）
 *
 * 从 ribbon 右侧挤压展开，不盖住内容区。三个入口：文件树 / 跨项目搜索 / 思考模式。
 */
export default function RibbonPanel({ kind, onClose }: RibbonPanelProps) {
  const nav = useNavigate()

  return (
    <div
      style={{
        flexShrink: 0,
        width: 260,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--card, #fff)',
        borderRight: '1px solid var(--card-border)',
        minHeight: 0,
      }}
    >
      <div
        style={{
          flex: 'none',
          display: 'flex',
          alignItems: 'center',
          padding: '8px 12px',
          borderBottom: '1px solid var(--card-border)',
        }}
      >
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{TITLE[kind]}</span>
        <button
          type="button"
          onClick={onClose}
          title="收起面板"
          style={{
            marginLeft: 'auto',
            border: 0,
            background: 'transparent',
            cursor: 'pointer',
            color: 'var(--text-sub)',
          }}
        >
          <X size={14} />
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {kind === 'search' && <SearchPane onNavigate={(p) => { nav(p); onClose() }} />}
        {kind === 'thinking' && <ThinkingPane onClose={onClose} />}
      </div>
    </div>
  )
}

function SearchPane({ onNavigate }: { onNavigate: (path: string) => void }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<
    { ref: string; title: string; project_ref: string; project: string; snippet: string }[]
  >([])

  useEffect(() => {
    if (!q.trim()) {
      setHits([])
      return
    }
    let alive = true
    const t = window.setTimeout(() => {
      personalApi
        .searchCards(q.trim())
        .then((d) => alive && setHits(d.notes || []))
        .catch(() => alive && setHits([]))
    }, 250)
    return () => {
      alive = false
      window.clearTimeout(t)
    }
  }, [q])

  return (
    <div style={{ padding: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Search size={14} className="faint" />
        <input
          autoFocus
          className="input"
          placeholder="搜笔记（所有项目）"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ flex: 1, fontSize: 12.5 }}
        />
      </div>
      <div style={{ marginTop: 10 }}>
        {hits.map((h) => (
          <button
            key={`${h.project_ref}/${h.ref}`}
            type="button"
            onClick={() =>
              onNavigate(`/p/${encodeURIComponent(h.project_ref)}/notes/${h.ref}`)
            }
            style={{
              display: 'block',
              width: '100%',
              textAlign: 'left',
              padding: '7px 8px',
              marginBottom: 4,
              border: '1px solid var(--card-border)',
              borderRadius: 6,
              background: 'transparent',
              cursor: 'pointer',
            }}
          >
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{h.title || '（无标题）'}</div>
            <div className="faint" style={{ fontSize: 11 }}>{h.project}</div>
          </button>
        ))}
        {q.trim() && hits.length === 0 && <Hint>没找到相关笔记</Hint>}
      </div>
    </div>
  )
}

/** ★ 白板列表项（后端 boards/*.json，节点名已由边车查索引补上） */
interface BoardItem {
  vid: number
  name?: string
  qname?: string
  file_path?: string
  mtime: number
}

function ThinkingPane({ onClose }: { onClose: () => void }) {
  const nav = useNavigate()
  // ★ 面板是全局的：用 useLocation 拿**剥掉 basename(/app) 后**的路由路径解析项目 ref
  //   （bug 修复：之前用 window.location.pathname，前缀 /app 使正则匹配失败，列表整个不显示）
  const { pathname } = useLocation()
  const m = pathname.match(/^\/p\/([^/]+)/)
  const projectRef = m ? decodeURIComponent(m[1]) : ''
  // ★ 当前选中节点（NoteSection 注册到 ribbon 总线）⇒ 白板状态随节点切换变化
  const curVid = useSyncExternalStore(subscribeRibbon, () => ribbonActions().currentNodeVid)
  const [items, setItems] = useState<BoardItem[] | null>(null)

  useEffect(() => {
    if (!projectRef) return
    let alive = true
    personalApi
      .listBoards(projectRef)
      .then((d) => {
        if (alive) setItems(d.items || [])
      })
      .catch(() => {
        if (alive) setItems([])
      })
    return () => {
      alive = false
    }
  }, [projectRef])

  /** ★ 点列表项：跳到那个节点并自动开白板（复用 `?think=1&node=<vid>` 深链） */
  const openBoard = (vid: number) => {
    onClose()
    nav(`/p/${encodeURIComponent(projectRef)}?think=1&node=${vid}`)
  }

  /** 当前节点的白板条目（在全部列表里找；没保存过布局则 undefined） */
  const cur = curVid != null ? items?.find((it) => it.vid === curVid) : undefined

  return (
    <div style={{ padding: 12 }}>
      <button
        type="button"
        className="code-icon-btn"
        style={{ border: '1px solid var(--card-border)' }}
        onClick={() => {
          ribbonActions().openThinking?.()
          onClose()
        }}
      >
        打开思考模式白板
      </button>

      {/* ★ 当前节点的白板：随选中节点变化（所有者：「随着选择的节点不同而变化」）⚠ */}
      {curVid != null && (
        <div style={{ marginTop: 14 }}>
          <div className="faint" style={{ fontSize: 11, marginBottom: 6 }}>
            当前节点的白板
          </div>
          <div style={{ padding: '8px 10px', border: '1px solid var(--card-border)', borderRadius: 6 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>
              {cur?.name || `节点 ${curVid}`}
            </div>
            {items === null ? null : (
              <div className="faint" style={{ fontSize: 11 }}>
                {cur
                  ? `已保存过布局${cur.mtime ? ` · ${new Date(cur.mtime * 1000).toLocaleString()}` : ''}`
                  : '这块白板还没保存过布局'}
              </div>
            )}
          </div>
        </div>
      )}

      {projectRef && (
        <div style={{ marginTop: 14 }}>
          <div className="faint" style={{ fontSize: 11, marginBottom: 6 }}>
            项目里的全部白板
          </div>
          {items === null ? null : items.length === 0 ? (
            <Hint>还没有保存过白板</Hint>
          ) : (
            items.map((it) => (
              <button
                key={it.vid}
                type="button"
                title={it.qname || it.name}
                onClick={() => openBoard(it.vid)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '7px 8px',
                  marginBottom: 4,
                  border: `1px solid ${it.vid === curVid ? 'var(--accent, #2563eb)' : 'var(--card-border)'}`,
                  borderRadius: 6,
                  background: 'transparent',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>
                  {it.name || `节点 ${it.vid}`}
                </div>
                {it.qname && (
                  <div className="faint" style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {it.qname}
                  </div>
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}

function Hint({ children }: { children: ReactNode }) {
  return (
    <div className="faint" style={{ padding: 14, fontSize: 12, lineHeight: 1.8 }}>
      {children}
    </div>
  )
}
