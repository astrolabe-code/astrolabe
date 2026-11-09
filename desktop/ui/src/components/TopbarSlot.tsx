import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** ★ 右上角页面工具插槽 DOM id（`PersonalBar` 里渲染这个空位）*/
export const PAGE_TOOLS_SLOT_ID = 'page-tools-slot'

/**
 * ★★★ **把页面级工具条挂到右上角**（2026-11-08 定稿）
 *
 * 所有者：「左栏的按钮，在每个界面的数量都不一样。要借鉴一下 obsidian，
 *          做成一样的呀。与页面强烈相关的就放到右上角」
 *
 * ⇒ ⛔ 不挂左栏 ribbon：那会让每个页面的左栏图标数量不同（图谱 6 个、
 *   笔记 1~2 个、设置 1 个），违背 Obsidian「左栏全局固定」的做法。
 * ⇒ ✅ 改挂顶栏右侧、窗口按钮左边，横排只显图标。
 *
 * ## 为什么用 portal
 *
 * ```
 * `PersonalBar` 在 App.tsx 里渲染，**在所有路由之外**
 * ⇒ 页面不能通过 props 把自己那一组按钮塞进去
 * ⇒ 顶栏留一个空 div（id=page-tools-slot），页面用 portal 挂进去 ✅
 * ```
 *
 * ⚠ 首帧拿不到节点，所以用 state + effect 再渲染一次。
 * ⚠ 页面卸载时 portal 自动移除（React 保证），不会残留上一页的按钮。
 */
export default function TopbarSlot({
  children,
  targetId,
}: {
  children: ReactNode
  /** ★ 容器内嵌的阅读/编辑页用「工作区自己的工具插槽」，避免和外层页面工具混在一起 */
  targetId?: string
}) {
  const [host, setHost] = useState<HTMLElement | null>(null)

  useEffect(() => {
    setHost(document.getElementById(targetId || PAGE_TOOLS_SLOT_ID))
  }, [targetId])

  if (!host) return null
  return createPortal(children, host)
}
