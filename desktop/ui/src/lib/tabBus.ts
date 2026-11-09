/**
 * ★★ **文件选项卡（tab）状态**（2026-11-08，模仿 Obsidian 标签栏）
 *
 * 所有者：「现在来模仿 obsidian，做这个文件选项吧，新建笔记的按钮就移到在旁边」
 *
 * 与 ribbonBus 同样的轻量做法：模块级 store + 订阅，⛔ 不引状态管理库、
 * 不层层传 props。App/TabBar 用 useSyncExternalStore 读取即可。
 *
 * ⚠ tab 的 key 用 `pathname`（不含 query）—— 笔记页会用 ?node= / ?parent=
 *   带上下文，但同一篇笔记不该因为参数不同就开两个标签。
 */
export interface TabItem {
  path: string
  title: string
}

let current: TabItem[] = []
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((l) => l())
}

/** 依路径推断标签名；页面拿到真实标题后可再用 setTabTitle 覆盖 */
export function inferTabTitle(pathname: string): string {
  const seg = pathname.split('/').filter(Boolean)
  if (seg.length === 0) return '首页'
  if (seg[0] === 'me') return seg[1] === 'settings' ? '设置' : '个人'
  if (seg[0] !== 'p') return '页面'
  const proj = (() => {
    try {
      return decodeURIComponent(seg[1] || '')
    } catch {
      return seg[1] || ''
    }
  })()
  const sub = seg[2]
  if (!sub) return proj || '项目'
  if (sub === 'graph') return `${proj} · 图谱`
  if (sub === 'settings') return `${proj} · 设置`
  if (sub === 'notes') {
    if (seg[3] === 'new') return '新笔记'
    if (seg[4] === 'edit') return '编辑笔记'
    return '笔记'
  }
  return proj || '项目'
}

/** 进入某个路由时调用：已有则**保持原样**（⛔ 不能用推断标题覆盖页面设好的真实标题），
 *  没有则按推断标题追加到末尾。显式传 title 时才允许改名。 */
export function openTab(pathname: string, title?: string) {
  const i = current.findIndex((x) => x.path === pathname)
  if (i >= 0) {
    if (!title || current[i].title === title) return
    const next = current.slice()
    next[i] = { path: pathname, title }
    current = next
  } else {
    current = [...current, { path: pathname, title: title || inferTabTitle(pathname) }]
  }
  emit()
}

/**
 * ★★ 新建笔记保存后：**同一个标签原地变成真实笔记**（Obsidian 口径）
 *
 * 之前 save() 只 nav 到阅读页 ⇒ 旧的「新笔记」标签留在原地、
 * 阅读页又新开一个标签，用户看到「保存了标签还叫新建笔记」。
 *
 * @param oldPath 编辑页路径（/notes/new 或 /notes/:id/edit）
 * @param newPath 保存后要去的地方（阅读页 / 来源页）的 pathname
 */
export function replaceTab(oldPath: string, newPath: string, title: string) {
  const iNew = current.findIndex((x) => x.path === newPath)
  if (iNew >= 0 && newPath !== oldPath) {
    // 目标页已经有标签了 ⇒ 只删掉这个临时的编辑标签，不覆盖已有标题
    current = current.filter((x) => x.path !== oldPath)
  } else {
    const iOld = current.findIndex((x) => x.path === oldPath)
    if (iOld < 0) {
      openTab(newPath, title)
      return
    }
    const next = current.slice()
    next[iOld] = { path: newPath, title }
    current = next
  }
  emit()
}

/** 笔记页拿到真实标题后覆盖（⛔ 不新增标签） */
export function setTabTitle(pathname: string, title: string) {
  if (!title) return
  const i = current.findIndex((x) => x.path === pathname)
  if (i < 0 || current[i].title === title) return
  const next = current.slice()
  next[i] = { path: pathname, title }
  current = next
  emit()
}

/** 关闭标签，返回关闭后应跳转的相邻路径（没有剩余标签则返回 '/'） */
export function closeTab(pathname: string): string {
  const i = current.findIndex((x) => x.path === pathname)
  if (i < 0) return '/'
  const next = current.slice(0, i).concat(current.slice(i + 1))
  current = next
  emit()
  if (next.length === 0) return '/'
  return next[Math.min(i, next.length - 1)].path
}

export function tabs(): TabItem[] {
  return current
}

export function subscribeTabs(l: () => void): () => void {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}
