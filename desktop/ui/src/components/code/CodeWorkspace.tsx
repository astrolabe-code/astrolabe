import { useCallback, useEffect, useId, useState, type CSSProperties, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { PanelLeft, X } from 'lucide-react'

import type { FileTreeData, SourceFile } from '../../api/code'
import { personalApi } from '../../api/personal'
import { patchRibbon, clearRibbon, ribbonActions } from '../../lib/ribbonBus'
import { openTab } from '../../lib/tabBus'
import type { GraphNode } from '../../lib/mergeGraph'
import { useNotes } from '../../query/notes'
import NoteEditPage from '../../pages/NoteEditPage'
import ThinkingBoard from '../notes/ThinkingBoard'
import NodePanel from '../node/NodePanel'
import NodeHeading from '../node/NodeHeading'
import ImitationPanel from './ImitationPanel'
import FileTree, { firstLevelDirs } from './FileTree'
import SplitPane from '../SplitPane'
import CodeViewer from './CodeViewer'

interface CodeWorkspaceProps {
  projectRef: string
  /** 当前选中的节点：决定笔记页显示谁、代码页跳到哪一行 */
  node: GraphNode | null
  /** ★ 只有"大窗口"传（点 × 关掉回原页面）；右栏常驻面板不传 */
  onClose?: () => void
  /** ★ 起始 tab：大窗口默认看代码，右栏默认停在笔记（右栏本来就是写笔记的地方） */
  initialTab?: Tab
  /** ★ 笔记页内容：调用方可贴自己的 NodePanel（右栏要保留学习路径等能力） */
  notePanel?: ReactNode
  /** ★ URL 指定要在这个框里显示的笔记（阅读 / 编辑 / 新建）；不传则显示笔记列表 */
  noteView?: {
    mode: 'read' | 'edit'
    ref: string | null
    nodeId: number
    parent?: string
  }
  /** ★ URL 指定要在这个框里显示的白板（挂在节点上的特殊笔记） */
  boardView?: {
    boardId: string
    nodeId: number
    focus?: string
  }
}

/** ★ 5 个视图：代码 / 笔记列表 / 阅读（笔记内容） / 白板 / 仿写 */
type Tab = 'code' | 'notes' | 'read' | 'board' | 'imitation'

const TABS: { key: Tab; label: string }[] = [
  { key: 'code', label: '代码' },
  { key: 'notes', label: '笔记' },
  { key: 'read', label: '阅读' },
  { key: 'board', label: '白板' },
  { key: 'imitation', label: '仿写' },
]

const TREE_OPEN_KEY = 'astrolabe.code.treeOpen'

interface IconBtnProps {
  title: string
  onClick: () => void
  active?: boolean
  children: ReactNode
}

/** ★ 右上角三枚同规格细线图标：⛔ 无背景 / 无边框 / 无圆形底板 / 无阴影 */
function IconBtn({ title, onClick, active, children }: IconBtnProps) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={active}
      onClick={onClick}
      className="code-icon-btn"
      style={{ color: active ? 'var(--accent, #2563eb)' : 'var(--text-sub, #6b7280)' }}
    >
      {children}
    </button>
  )
}

/**
 * ★★★ **代码工作区**（2026-11-06）
 *
 * 所有者给的样式要点（逐条落实，⛔ 不照抄其余装饰）：
 * ```
 * ✅ tab 切换（代码 / 笔记，蓝色下划线选中态）
 * ✅ 左侧可折叠文件树 | 右侧内容
 * ✅ 右上角三枚同款细线图标：文件树收起 / 沉浸 / 全屏
 * ✅ 沉浸 = 隐藏标题行 + tab 行，右上角「退出沉浸」
 * ⛔ 不抄：紫色圆点、「启动」胶囊、黄色 Failed to fetch 条、评论 tab、文件名截断
 * ```
 *
 * 文件树**全部显示**（⛔ 不按 .gitignore 过滤）；读文件仍受
 * sidecar/source.py 的三条边界约束（项目根内 / UTF-8 / ≤512KB）。
 */
export default function CodeWorkspace({
  projectRef,
  node,
  onClose,
  initialTab = 'code',
  notePanel,
  noteView,
  boardView,
}: CodeWorkspaceProps) {
  const [tab, setTab] = useState<Tab>(initialTab)
  // ★ 每个工作区实例一个唯一工具插槽 id（图谱页/项目页各有多个 CodeWorkspace，
  //   固定 id 会让 document.getElementById 拿到错的那个）
  const toolsSlotId = `note-pane-tools-${useId().replace(/:/g, '')}`
  // ★★ 笔记有真实路由，但内容仍在这个框里显示：URL 决定显示哪篇，
  //   ⛔ 不再有 notePaneBus 那套双轨状态（导航就是唯一状态源）
  const nav = useNavigate()
  // ★ 白板里的卡片就是笔记，用和笔记列表同一份数据
  const notesQ = useNotes(projectRef)

  // ★★ URL 决定「阅读 / 白板」两个视图：打开笔记或白板时自动切到对应 tab
  useEffect(() => {
    if (noteView) setTab('read')
    else if (boardView) setTab('board')
  }, [noteView?.ref, noteView?.mode, boardView?.boardId])

  const hasNoteView = !!noteView
  const hasBoardView = !!boardView

  // ★★ 「阅读」tab：URL 没指定笔记时，自动打开**当前选中节点的第一篇笔记**；
  //   这个节点没有笔记 ⇒ 阅读页留空（⛔ 不回退到笔记列表）
  useEffect(() => {
    if (tab !== 'read' || hasNoteView || !notesQ.data) return
    const vid = node?.vid ?? ribbonActions().currentNodeVid
    if (vid == null) return
    const first = notesQ.data.find((n) => n.node_id === vid)
    if (!first) {
      // 还停在白板路由就回项目页，保持 URL 与空白阅读页一致
      if (hasBoardView) nav(`/p/${encodeURIComponent(projectRef)}`)
      return
    }
    const path = `/p/${encodeURIComponent(projectRef)}/notes/${first.ref}`
    openTab(path, first.title || '笔记')
    nav(path)
  }, [tab, hasNoteView, hasBoardView, notesQ.data, node?.vid, projectRef, nav])

  /** ★ 点 tab：需要内容的两个视图走真实路由，其余回到项目页 */
  const pickTab = (k: Tab) => {
    if (k === 'board' && !boardView) {
      // 当前节点的默认白板（每个节点最早那块），没有也能直接建
      const vid = node?.vid ?? ribbonActions().currentNodeVid ?? 0
      nav(`/p/${encodeURIComponent(projectRef)}/board/${vid}?node=${vid}`)
      setTab('board')
      return
    }
    if (k === 'read' && !noteView) {
      // 上面的 effect 会打开第一篇笔记（或留空），这里只切 tab
      setTab('read')
      setTreeOpen(false)
      return
    }
    const stayOnUrl = (k === 'read' && !!noteView) || (k === 'board' && !!boardView)
    if (!stayOnUrl && (noteView || boardView)) {
      nav(`/p/${encodeURIComponent(projectRef)}`)
    }
    setTab(k)
    setTreeOpen(k === 'code')
  }

  // 笔记列表（notes / 白板未指定时共用；阅读没笔记是空白，不共用）
  const listPane = (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {notePanel ?? <NodePanel projectRef={projectRef} node={node} canWrite flat hideInfo />}
    </div>
  )
  const [treeOpen, setTreeOpen] = useState(() => {
    // ★ 文件树跟着「代码」页走：初始停在笔记就不显示
    if (initialTab === 'notes') return false
    try {
      return localStorage.getItem(TREE_OPEN_KEY) !== '0'
    } catch {
      return true
    }
  })
  const [immersive, setImmersive] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)

  const [tree, setTree] = useState<FileTreeData | null>(null)
  const [treeError, setTreeError] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [activePath, setActivePath] = useState('')
  const [source, setSource] = useState<SourceFile | null>(null)
  const [sourceError, setSourceError] = useState('')
  const [loading, setLoading] = useState(false)
  const [focusLineNo, setFocusLineNo] = useState<number | null>(null)
  const [copied, setCopied] = useState(false)

  // ① 文件树
  useEffect(() => {
    let alive = true
    personalApi
      .fileTree(projectRef)
      .then((d) => {
        if (!alive) return
        setTree(d)
        setExpanded(firstLevelDirs(d.items))
        setTreeError('')
      })
      .catch((e: Error) => alive && setTreeError(e.message || '列文件树失败'))
    return () => {
      alive = false
    }
  }, [projectRef])

  // ② 点节点 ⇒ 自动打开对应文件并跳到那一行
  useEffect(() => {
    if (!node?.file_path) return
    setActivePath(node.file_path)
    setFocusLineNo(node.line > 0 ? node.line : null)
  }, [node?.file_path, node?.line, node?.vid])

  // ③ 读文件内容
  useEffect(() => {
    if (!activePath) return
    let alive = true
    setLoading(true)
    setSourceError('')
    personalApi
      .readSource(projectRef, activePath)
      .then((d) => {
        if (!alive) return
        setSource(d)
        setSourceError('')
      })
      .catch((e: Error) => {
        if (!alive) return
        setSource(null)
        setSourceError(e.message || '读取失败')
      })
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [projectRef, activePath])

  const toggleTree = useCallback(() => {
    setTreeOpen((v) => {
      const next = !v
      try {
        localStorage.setItem(TREE_OPEN_KEY, next ? '1' : '0')
      } catch {
        /* 存不了就用默认值 */
      }
      return next
    })
  }, [])

  const toggleDir = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }, [])

  const pickFile = useCallback((path: string) => {
    setActivePath(path)
    setFocusLineNo(null)
    setTab('code')
  }, [])

  // Esc：先退出全屏，再退出沉浸（⛔ 不直接关面板，避免误关）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (fullscreen) setFullscreen(false)
      else if (immersive) setImmersive(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [fullscreen, immersive])

  const copy = useCallback(() => {
    if (!source) return
    void navigator.clipboard.writeText(source.text).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }, [source])

  // ★★ 把本工作区能做的事注册给全局 ribbon（Obsidian 口径：按钮不在内容区）
  useEffect(() => {
    patchRibbon({
      projectRef,
      activePath,
      copy,
      toggleImmersive: () => setImmersive((v) => !v),
      toggleFullscreen: () => setFullscreen((v) => !v),
      openPath: pickFile,
    })
    return () =>
      clearRibbon([
        'copy',
        'toggleImmersive',
        'toggleFullscreen',
        'openPath',
      ])
  }, [projectRef, activePath, toggleTree, copy, pickFile])

  const shellStyle: CSSProperties = fullscreen
    ? {
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        background: 'var(--card, #fff)',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }
    : {
        display: 'flex',
        flexDirection: 'column',
        flex: 1,
        height: '100%',
        minHeight: 420,
        background: 'var(--card, #fff)',
      }

  return (
    <div style={shellStyle}>
      {immersive && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '6px 10px 0' }}>
          <button
            type="button"
            onClick={() => setImmersive(false)}
            className="faint"
            style={{
              fontSize: 11.5,
              padding: '3px 10px',
              border: '1px solid var(--card-border)',
              borderRadius: 999,
              background: 'transparent',
              cursor: 'pointer',
            }}
          >
            ∨ 退出沉浸
          </button>
        </div>
      )}

      {/* ★★★ 第一行：**节点头部（圆点 + 名称 + 类型 + 路径）** 在左，工具按钮在右；
          tab 行在它下面（所有者：「我叫你这样摆！」） */}
      {!immersive && (
        <div
          style={{
            flex: 'none',
            padding: '8px 12px',
            borderBottom: '1px solid var(--card-border)',
          }}
        >
          <NodeHeading
            node={node}
            trailing={
              onClose ? (
                <IconBtn title="关闭代码窗口" onClick={onClose}>
                  <X size={16} strokeWidth={1.5} />
                </IconBtn>
              ) : null
            }
          />
        </div>
      )}

      {/* ★ tab：代码 / 笔记 / 阅读 / 白板 / 仿写（蓝色下划线选中态） */}
      {!immersive && (
        <div className="code-tabs">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => pickTab(key)}
              className={`code-tab${tab === key ? ' is-active' : ''}`}
            >
              {label}
            </button>
          ))}
          {/* ★ 容器内嵌页面自己的工具条插槽（与外层顶栏工具分离） */}
          <div
            id={toolsSlotId}
            className="page-tools-slot"
            style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center' }}
          />
          {/* ★ 文件树开关：放**最右**（所有者：「我上一轮都给你指定在右边了」）⚠
              Ribbon 上那枚仍在；这枚停在任何页都能展开/收起左侧文件树 */}
          <IconBtn
            title={treeOpen ? '收起文件树' : '打开文件树'}
            active={treeOpen}
            onClick={toggleTree}
          >
            <PanelLeft size={16} strokeWidth={1.5} />
          </IconBtn>
        </div>
      )}

      {/* ★★ 2026-11-11：外层也改用 SplitPane ⇒ 与内层 note 页嵌套成三分页。
          · 文件树仍是 treeOpen 控制，但走 collapsed 接口（整块不渲染）
          · preserveChildStyle：文件树自己的 display:flex 列布局要保留 */}
      <SplitPane
        fixed="left"
        initial={240}
        min={180}
        otherMin={320}
        collapsed={!treeOpen}
        collapsedSide="left"
        preserveChildStyle
      >
        <div
          style={{
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
            {treeError ? (
              <div className="faint" style={{ padding: 12, fontSize: 12 }}>
                {treeError}
              </div>
            ) : !tree ? (
              <div className="faint" style={{ padding: 12, fontSize: 12 }}>
                正在读取文件树…
              </div>
            ) : (
              <FileTree
                items={tree.items}
                activePath={activePath}
                expanded={expanded}
                onToggle={toggleDir}
                onPick={pickFile}
              />
            )}
            {tree?.truncated && (
              <div className="faint" style={{ padding: '4px 10px', fontSize: 11 }}>
                文件太多，只显示了一部分
              </div>
            )}
        </div>

        {/* 右侧：代码页 / 笔记页 */}
        <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          {tab === 'code' ? (
            <>
              {loading ? (
                <div className="faint" style={{ padding: 20, fontSize: 12.5 }}>正在读取…</div>
              ) : sourceError ? (
                <div style={{ padding: 20, fontSize: 12.5, color: 'var(--text-sub)' }}>
                  {sourceError}
                </div>
              ) : source ? (
                <div style={{ flex: 1, minHeight: 0 }}>
                  <CodeViewer text={source.text} lang={source.lang} focus={focusLineNo} />
                </div>
              ) : (
                <div
                  className="faint"
                  style={{
                    flex: 1,
                    display: 'grid',
                    placeItems: 'center',
                    textAlign: 'center',
                    fontSize: 13,
                    lineHeight: 2,
                  }}
                >
                  点击左侧文件查看代码
                  <br />
                  <span style={{ fontSize: 11.5 }}>
                    从列表或图谱里选中节点再打开，会自动跳到它所在的那一行
                  </span>
                </div>
              )}
            </>
          ) : tab === 'imitation' ? (
            <ImitationPanel projectRef={projectRef} node={node} />
          ) : tab === 'read' ? (
            noteView ? (
              <NoteEditPage
                key={`${noteView.ref ?? 'new'}-${noteView.mode}`}
                projectRef={projectRef}
                noteRef={noteView.ref || undefined}
                nodeId={noteView.nodeId}
                parent={noteView.parent}
                initialMode={noteView.mode}
                onNavigate={(p) => nav(p)}
                toolsSlotId={toolsSlotId}
                onBackToList={() => nav(`/p/${encodeURIComponent(projectRef)}`)}
              />
            ) : (
              <div style={{ flex: 1, minHeight: 0 }} />
            )
          ) : tab === 'board' ? (
            boardView ? (
              <ThinkingBoard
                open
                projectRef={projectRef}
                nodeId={boardView.nodeId}
                boardId={boardView.boardId}
                notes={notesQ.data || []}
                focusCardId={boardView.focus}
                onClose={() => nav(`/p/${encodeURIComponent(projectRef)}`)}
              />
            ) : listPane
          ) : (
            listPane
          )}
        </div>
      </SplitPane>
    </div>
  )
}
