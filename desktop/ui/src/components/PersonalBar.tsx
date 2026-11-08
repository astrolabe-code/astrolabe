/**
 * ★★★ **自绘标题栏**（Obsidian 口径：整个窗口只有一行顶栏）
 *
 * 所有者：「主要是要合并成一行，自己绘制一个，还有把设置和搜索收进左栏」
 *
 * ```
 * [▣]  [页面工具 TopbarSlot] ······ 可拖动区 ······  [—] [□/❐] [×]
 * ```
 *
 * ⚠ 主进程 `frame:false` ⇒ 原生 — □ × 没有了，这三个由这里画，
 *   经 preload 的 win* 转发到主进程 IPC。浏览器里打开 ui/dist 时
 *   `window.astrolabe` 不存在 ⇒ 窗口按钮不渲染，不会报错。
 *
 * ⚠ 拖动区用 `-webkit-app-region: drag`（见 components.css），
 *   所有按钮 / 输入框必须 no-drag，否则点不动。
 * ⚠ 品牌名、设置、搜索都不再占这一行：品牌折成左端方块（回首页），
 *   设置与搜索收进左侧 Ribbon。
 */

import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Box, Copy, Minus, Square, X } from 'lucide-react'

interface DesktopApi {
  isDesktop?: boolean
  winMinimize?: () => Promise<boolean>
  winToggleMaximize?: () => Promise<boolean>
  winClose?: () => Promise<boolean>
  winIsMaximized?: () => Promise<boolean>
  onWinMaximized?: (cb: (value: boolean) => void) => () => void
}

/** 单个窗口控制按钮：46×40，关闭键 hover 变红 */
function WinButton({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: ReactNode
  label: string
  onClick: () => void
  danger?: boolean
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
        width: 46,
        height: 40,
        padding: 0,
        border: 0,
        borderRadius: 0,
        background: hover ? (danger ? '#e81123' : 'rgba(15,23,42,.07)') : 'transparent',
        color: hover && danger ? '#fff' : 'var(--text-sub, #6b7280)',
        cursor: 'pointer',
      }}
    >
      {icon}
    </button>
  )
}

export default function PersonalBar() {
  const nav = useNavigate()
  const api = (window as unknown as { astrolabe?: DesktopApi }).astrolabe
  const hasWinApi = !!api?.winClose
  const [maximized, setMaximized] = useState(false)

  useEffect(() => {
    if (!hasWinApi) return
    api?.winIsMaximized?.().then((v) => setMaximized(!!v)).catch(() => {})
    return api?.onWinMaximized?.(setMaximized)
  }, [api, hasWinApi])

  const toggleMaximize = () => {
    void api?.winToggleMaximize?.()
  }

  return (
    <div
      className="app-titlebar"
      style={{
        display: 'flex',
        alignItems: 'center',
        height: 40,
        padding: 0,
        borderBottom: '1px solid #eee',
        background: '#fff',
        fontFamily: 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
        flexShrink: 0,
      }}
    >
      {/* ★ 左端方块（借鉴 Obsidian 的工作区方块）：回首页 */}
      <button
        type="button"
        title="Astrolabe · 回到首页"
        aria-label="回到首页"
        onClick={() => nav('/')}
        onDoubleClick={(e) => e.stopPropagation()}
        style={{
          display: 'grid',
          placeItems: 'center',
          width: 40,
          height: 40,
          flexShrink: 0,
          padding: 0,
          border: 0,
          background: 'transparent',
          color: '#111',
          cursor: 'pointer',
        }}
      >
        <Box size={15} strokeWidth={1.6} />
      </button>

      {/* ★ 页面级工具条仍挂这一行（TopbarSlot portal） */}
      <div id="app-topbar-slot" className="topbar-slot" />

      {/* ★ 中间大片留白 = 系统拖动区（-webkit-app-region: drag）。
          ⚠ drag 区域不派发 JS 鼠标事件 ⇒ 这里不做「双击最大化」，
            最大化统一用右侧 □ 按钮（真能点） */}
      <div style={{ flex: 1, minWidth: 0, height: '100%' }} />

      {hasWinApi && (
        <div style={{ display: 'flex', flexShrink: 0 }}>
          <WinButton
            icon={<Minus size={14} strokeWidth={1.5} />}
            label="最小化"
            onClick={() => void api?.winMinimize?.()}
          />
          <WinButton
            icon={maximized ? <Copy size={12} strokeWidth={1.5} /> : <Square size={12} strokeWidth={1.5} />}
            label={maximized ? '向下还原' : '最大化'}
            onClick={toggleMaximize}
          />
          <WinButton
            icon={<X size={15} strokeWidth={1.5} />}
            label="关闭"
            danger
            onClick={() => void api?.winClose?.()}
          />
        </div>
      )}
    </div>
  )
}
