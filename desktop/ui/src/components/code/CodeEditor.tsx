import { useEffect, useRef } from 'react'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'

import { baseExtensions, loadLanguage } from './cmSetup'

interface CodeEditorProps {
  /** 初始内容（只在挂载 / 换 docKey 时读一次，⛔ 不做受控） */
  initialText: string
  lang: string
  /** 切换文档的标识（版本名）；变了就重建编辑器 */
  docKey: string
  /** 内容变化（防抖保存由调用方做） */
  onChange: (text: string) => void
}

/**
 * ★★ **可编辑**代码视窗（仿写用）
 *
 * 与 `CodeViewer` 的区别只有一处：`baseExtensions({ readOnly: false })`。
 * ⚠ 受控重渲染会让 CM6 每敲一个字就重建 view、光标丢失，
 *   所以这里**只在 docKey/lang 变化时重建**，内容靠 onChange 往上抛。
 */
export default function CodeEditor({ initialText, lang, docKey, onChange }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const cb = useRef(onChange)
  cb.current = onChange

  useEffect(() => {
    let cancelled = false

    void (async () => {
      const langExt = await loadLanguage(lang)
      if (cancelled || !host.current) return

      const state = EditorState.create({
        doc: initialText,
        extensions: [
          ...baseExtensions({ readOnly: false }),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) cb.current(u.state.doc.toString())
          }),
          ...(langExt ? [langExt] : []),
        ],
      })
      const view = new EditorView({ state, parent: host.current })
      viewRef.current = view
      view.focus()
    })()

    return () => {
      cancelled = true
      viewRef.current?.destroy()
      viewRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docKey, lang])

  return <div ref={host} style={{ height: '100%', minHeight: 0, overflow: 'hidden' }} />
}
