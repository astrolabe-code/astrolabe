import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const KEY = 'theme'

/** 与旧站 base.js 完全一致:同 key、同取值、写到 <html data-theme>、派发 themechange */
export function applyTheme(t: Theme) {
  document.documentElement.setAttribute('data-theme', t)
  try {
    localStorage.setItem(KEY, t)
  } catch (e) {
    console.error('write theme failed', e)
  }
  document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: t } }))
}

function readSaved(): Theme | null {
  try {
    const t = localStorage.getItem(KEY)
    return t === 'dark' || t === 'light' ? t : null
  } catch (e) {
    console.error('read theme failed', e)
    return null
  }
}

function systemTheme(): Theme {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => readSaved() ?? systemTheme())

  // 初始化:未手动选择过则跟随系统变化(与旧站行为一致)
  useEffect(() => {
    const saved = readSaved()
    const initial = saved ?? systemTheme()
    document.documentElement.setAttribute('data-theme', initial)
    document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: initial } }))

    const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
    if (!mq) return
    const onChange = (e: MediaQueryListEvent) => {
      if (readSaved()) return
      const next: Theme = e.matches ? 'dark' : 'light'
      document.documentElement.setAttribute('data-theme', next)
      document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: next } }))
      setTheme(next)
    }
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [])

  const toggle = useCallback(() => {
    setTheme((cur) => {
      const next: Theme = cur === 'dark' ? 'light' : 'dark'
      applyTheme(next)
      return next
    })
  }, [])

  return { theme, toggle }
}
