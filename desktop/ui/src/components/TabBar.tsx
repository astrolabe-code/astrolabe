/**
 * ★★★ **文件选项卡（标签栏）**（2026-11-08，模仿 Obsidian）
 *
 * 所有者：「现在来模仿 obsidian，做这个文件选项吧，新建笔记的按钮就移到在旁边」
 * 所有者（2026-11-12）：「让笔记和白板都有真实路由……标签栏只按 URL」
 *
 * ★ 唯一数据源：`tabBus` 里访问过的 **pathname**。
 *   笔记、白板、页面都各有真实路由 ⇒ 打开什么就导航到什么，标签自动出现；
 *   ⛔ 不再有虚拟标签、不再订阅覆盖层状态（那套双轨机制已删）。
 *
 * ⚠ 标签栏空白处继承 .app-titlebar 的 drag（可以拖窗口），
 *   只有按钮设 no-drag（见 components.css），否则点不动。
 */

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ChevronDown, Plus, X } from 'lucide-react'

import { closeTab, openTab, subscribeTabs, tabs } from '../lib/tabBus'
import { ribbonActions } from '../lib/ribbonBus'

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

export default function TabBar() {
  const location = useLocation()
  const nav = useNavigate()
  const list = useSyncExternalStore(subscribeTabs, tabs, tabs)
  const [menu, setMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // ★ 每次路由变化：打开（或更新）对应标签。用 pathname 作 key
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

  // ★ 新建笔记：一律走真实路由并带上「当前 / 最近选中节点」
  //   ⚠ 不用 ribbon 的 createNote 回调：它由 NoteSection 注册，在笔记页/白板页
  //      会随组件卸载被清掉，那时兜底路径不带 ?node= ⇒ 新建页报「缺少节点信息」
  const canCreate = !!projectRef
  const createNote = () => {
    if (!projectRef) return
    const vid = ribbonActions().currentNodeVid
    const q = vid != null ? `?node=${vid}` : ''
    nav(`/p/${projectRef}/notes/new${q}`)
  }

  const close = (path: string) => {
    const next = closeTab(path)
    setMenu(false)
    if (path === currentPath) nav(next)
  }

  return (
    <div
      className="app-tabs"
      style={{ display: 'flex', alignItems: 'center', flex: 1, minWidth: 0, height: '100%' }}
    >
      <div
        className="app-tabs-scroll"
        style={{ display: 'flex', alignItems: 'center', minWidth: 0, flex: '0 1 auto', height: '100%' }}
      >
        {list.map((t) => {
          const active = t.path === currentPath
          return (
            <div
              key={t.path}
              className={`app-tab${active ? ' active' : ''}`}
              title={t.title}
            >
              <button
                type="button"
                className="app-tab-label"
                onClick={() => nav(t.path)}
                onDoubleClick={(e) => e.stopPropagation()}
              >
                {t.title}
              </button>
              <button
                type="button"
                className="app-tab-close"
                title={`关闭 ${t.title}`}
                aria-label={`关闭 ${t.title}`}
                onClick={() => close(t.path)}
                onDoubleClick={(e) => e.stopPropagation()}
              >
                <X size={11} strokeWidth={1.6} />
              </button>
            </div>
          )
        })}
      </div>

      <IconButton
        label={canCreate ? '新建笔记' : '先打开一个项目才能写笔记'}
        onClick={canCreate ? createNote : () => {}}
      >
        <Plus size={14} strokeWidth={1.6} />
      </IconButton>

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
            {list.length === 0 && (
              <div className="faint" style={{ padding: 8, fontSize: 12 }}>还没有打开的标签</div>
            )}
            {list.map((t) => (
              <div
                key={t.path}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  borderRadius: 5,
                  background: t.path === currentPath ? 'rgba(37,99,235,.08)' : 'transparent',
                }}
              >
                <button
                  type="button"
                  onClick={() => {
                    nav(t.path)
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
                    color: t.path === currentPath ? 'var(--accent)' : 'var(--text-main)',
                    fontSize: 12,
                    textAlign: 'left',
                    cursor: 'pointer',
                  }}
                >
                  {t.title}
                </button>
                <button
                  type="button"
                  title="关闭标签"
                  aria-label="关闭标签"
                  onClick={() => close(t.path)}
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

      <div style={{ flex: 1, minWidth: 0, height: '100%' }} />
    </div>
  )
}
