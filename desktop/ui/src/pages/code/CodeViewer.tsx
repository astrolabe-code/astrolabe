import { useEffect, useRef } from 'react'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'

import { baseExtensions, focusLine, loadLanguage } from './cmSetup'

interface CodeViewerProps {
  text: string
  /** 语言标识（cmSetup.loadLanguage 按需加载） */
  lang: string
  /** 当前节点所在行（1 起）；会滚到中央并高亮 */
  focus?: number | null
}

/**
 * ★★ 只读代码视窗（CodeMirror 6）
 *
 * ⚠ 文本/语言变化 ⇒ 重建 EditorState（文件一般几百行，重建足够快且状态干净）
 * ⚠ 只改「选中行」时不重建，只发一个 StateEffect ⇒ 点图谱节点时不会闪
 * ⚠ 以后做仿写：去掉 cmSetup.baseExtensions() 里的 readOnly/editable 两行即可
 */
export default function CodeViewer({ text, lang, focus }: CodeViewerProps) {
  const host = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)

  useEffect(() => {
    let cancelled = false

    void (async () => {
      const langExt = await loadLanguage(lang)
      if (cancelled || !host.current) return

      const state = EditorState.create({
        doc: text,
        extensions: [...baseExtensions(), ...(langExt ? [langExt] : [])],
      })
      const view = new EditorView({ state, parent: host.current })
      viewRef.current = view
      if (focus) focusLine(view, focus)
    })()

    return () => {
      cancelled = true
      viewRef.current?.destroy()
      viewRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, lang])

  useEffect(() => {
    if (viewRef.current) focusLine(viewRef.current, focus ?? null)
  }, [focus])

  return (
    <div
      ref={host}
      style={{ height: '100%', minHeight: 0, overflow: 'hidden' }}
      aria-label="源码内容"
    />
  )
}
