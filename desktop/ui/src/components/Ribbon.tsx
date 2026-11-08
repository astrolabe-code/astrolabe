import { useSyncExternalStore, useState, type ReactNode } from 'react'
import {
  Copy,
  Lightbulb,
  Maximize,
  MoreHorizontal,
  PanelLeft,
  Plus,
  Search,
  SquareChevronDown,
  Settings,
} from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

import {
  ribbonActions,
  subscribeRibbon,
  type PanelKind,
} from '../lib/ribbonBus'

interface RibbonProps {
  active: PanelKind | null
  onToggle: (kind: PanelKind) => void
}

const ICON = 16
const BTN = 30

/**
 * ★★★ **左侧 ribbon**（Obsidian 口径）
 *
 * 所有者：「做成obsidian一样的就行」——功能按钮不再摊在内容区顶部，
 * 收进这条 36px 细线图标竖栏；点图标展开功能面板，次要功能进 ⋮。
 */
export default function Ribbon({ active, onToggle }: RibbonProps) {
  const actions = useSyncExternalStore(subscribeRibbon, ribbonActions, ribbonActions)
  const [menu, setMenu] = useState(false)
  const nav = useNavigate()
  const location = useLocation()
  const m = location.pathname.match(/\/p\/([^/]+)/)
  const projectRef = m ? decodeURIComponent(m[1]) : ''

  const Item = ({
    icon,
    label,
    selected,
    onClick,
  }: {
    icon: ReactNode
    label: string
    selected?: boolean
    onClick: () => void
  }) => (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      style={{
        position: 'relative',
        display: 'grid',
        placeItems: 'center',
        width: BTN,
        height: BTN,
        margin: '2px auto',
        padding: 0,
        border: 0,
        borderRadius: 6,
        background: selected ? 'var(--accent-dim, rgba(37,99,235,.08))' : 'transparent',
        color: selected ? 'var(--accent, #2563eb)' : 'var(--text-sub, #6b7280)',
        cursor: 'pointer',
      }}
    >
      {icon}
      {selected && (
        <span
          style={{
            position: 'absolute',
            left: -3,
            top: 6,
            bottom: 6,
            width: 2,
            borderRadius: 2,
            background: 'var(--accent, #2563eb)',
          }}
        />
      )}
    </button>
  )

  const run = (fn?: () => void) => {
    setMenu(false)
    fn?.()
  }

  return (
    <div
      style={{
        position: 'relative',
        flexShrink: 0,
        width: 36,
        background: 'var(--card, #fff)',
        borderRight: '1px solid var(--card-border)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        paddingTop: 6,
        gap: 2,
        zIndex: 40,
      }}
    >
      {/* ★ 只留右边那棵文件树：这里只负责显示/隐藏，不再展开第二个树
          （所有者：「出现两个文件树吗？重复了，就留右边的就行」） */}
      <Item
        icon={<PanelLeft size={ICON} strokeWidth={1.5} />}
        label="显示 / 隐藏文件树"
        onClick={() => run(actions.toggleTree)}
      />
      <Item
        icon={<Search size={ICON} strokeWidth={1.5} />}
        label="搜索 · 打开功能面板"
        selected={active === 'search'}
        onClick={() => {
          setMenu(false)
          onToggle('search')
        }}
      />
      <Item
        icon={<Lightbulb size={ICON} strokeWidth={1.5} />}
        label="思考模式 · 打开功能面板"
        selected={active === 'thinking'}
        onClick={() => {
          setMenu(false)
          onToggle('thinking')
        }}
      />
      <Item
        icon={<Plus size={ICON} strokeWidth={1.5} />}
        label="写笔记"
        onClick={() => run(actions.createNote)}
      />
      <div style={{ flex: 1 }} />
      {/* ★ 设置 / 搜索从顶栏收进左栏（所有者：「合并成一行…把设置和搜索收进左栏」） */}
      <Item
        icon={<Settings size={ICON} strokeWidth={1.5} />}
        label="设置"
        onClick={() => {
          setMenu(false)
          nav(projectRef ? `/p/${encodeURIComponent(projectRef)}/settings` : '/me/settings')
        }}
      />
      <Item
        icon={<MoreHorizontal size={ICON} strokeWidth={1.5} />}
        label="更多功能"
        selected={menu}
        onClick={() => setMenu((v) => !v)}
      />

      {menu && (
        <div
          className="card"
          style={{
            position: 'absolute',
            left: 38,
            bottom: 8,
            width: 190,
            padding: 6,
            boxShadow: '0 10px 30px rgba(15,23,42,.16)',
            zIndex: 60,
          }}
        >
          {[
            { label: '复制当前代码', icon: <Copy size={14} />, fn: actions.copy },
            { label: '沉浸模式', icon: <SquareChevronDown size={14} />, fn: actions.toggleImmersive },
            { label: '代码窗口全屏', icon: <Maximize size={14} />, fn: actions.toggleFullscreen },
            {
              label: '图谱画布全屏',
              icon: <Maximize size={14} />,
              fn: actions.toggleCanvasFullscreen,
            },
            {
              // ★ 顶栏那个「搜索 Ctrl+K」按钮撤走后，全局搜索入口收进这里
              label: '全局搜索 Ctrl+K',
              icon: <Search size={14} />,
              fn: () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true })),
            },
          ].map((m) => (
            <button
              key={m.label}
              type="button"
              disabled={!m.fn}
              onClick={() => run(m.fn)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                width: '100%',
                padding: '6px 8px',
                border: 0,
                borderRadius: 6,
                background: 'transparent',
                color: m.fn ? 'var(--text-main)' : 'var(--text-faint)',
                fontSize: 12,
                textAlign: 'left',
                cursor: m.fn ? 'pointer' : 'not-allowed',
              }}
            >
              {m.icon}
              {m.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
