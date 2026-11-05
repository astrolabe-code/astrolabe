/**
 * ★ **可折叠卡片的状态**（2026-10-27）⚠
 *
 * 所有者：「**写作进度和导读路径应该可以折叠，不然占了太多空间**」
 *
 * ⚠ 状态存 localStorage：收起来之后**下次打开还是收着的** ——
 *   ⛔ 不要只在组件里 `useState`，那样一刷新就弹回来，等于没折 ⚠
 */
import { useCallback, useState } from 'react'

const PREFIX = 'astrolabe.collapsed.'

export function useCollapsed(key: string, initial = false) {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(PREFIX + key)
      return v === null ? initial : v === '1'
    } catch {
      // ★ 隐私模式 / 禁用存储 ⇒ 退回默认，⛔ 别让页面挂掉 ⚠
      return initial
    }
  })

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(PREFIX + key, next ? '1' : '0')
      } catch {
        /* ignore */
      }
      return next
    })
  }, [key])

  return { collapsed, toggle }
}
