import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

import TopbarSlot from './TopbarSlot'

/**
 * ★★★ **页面顶栏工具条**（2026-11-05 抽成组件）⚠
 *
 * 所有者：「为所有页面都加上这个栏板吧，做成一个组件，方便统一替换」
 *
 * ## 用法
 *
 * ```tsx
 * <PageBar>
 *   <RailButton icon={<List size={13} />} label="列表" onClick={...} />
 *   <RailMenu label="工具" icon={<SlidersHorizontal size={13} />}>
 *     <Button onClick={...}>依赖线</Button>
 *   </RailMenu>
 * </PageBar>
 * ```
 *
 * ## 三条设计约束（都是踩过坑才定下来的）
 *
 * ```
 * ① 挂在**右上角**（portal，见 PersonalBar 的 page-tools-slot 插槽）
 *    ⛔ 不挂左栏：左栏 ribbon 要全局固定、每个界面图标数一致
 *    （所有者：「左栏的按钮，在每个界面的数量都不一样…
 *      与页面强烈相关的就放到右上角」）
 * ② 扁平图标按钮：透明底 / 无边框 / 无阴影，悬停才出现浅底
 *    ⛔ 不用胶囊 + 阴影（所有者：「样子怪不说，还挡住了后面的字」）
 *    .page-tools-slot 会隐藏文字只留图标
 * ③ 下拉菜单：点外面 / Esc 关闭，⛔ 不用 mouseleave
 *    （菜单与按钮之间有 6px 视觉缝，mouseleave 会被那块空隙误触发 ⇒ 菜单"一碰就消失"）
 * ```
 */

export function PageBar({ children, slotId }: { children: ReactNode; slotId?: string }) {
  return (
    <TopbarSlot targetId={slotId}>
      <div className="graph-toolbar">
        {/* ★★★ 必须包成**一个组** ⚠
            `.graph-toolbar` 早先是 space-between（左组工具 + 右组搜索）；
            改成公共组件后搜索已归 PersonalBar，若子项直接散在容器里，
            每个按钮都会成为 space-between 的一项 ⇒ 被均匀摊到整行
            （所有者：「各个按钮之间怎么分的这么宽？」）*/}
        <div className="rail-group">{children}</div>
      </div>
    </TopbarSlot>
  )
}

interface RailButtonProps {
  icon?: ReactNode
  /** 文字（窄屏由 CSS 自动隐藏，只留图标）*/
  label?: string
  title?: string
  /** 开关类按钮：开启态只改文字颜色 */
  active?: boolean
  onClick?: () => void
}

export function RailButton({ icon, label, title, active, onClick }: RailButtonProps) {
  return (
    <button
      type="button"
      className="rail-btn"
      aria-pressed={active}
      onClick={onClick}
      title={title || label}
    >
      {icon}
      {label && <span className="rail-label">{label}</span>}
    </button>
  )
}

interface RailMenuProps {
  label: string
  title?: string
  icon?: ReactNode
  children: ReactNode
}

/** 「工具▾」这类下拉：自己管开合（点外面 / Esc 关闭）*/
export function RailMenu({ label, title, icon, children }: RailMenuProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={ref} style={{ position: 'relative', display: 'flex' }}>
      <RailButton
        icon={icon}
        label={label}
        title={title || label}
        active={open}
        onClick={() => setOpen((v) => !v)}
      />
      {open && <div className="rail-menu">{children}</div>}
    </div>
  )
}

/** 菜单里的分隔线（导出成组件，页面不用再写 `<span className="rail-menu-sep" />`）*/
export function RailMenuSep() {
  return <span className="rail-menu-sep" />
}
