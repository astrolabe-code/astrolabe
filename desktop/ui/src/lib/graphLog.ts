/**
 * ★ 图谱诊断日志（前端 → Electron ui.log）
 *
 * main.js 已监听渲染进程的 console-message，所有 console.log 会落盘到
 * exe 旁的 ui.log。统一加 [GRAPH] 前缀，方便 grep：
 *   grep '\[GRAPH\]' ui.log
 *
 * ⚠ 只打「定位渲染问题需要的事实」：节点数、canvas 尺寸、坐标范围、
 *   布局耗时、hover 命中。⛔ 不打每个 token / 每帧，以免日志爆炸。
 */

const PREFIX = '[GRAPH]'

export function graphLog(tag: string, data?: Record<string, unknown>) {
  const msg = data ? `${PREFIX} ${tag} ${JSON.stringify(data)}` : `${PREFIX} ${tag}`
  // ★ console.info 的 level 是 info，主进程会写成 console[info]
  console.info(msg)
}

/** 数值取一位小数，避免日志里一长串浮点 */
export const n1 = (v: number) => Math.round(v * 10) / 10
