import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Search, Trash2, X } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

import { personalApi, type BoardItem } from '../api/personal'
import { errorMessage } from '../api/errors'
import ConfirmDialog from './ui/ConfirmDialog'
import { ribbonActions, subscribeRibbon, type PanelKind } from '../lib/ribbonBus'
import { closeTab, openTab } from '../lib/tabBus'

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
  const { pathname } = useLocation()
  const m = pathname.match(/^\/p\/([^/]+)/)
  const projectRef = m ? decodeURIComponent(m[1]) : ''
  const curVid = useSyncExternalStore(subscribeRibbon, () => ribbonActions().currentNodeVid)

  /** ★ 搜索结果跳笔记：命中里就有标题，直接拿它开标签 */
  const go = (path: string, title?: string) => {
    if (title) openTab(path, title)
    onClose()
    nav(path)
  }

  /** ★ 打开这个节点挂载的某一块白板：列表里就有名字，直接拿它开标签 */
  const openBoard = (boardId: string, name?: string) => {
    const path = `/p/${encodeURIComponent(projectRef)}/board/${encodeURIComponent(boardId)}`
    openTab(path, name || '白板')
    onClose()
    nav(`${path}?node=${curVid ?? 0}`)
  }

  /** ★★ 新建白板（跟「新建笔记」一样的动作）：后端建一块空白白板并打开它 ⚠ */
  const createBoard = async () => {
    if (curVid == null || !projectRef) return
    try {
      const d = await personalApi.newBoard(projectRef, curVid)
      openBoard(d.item.id, d.item.name)
    } catch {
      /* 新建失败静默 */
    }
  }

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
        {kind === 'thinking' ? (
          /* ★ 所有者：「不是打开思考模式，而是新建白板，逻辑跟笔记是一样的」⚠ */
          <button
            type="button"
            onClick={createBoard}
            title="在当前节点新建一块白板"
            style={{
              marginLeft: 'auto',
              padding: '3px 8px',
              fontSize: 11,
              border: '1px solid var(--card-border)',
              borderRadius: 6,
              background: 'transparent',
              color: 'var(--text-sub)',
              cursor: 'pointer',
            }}
          >
            新建白板
          </button>
        ) : (
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
        )}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {kind === 'search' && <SearchPane onNavigate={go} />}
        {kind === 'thinking' && (
          <ThinkingPane projectRef={projectRef} curVid={curVid} onOpen={openBoard} />
        )}
      </div>
    </div>
  )
}

function SearchPane({ onNavigate }: { onNavigate: (path: string, title?: string) => void }) {
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
              onNavigate(
                `/p/${encodeURIComponent(h.project_ref)}/notes/${h.ref}`,
                h.title || '笔记',
              )
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

function ThinkingPane({ projectRef, curVid, onOpen }: {
  projectRef: string
  curVid: number | undefined
  onOpen: (boardId: string, name?: string) => void
}) {
  const [items, setItems] = useState<BoardItem[] | null>(null)
  // ★ 删除走和笔记同一套：小文字按钮 + ConfirmDialog 确认框
  const [pendingDel, setPendingDel] = useState<BoardItem | null>(null)
  const [delBusy, setDelBusy] = useState(false)
  const [delErr, setDelErr] = useState('')
  const nav = useNavigate()
  const loc = useLocation()

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

  /** 确认框里点「删除」后才真正删除；同时清掉对应标签与内容区 */
  const confirmDelete = async () => {
    if (!pendingDel) return
    const id = pendingDel.id
    setDelBusy(true)
    setDelErr('')
    try {
      await personalApi.deleteBoard(projectRef, id)
      setItems((prev) => (prev ?? []).filter((x) => x.id !== id))
      const path = `/p/${encodeURIComponent(projectRef)}/board/${encodeURIComponent(id)}`
      closeTab(path)
      if (loc.pathname === path) nav(`/p/${encodeURIComponent(projectRef)}`)
      setPendingDel(null)
    } catch (e) {
      setDelErr(errorMessage(e))
    } finally {
      setDelBusy(false)
    }
  }

  /** 当前节点挂载的**所有**白板（按修改时间新→旧；一个节点可以有多块） */
  const boards = curVid != null ? (items ?? []).filter((it) => it.vid === curVid) : []

  return (
    <div style={{ padding: 12 }}>
      {/* ★★ 只显示**当前选中节点**挂载的白板（所有者：「点了哪个节点，就显示挂载这个节点上的白板」）⚠
          一个节点可以有多块：右上角「新建白板」创建，点某一块打开编辑，跟笔记一样 */}
      <div>
        <div className="faint" style={{ fontSize: 11, marginBottom: 6 }}>
          这个节点上的白板
        </div>
        {curVid == null ? (
          <Hint>先在节点列表里选中一个节点</Hint>
        ) : items === null ? null : boards.length === 0 ? (
          <Hint>这个节点还没有白板，点右上角「新建白板」</Hint>
        ) : (
          boards.map((it, i) => (
            <div
              key={it.id}
              style={{
                padding: '7px 8px',
                marginBottom: 4,
                border: '1px solid var(--card-border)',
                borderRadius: 6,
              }}
            >
              <button
                type="button"
                title={it.qname || it.name || it.id}
                onClick={() => onOpen(it.id, it.name)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: 0,
                  border: 0,
                  background: 'transparent',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>
                  {it.name || `白板 ${boards.length - i}`}
                </div>
                <div className="faint" style={{ fontSize: 11 }}>
                  {it.mtime ? `保存于 ${new Date(it.mtime * 1000).toLocaleString()}` : '空白白板'}
                </div>
              </button>
              {/* ★ 和笔记卡片同款：一行细线文字操作按钮（Trash2 + 删除），靠右下角 */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 6 }}>
                <button
                  type="button"
                  className="flex items-center gap-1"
                  style={{
                    color: 'var(--text-sub)',
                    cursor: 'pointer',
                    border: 0,
                    background: 'transparent',
                    fontSize: 11,
                    padding: 0,
                  }}
                  onClick={() => {
                    setDelErr('')
                    setPendingDel(it)
                  }}
                >
                  <Trash2 size={11} />
                  删除
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* ★ 和笔记同一个确认框（删除笔记 / 删除白板同款） */}
      <ConfirmDialog
        open={!!pendingDel}
        title="删除白板"
        danger
        loading={delBusy}
        error={delErr}
        confirmText="删除"
        message={
          pendingDel
            ? `删除「${pendingDel.name || '（未命名）'}」？\n删除后不可恢复。`
            : ''
        }
        onConfirm={() => void confirmDelete()}
        onCancel={() => {
          setPendingDel(null)
          setDelErr('')
        }}
      />
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
