/**
 * ★★ 个人版的界面偏好（本地存储，不需要后端）⚠
 *
 * 目前只有一项：**流星特效**（图谱里节点之间飞过的流光）。
 *
 * 为什么单独抽出来：
 *   它原来放在图谱页的「工具」下拉里 —— 所有者（2026-11-05）：
 *   「流星这个应该在设置页面出现，怎么出现在这个下拉栏了？」
 *   ⇒ 移到 设置 → 外观，绘图页只读这里的值。
 */
const KEY_METEORS = 'astrolabe.meteors'

/** 读「流星」开关（默认开）*/
export function getMeteors(): boolean {
  try {
    const v = localStorage.getItem(KEY_METEORS)
    return v === null ? true : v === '1'
  } catch {
    return true // 隐私模式 / 存储被禁 ⇒ 用默认值，不抛错
  }
}

/** 写「流星」开关 */
export function setMeteors(on: boolean): void {
  try {
    localStorage.setItem(KEY_METEORS, on ? '1' : '0')
  } catch {
    /* 存不了就算了，下次还是默认开 */
  }
}
