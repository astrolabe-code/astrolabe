import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import {
  Copy,
  Maximize,
  Minimize,
  PanelLeft,
  SquareChevronDown,
  X,
} from 'lucide-react'

import type { FileTreeData, SourceFile } from '../../api/code'
import { personalApi } from '../../api/personal'
import type { GraphNode } from '../../lib/mergeGraph'
import NodePanel from '../node/NodePanel'
import NodeHeading from '../node/NodeHeading'
import ImitationPanel from './ImitationPanel'
import FileTree, { firstLevelDirs } from './FileTree'
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
}

type Tab = 'code' | 'imitation' | 'notes'

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
}: CodeWorkspaceProps) {
  const [tab, setTab] = useState<Tab>(initialTab)
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

  const copy = () => {
    if (!source) return
    void navigator.clipboard.writeText(source.text).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }

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
              <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                {source && (
                  <>
                    <span
                      className="faint"
                      style={{ fontSize: 11.5, whiteSpace: 'nowrap', marginRight: 4 }}
                    >
                      {source.lang || '文本'} · {source.lines} 行
                    </span>
                    <IconBtn title="复制全部代码" onClick={copy}>
                      <Copy size={14} strokeWidth={1.5} />
                      {copied ? '已复制' : ''}
                    </IconBtn>
                  </>
                )}
                <IconBtn
                  title={treeOpen ? '收起文件树' : '展开文件树'}
                  onClick={toggleTree}
                  active={treeOpen}
                >
                  <PanelLeft size={16} strokeWidth={1.5} />
                </IconBtn>
                <IconBtn title="沉浸（隐藏标签页）" onClick={() => setImmersive(true)}>
                  <SquareChevronDown size={16} strokeWidth={1.5} />
                </IconBtn>
                <IconBtn
                  title={fullscreen ? '退出全屏' : '全屏'}
                  onClick={() => setFullscreen((v) => !v)}
                  active={fullscreen}
                >
                  {fullscreen ? (
                    <Minimize size={16} strokeWidth={1.5} />
                  ) : (
                    <Maximize size={16} strokeWidth={1.5} />
                  )}
                </IconBtn>
                {onClose && (
                  <IconBtn title="关闭代码窗口" onClick={onClose}>
                    <X size={16} strokeWidth={1.5} />
                  </IconBtn>
                )}
              </div>
            }
          />
        </div>
      )}

      {/* ★ tab：代码 / 笔记（蓝色下划线选中态） */}
      {!immersive && (
        <div className="code-tabs">
          {(['code', 'imitation', 'notes'] as const).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => {
                setTab(k)
                setTreeOpen(k === 'code')
              }}
              className={`code-tab${tab === k ? ' is-active' : ''}`}
            >
              {k === 'code' ? '代码' : k === 'imitation' ? '仿写' : '笔记'}
            </button>
          ))}
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {/* ★★ 文件树只由 treeOpen 决定：切到笔记时由 tab 按钮把它收起，
            右上角的按钮常驻，用户想看随时点开（⛔ 渲染处不加 tab 判断） */}
        {treeOpen && (
          <div
            style={{
              width: 240,
              flex: 'none',
              borderRight: '1px solid var(--card-border)',
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
        )}

        {/* 右侧：代码页 / 笔记页 */}
        <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          {tab === 'notes' ? (
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
          ) : tab === 'imitation' ? (
            <ImitationPanel projectRef={projectRef} node={node} />
          ) : (
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
          )}
        </div>
      </div>
    </div>
  )
}
