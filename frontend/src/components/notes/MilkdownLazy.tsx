import { lazy, Suspense } from 'react'
import { MilkdownProvider } from '@milkdown/react'

/**
 * ★★ **懒加载版的只读渲染**（`D108`）⚠
 *
 * ⚠ Milkdown 解包后上百 MB ⇒ 直接 import 会把首屏体积撑爆；
 *   这里按需加载，* 只有真正渲染笔记正文时才拉代码 ✅
 */
const Inner = lazy(() => import('./MilkdownView'))

/** ★ 与 MilkdownView 同形的 props（* 这里只做转发）⚠ */
import type { NoteBlockInfo, SelectionInfo } from './MilkdownView'

export interface MilkdownLazyProps {
  text: string
  blocks?: NoteBlockInfo[]
  onOpenBlock?: (b: NoteBlockInfo) => void
  authed?: boolean
  onSelection?: (info: SelectionInfo) => void
}

export default function MilkdownLazy(props: MilkdownLazyProps) {
  return (
    <Suspense
      fallback={
        <div className="faint" style={{ fontSize: 12.5, padding: '8px 0' }}>
          渲染中…
        </div>
      }
    >
      {/* ⚠ Provider 必须包住 Inner —— useEditor 在 Inner 内部调用，
         要能注册工厂（* 否则报 setEditorFactory is not a function）⚠ */}
      <MilkdownProvider>
        <Inner {...props} />
      </MilkdownProvider>
    </Suspense>
  )
}
