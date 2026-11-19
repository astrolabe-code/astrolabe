import { useEffect, useState } from 'react'

/**
 * ★★ 「AI 正在回答」的全局状态。
 *
 * 所有者原话（2026-11-19）：
 * 「你这遮罩效果也太明显了吧？一下子，整个界面就变暗了，而且问答界面也被封了，
 *   无法滚动了… 就像我说的，写一个组件，可以添加禁用按钮，可以禁用和解禁按钮。
 *   禁用的按钮就变成灰色的就行」
 *
 * ## 为什么不用遮罩
 *
 * 遮罩会把**整个界面**压暗，而且 z-index 一旦没算准，连问答区都被盖住
 * （用户就滚不动、看不到流式输出了）。禁用只需要作用在「能跳转的东西」上：
 * 节点、列表行、tab —— 问答区本身不在其中。
 *
 * ## 用法
 *
 * ```tsx
 * const busy = useAiBusy()
 * <button className={`code-tab${busy ? ' ai-disabled' : ''}`} disabled={busy}>
 * ```
 *
 * 或者包一层：
 *
 * ```tsx
 * <DisableWrap>…一组按钮…</DisableWrap>
 * ```
 *
 * ⚠ 不做成 React context：这些组件分散在页面各处，逐层传 provider 太麻烦，
 *   而这里只有一个布尔值，订阅式的最小实现就够。
 */

let busy = false
const listeners = new Set<(v: boolean) => void>()

/** 由问答发起处调用：开始回答时 true，结束（成功或失败）时 false */
export function setAiBusy(v: boolean): void {
  const next = Boolean(v)
  if (busy === next) return
  busy = next
  listeners.forEach((fn) => fn(next))
}

export function isAiBusy(): boolean {
  return busy
}

/** 组件里订阅；返回当前是否忙碌 */
export function useAiBusy(): boolean {
  const [v, setV] = useState(busy)
  useEffect(() => {
    listeners.add(setV)
    setV(busy) // 挂载时可能有别的组件已经在跑
    return () => {
      listeners.delete(setV)
    }
  }, [])
  return v
}

/** 忙碌时给元素追加的类名（配合 components.css 里的 .ai-disabled） */
export function disableClass(busyNow: boolean, base = ''): string {
  return busyNow ? `${base} ai-disabled`.trim() : base
}
