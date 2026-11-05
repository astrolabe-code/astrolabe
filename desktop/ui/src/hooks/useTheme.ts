import { useCallback } from 'react'

export type Theme = 'light' | 'dark'

/**
 * ★ 个人版没有明暗主题：界面恒为白（见 POSITIONING 0.4）
 *
 * ⚠ 刻意**不写** `<html data-theme>`：`[data-theme='plain']` 那套全白覆盖才会生效
 * ⚠ 也不跟随系统深色 —— 否则白底 + 深色文字会不可读
 * ⇒ 所以这里没有 localStorage、没有媒体查询、没有事件订阅，只有一个空 toggle
 */
export function useTheme() {
  const toggle = useCallback(() => {
    /* 个人版没有明暗切换 */
  }, [])
  return { theme: 'light' as Theme, toggle }
}
