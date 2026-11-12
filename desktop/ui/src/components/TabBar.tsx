/**
 * ★★★ **文件选项卡（标签栏）**（2026-11-08，模仿 Obsidian）
 *
 * 所有者：「现在来模仿 obsidian，做这个文件选项吧，新建笔记的按钮就移到在旁边」
 * 所有者（2026-11-12）：「打开了什么页面，某篇笔记，或白板之类的，都要显示」
 *
 * 顶栏布局：
 * ```
 * [▣] [标签1 ×][标签2][标签3] …  [＋ 新建笔记][∨ 标签列表] ··· [页面工具][— □ ×]
 * ```
 *
 * ★ 两类标签：
 *   · **路由标签**：访问过的 pathname（首页 / 项目 / 图谱 / 设置 / 独立笔记页），来自 tabBus
 *   · **虚拟标签**：白板与工作区内嵌笔记都是**覆盖层**，不改变 URL ⇒
 *     从 ribbonBus（当前白板）/ notePaneBus（当前笔记）动态派生，关掉视图标签就没了
 *
 * ⚠ 标签栏空白处继承 .app-titlebar 的 drag（可以拖窗口），
 *   只有按钮设 no-drag（见 components.css），否则点不动。
 * ⚠ 标签是**会话内**的，刷新不持久化（当前页会由 useLocation 自动重新打开）。
 */

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ChevronDown, FileText, LayoutDashboard, Plus, X } from 'lucide-react'

import { closeTab, openTab, subscribeTabs, tabs } from '../lib/tabBus'
import { ribbonActions, subscribeRibbon } from '../lib/ribbonBus'
import {
  closeNotePane,
  notePaneTitle,
  notePaneView,
  subscribeNotePane,
  subscribeNotePaneTitle,
} from '../lib/notePaneBus'

const BTN = 26

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: ReactNode
}) {
  const [hover, setHover] = useState(false)
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      onDoubleClick={(e) => e.stopPropagation()}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'grid',
        placeItems: 'center',
        width: BTN,
        height: BTN,
        flexShrink: 0,
        padding: 0,
        border: 0,
        borderRadius: 5,
        background: hover ? 'rgba(15,23,42,.07)' : 'transparent',
        color: 'var(--text-sub, #6b7280)',
        cursor: 'pointer',
      }}
    >
      {children}
    </button>
  )
}

/** 统一的一行标签：路由标签走 nav，虚拟标签走各自的关闭 / 激活动作 */
interface Row {
  key: string
  title: string
  icon?: ReactNode
  active: boolean
  onOpen: () => void
  onClose: () => void
}

export default function TabBar() {
  const location = useLocation()
  const nav = useNavigate()
  const routeTabs = useSyncExternalStore(subscribeTabs, tabs, tabs)
  const rib = useSyncExternalStore(subscribeRibbon, ribbonActions, ribbonActions)
  const pane = useSyncExternalStore(subscribeNotePane, notePaneView, notePaneView)
  const paneTitle = useSyncExternalStore(subscribeNotePaneTitle, notePaneTitle, notePaneTitle)
  const [menu, setMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // ★ 每次路由变化：打开（或更新）对应标签。用 pathname 作 key，
  //   同一篇笔记换 ?node= / ?parent= 不会开出第二个标签。
  useEffect(() => {
    openTab(location.pathname)
  }, [location.pathname])

  useEffect(() => {
    if (!menu) return
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenu(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenu(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menu])

  const currentPath = location.pathname
  const m = currentPath.match(/\/p\/([^/]+)/)
  const projectRef = m ? m[1] : ''

  // ★ 新建笔记：优先用当前笔记区注册的 createNote（带节点上下文），
  //   否则按当前项目直接进编辑器；首页没有项目 ⇒ 按钮禁用（不做假按钮）
  const canCreate = !!ribbonActions().createNote || !!projectRef
  const createNote = () => {
    const fn = ribbonActions().createNote
    if (fn) {
      fn()
      return
    }
    if (projectRef) nav(`/p/${projectRef}/notes/new`)
  }

  // ★★ 虚拟标签：当前打开的白板 / 内嵌笔记（都是覆盖层，不改 URL）
  const viewRows: Row[] = []
  if (rib.activeBoardKey) {
    viewRows.push({
      key: rib.activeBoardKey,
      title: rib.activeBoardTitle || '白板',
      icon: <LayoutDashboard size={11} strokeWidth={1.6} />,
      active: true,
      // 白板就是这个标签派生出来的，本来已经开着
      onOpen: () => {},
      onClose: () => rib.closeThinking?.(),
    })
  }
  if (pane) {
    viewRows.push({
      key: `note:${pane.ref ?? 'new'}`,
      title: paneTitle || (pane.ref ? '笔记' : '新笔记'),
      icon: <FileText size={11} strokeWidth={1.6} />,
      active: !rib.activeBoardKey,
      // 白板盖在最上层 ⇒ 点笔记标签就把白板收掉，露出笔记
      onOpen: () => rib.closeThinking?.(),
      onClose: () => closeNotePane(),
    })
  }
  const hasView = viewRows.length > 0

  const rows: Row[] = [
    ...routeTabs.map((t) => ({
      key: t.path,
      title: t.title,
      active: !hasView && t.path === currentPath,
      onOpen: () => {
        // 切回页面标签时，先把覆盖层视图收掉（否则白板还盖着）
        if (hasView) {
          rib.closeThinking?.()
          closeNotePane()
        }
        nav(t.path)
      },
      onClose: () => {
        const next = closeTab(t.path)
        setMenu(false)
        if (!hasView && t.path === currentPath) nav(next)
      },
    })),
    ...viewRows,
  ]

  return (
    <div
      className="app-tabs"
      style={{ display: 'flex', alignItems: 'center', flex: 1, minWidth: 0, height: '100%' }}
    >
      {/* ★ flex:0 1 auto ⇒ ＋/∨ 紧跟最后一个标签（Obsidian 口径），
          空白留给右侧的拖动区，不会被推到最右端 */}
      <div
        className="app-tabs-scroll"
        style={{ display: 'flex', alignItems: 'center', minWidth: 0, flex: '0 1 auto', height: '100%' }}
      >
        {rows.map((r) => (
          <div
            key={r.key}
            className={`app-tab${r.active ? ' active' : ''}`}
            title={r.title}
          >
            <button
              type="button"
              className="app-tab-label"
              onClick={r.onOpen}
              onDoubleClick={(e) => e.stopPropagation()}
            >
              {r.icon && (
                <span style={{ display: 'inline-flex', marginRight: 4, opacity: 0.7 }}>
                  {r.icon}
                </span>
              )}
              {r.title}
            </button>
            <button
              type="button"
              className="app-tab-close"
              title={`关闭 ${r.title}`}
              aria-label={`关闭 ${r.title}`}
              onClick={() => {
                r.onClose()
                setMenu(false)
              }}
              onDoubleClick={(e) => e.stopPropagation()}
            >
              <X size={11} strokeWidth={1.6} />
            </button>
          </div>
        ))}
      </div>

      {/* ★ 新建笔记按钮：从左栏 ribbon 移到标签旁边（所有者要求） */}
      <IconButton
        label={canCreate ? '新建笔记' : '先打开一个项目才能写笔记'}
        onClick={canCreate ? createNote : () => {}}
      >
        <Plus size={14} strokeWidth={1.6} />
      </IconButton>

      {/* ★ ∨ 标签列表：标签多到横向滚动时，从这里快速跳转 / 关闭 */}
      <div ref={menuRef} style={{ position: 'relative', flexShrink: 0 }}>
        <IconButton label="标签列表" onClick={() => setMenu((v) => !v)}>
          <ChevronDown size={14} strokeWidth={1.6} />
        </IconButton>
        {menu && (
          <div
            className="card"
            style={{
              position: 'absolute',
              top: 32,
              right: 0,
              width: 230,
              maxHeight: 320,
              overflowY: 'auto',
              padding: 6,
              boxShadow: '0 10px 30px rgba(15,23,42,.16)',
              zIndex: 120,
            }}
          >
            {rows.length === 0 && (
              <div className="faint" style={{ padding: 8, fontSize: 12 }}>还没有打开的标签</div>
            )}
            {rows.map((r) => (
              <div
                key={r.key}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  borderRadius: 5,
                  background: r.active ? 'rgba(37,99,235,.08)' : 'transparent',
                }}
              >
                <button
                  type="button"
                  onClick={() => {
                    r.onOpen()
                    setMenu(false)
                  }}
                  style={{
                    flex: 1,
                    minWidth: 0,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    padding: '6px 8px',
                    border: 0,
                    borderRadius: 5,
                    background: 'transparent',
                    color: r.active ? 'var(--accent)' : 'var(--text-main)',
                    fontSize: 12,
                    textAlign: 'left',
                    cursor: 'pointer',
                  }}
                >
                  {r.icon && (
                    <span style={{ display: 'inline-flex', marginRight: 5, opacity: 0.7 }}>
                      {r.icon}
                    </span>
                  )}
                  {r.title}
                </button>
                <button
                  type="button"
                  title="关闭标签"
                  aria-label="关闭标签"
                  onClick={() => {
                    r.onClose()
                    setMenu(false)
                  }}
                  style={{
                    display: 'grid',
                    placeItems: 'center',
                    width: 22,
                    height: 22,
                    flexShrink: 0,
                    border: 0,
                    background: 'transparent',
                    color: 'var(--text-faint)',
                    cursor: 'pointer',
                  }}
                >
                  <X size={11} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ★ 标签与按钮右侧的空白继承 drag，仍可拖动窗口 */}
      <div style={{ flex: 1, minWidth: 0, height: '100%' }} />
    </div>
  )
}
