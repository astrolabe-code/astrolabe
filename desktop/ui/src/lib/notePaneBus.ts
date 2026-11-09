/**
 * ★★ 工作区「阅读 / 编辑」两个标签的共享状态（2026-11-09）
 *
 * 所有者：「停，太麻烦了，容易错，拆成两个标签，阅读和编辑」
 * ⇒ ⛔ 不把阅读页/编辑页合并成一个组件，两个页面各自原样嵌进容器。
 *
 * 与 ribbonBus / tabBus 同样的轻量做法：模块级 store + 订阅，
 * ⛔ 不引状态库、不层层传 props（notePanel 是外层传进来的 ReactNode）。
 */
export type NotePaneMode = 'read' | 'edit'

export interface NotePaneView {
  /** 笔记 ref；null = 新建 */
  ref: string | null
  mode: NotePaneMode
  nodeId: number
  parent?: string
  /** 每次「打开」递增 ⇒ 容器用它作 key 重建页面；内部跳转只改 mode 不重建 */
  token: number
}

let view: NotePaneView | null = null
let seq = 0
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((l) => l())
}

/** 页面上是否有工作区容器在监听（决定点卡片是就地打开还是照旧跳全屏页） */
export function hasNotePane(): boolean {
  return listeners.size > 0
}

export function openNotePane(v: Omit<NotePaneView, 'token'>) {
  view = { ...v, token: ++seq }
  emit()
}

/** 容器里两个标签之间切换：会重建页面 */
export function setNotePaneMode(mode: NotePaneMode) {
  if (!view || view.mode === mode) return
  view = { ...view, mode, token: ++seq }
  emit()
}

export function closeNotePane() {
  view = null
  emit()
}

export function notePaneView(): NotePaneView | null {
  return view
}

export function subscribeNotePane(l: () => void): () => void {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

/**
 * ★ 把页面里原有的站内路径（nav(...) 的参数）翻译成容器动作。
 * 这样 NotePage / NoteEditPage 的跳转逻辑一行都不用改，
 * 只要把 `nav` 换成回调即可。
 */
export function parseNotePath(
  path: string,
): Omit<NotePaneView, 'token'> | null {
  const [pathname, qs] = path.split('?')
  const q = new URLSearchParams(qs || '')
  const m = pathname.match(/\/p\/[^/]+\/notes\/(new|[^/]+)(?:\/edit)?$/)
  if (!m) return null // 回项目页 / 节点面板 ⇒ 收起，回到「笔记」列表
  const seg = m[1]
  const isEdit = seg === 'new' || /\/edit$/.test(pathname)
  return {
    mode: isEdit ? 'edit' : 'read',
    ref: seg === 'new' ? null : decodeURIComponent(seg),
    nodeId: Number(q.get('node') || 0),
    parent: q.get('parent') || undefined,
  }
}
