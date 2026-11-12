/**
 * ★★ ribbon ↔ 当前工作区的轻量桥接
 *
 * Obsidian 的左侧 ribbon 是全局的，但按钮作用在「当前活动的编辑器」上。
 * 这里用一个模块级 store：CodeWorkspace / NoteSection / 图谱页挂载时
 * 各自注册自己能做的事，ribbon 用 useSyncExternalStore 读取即可。
 * ⛔ 不引入状态管理库、不层层传 props。
 */
export interface RibbonActions {
  projectRef?: string
  activePath?: string
  copy?: () => void
  toggleImmersive?: () => void
  toggleFullscreen?: () => void
  toggleCanvasFullscreen?: () => void
  /** ★ 打开白板：传白板 id 打开指定那块，不传则打开该节点的默认白板 */
  openThinking?: (boardId?: string) => void
  /** ★ 当前选中节点的 vid（NoteSection 注册；思考面板随节点切换变化用）⚠ */
  currentNodeVid?: number
  /** ★ 白板打开时由 App 注册：收起左侧功能面板 */
  closePanel?: () => void
  createNote?: () => void
  openPath?: (path: string) => void
}

let current: RibbonActions = {}
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((l) => l())
}

export function patchRibbon(patch: Partial<RibbonActions>) {
  current = { ...current, ...patch }
  emit()
}

export function clearRibbon(keys: (keyof RibbonActions)[]) {
  const next = { ...current }
  keys.forEach((k) => delete next[k])
  current = next
  emit()
}

export function ribbonActions(): RibbonActions {
  return current
}

export function subscribeRibbon(l: () => void): () => void {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export type PanelKind = 'search' | 'thinking'
