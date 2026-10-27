/**
 * ★★★ **「继续上次」的本地存档**（`D120` · 2026-10-27）⚠
 *
 * ## 所有者原话（逐字）
 *
 * > 「**记录用户上次看到的是那个项目的那个节点，打了网站时，自动跳到对应节点，
 * >   展开图。就像游戏存档一样，打开还是原来退出时的界面和进度。**」
 *
 * ## ⚠ 为什么放 localStorage，不放后端
 *
 * ```\n * · 这是**单机体验**，不值得为它加表、加字段、加迁移 ⚠\n * · 存的东西没有隐私价值（项目 ref + 节点 vid，都是公开标识）✅\n * ```\n *
 * ## ★★★ 记录时机（所有者追问过，见 `D120`③）
 *
 * ```\n * ⛔ 每次点击都记      ⇒ 存档会漂移到「只是瞟了一眼」的节点\n * ⛔ 只有写笔记才记    ⇒ 读两小时没写字，离开后回来没存档\n * ✅ 停留 ≥ 阈值 或 写了笔记/评论 ⇒ 才写（阈值后台可调，0 = 关闭）\n * ```\n *
 * ## ★ 语义
 *
 * `vid` 用 **stable_vid**（和 `reading_path` 里存的一致），⛔ 不用自增 id ⚠
 */

const KEY = 'astrolabe.resume.v1'

/** ★ 存档有效期：7 天（* 三个月后打开还跳回去会很怪）⚠ */
const TTL_MS = 7 * 24 * 60 * 60 * 1000

export interface ResumePoint {
  /** 项目 ref */
  ref: string
  /** 节点 stable_vid */
  vid: number
  /** ★ 节点名（* 只用于首页提示条显示，⛔ 不参与任何判断）⚠ */
  name?: string
  /** 记录时刻（毫秒） */
  at: number
}

function safeParse(raw: string | null): ResumePoint | null {
  if (!raw) return null
  try {
    const o = JSON.parse(raw) as ResumePoint
    if (!o || typeof o.ref !== 'string' || typeof o.vid !== 'number') return null
    if (typeof o.at !== 'number') return null
    return o
  } catch {
    return null
  }
}

/** ★ 读存档（过期的返回 null，顺手清掉）⚠ */
export function readResume(): ResumePoint | null {
  try {
    const p = safeParse(localStorage.getItem(KEY))
    if (!p) return null
    if (Date.now() - p.at > TTL_MS) {
      localStorage.removeItem(KEY)
      return null
    }
    return p
  } catch {
    // ★ 隐私模式 / 禁用存储 ⇒ 静默降级，⛔ 不让它影响页面 ⚠
    return null
  }
}

/** ★ 写存档 ⚠ */
export function markResume(ref: string, vid: number, name?: string): void {
  if (!ref || !vid) return
  try {
    localStorage.setItem(
      KEY,
      JSON.stringify({ ref, vid, name: name || '', at: Date.now() } as ResumePoint),
    )
  } catch {
    /* 存储不可用 ⇒ 忽略 */
  }
}

/**
 * ★★ 清存档 —— 什么时候用：
 *   · 用户明确关掉「继续」提示条
 *   · 存档指向的项目 404 / 无权访问
 */
export function clearResume(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}

/** ★ 人话时间（"3 小时前"）—— 提示条上显示 ⚠ */
export function agoText(at: number): string {
  const min = Math.floor((Date.now() - at) / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}
