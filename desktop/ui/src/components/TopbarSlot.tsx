import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** ★ 顶栏插槽的 DOM id（`PersonalBar` 里渲染这个空位）*/
export const TOPBAR_SLOT_ID = 'app-topbar-slot'

/**
 * ★★★ **把页面级工具条挂到顶栏那一行**（2026-11-05）
 *
 * 所有者：「你把这些工具按钮直接移到上面的 astrolabe 行，不就完了？上面那么空」
 *
 * ## 为什么用 portal
 *
 * ```
 * 顶栏 `PersonalBar` 在 App.tsx 里渲染，**在所有路由之外**
 * ⇒ 页面不能通过 props 把它自己的按钮塞进去
 * ⇒ 顶栏留一个空 div（id=app-topbar-slot），页面用 portal 把 JSX 挂进去 ✅
 * ```
 *
 * ⚠ 顶栏先于页面挂载 ⇒ 首帧拿不到节点，所以用 state + effect 再渲染一次。
 * ⚠ 页面卸载时 portal 自动移除（React 保证），顶栏不会残留上一页的按钮。
 */
export default function TopbarSlot({ children }: { children: ReactNode }) {
  const [host, setHost] = useState<HTMLElement | null>(null)

  useEffect(() => {
    setHost(document.getElementById(TOPBAR_SLOT_ID))
  }, [])

  if (!host) return null
  return createPortal(children, host)
}
