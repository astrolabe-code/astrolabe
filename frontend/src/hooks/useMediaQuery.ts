import { useEffect, useState } from 'react'

/** 媒体查询订阅(用于 <lg 切「节点列表」形态,断点与现站一致) */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia(query).matches : false,
  )

  useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches)
    setMatches(mql.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}

/** 是否小屏(<1024px → 图谱走列表形态) */
export function useIsSmallScreen(): boolean {
  return useMediaQuery('(max-width: 1023px)')
}
