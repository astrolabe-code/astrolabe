import { useSyncExternalStore, useState, type ReactNode } from 'react'
import {
  Copy,
  FolderOpen,
  Lightbulb,
  Maximize,
  MoreHorizontal,
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

interface DesktopApi {
  openDataDir?: () => Promise<boolean>
}

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
  const api = (window as unknown as { astrolabe?: DesktopApi }).astrolabe
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
      {/* ★ 写笔记已移到标签栏的 ＋ 按钮（所有者：「新建笔记的按钮就移到在旁边」）
          ⇒ 左栏只保留全局固定图标，不随页面变化 */}
      {/* ★ 设置从「左栏最底部」挪到上方图标组 —— 之前被 flex:1 推到窗口底端，
          所有者截图只截到顶部 280px 找不到它：「左栏的设置按钮在哪里？」 */}
      <Item
        icon={<Settings size={ICON} strokeWidth={1.5} />}
        label="设置"
        onClick={() => {
          setMenu(false)
          nav(projectRef ? `/p/${encodeURIComponent(projectRef)}/settings` : '/me/settings')
        }}
      />
      {/* ★ 原「工具」下拉里的全局动作，拆成常驻图标（浏览器里没有该 API ⇒ 不渲染） */}
      {api?.openDataDir && (
        <Item
          icon={<FolderOpen size={ICON} strokeWidth={1.5} />}
          label="打开数据目录"
          onClick={() => void api.openDataDir?.()}
        />
      )}

      {/* ★★ 左栏只放**全局固定**图标 ⛔
          所有者：「左栏的按钮，在每个界面的数量都不一样。要借鉴一下 obsidian，
                  做成一样的呀。与页面强烈相关的就放到右上角」
          ⇒ 页面级 <PageBar> 不再 portal 到这里，改挂顶栏右侧 #page-tools-slot */}
      <div style={{ flex: 1 }} />
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
