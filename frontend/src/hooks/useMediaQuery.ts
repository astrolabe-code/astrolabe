import { useEffect, useState } from 'react'

/**
 * ★★ 响应式断点 hook（* 移动端适配用）⚠
 *
 * ```
 * const isNarrow = useMediaQuery('(max-width: 900px)')
 * ```
 *
 * ★ 用 `matchMedia` + `change` 事件 ⇒* 窗口拖拽 / 旋转都会实时更新 ✅
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mq = window.matchMedia(query)
    const on = (e: MediaQueryListEvent) => setMatches(e.matches)
    setMatches(mq.matches)
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [query])

  return matches
}
