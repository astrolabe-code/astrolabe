/**
 * ★★ 流星轨迹效果（`D104`）—— 一块透明 canvas 罩在 G6 画布上
 *
 * ## ★★ 实现来源
 *
 * 移植自原型 `code_network/src/meteor.js`（* 所有者已确认效果的那套）：
 *
 * ```
 * ★★ 尾迹 = **线性渐变**（尾透明 → 头 0.9）+ 两层（宽而淡 / 窄而亮）✅
 * ★★ 光晕 = 径向渐变：* 中心**白色** → 35% 处节点色 → 边缘透明 ✅
 * ★★ 头部 = 纯白亮点 ✅
 * ★★ 首尾各 8% 淡入淡出 ——* 循环衔接不跳变 ✅
 * ★★ 所有尺寸 × `scale`（= 画布 zoom）—— 滚轮缩放时同步变大变小 ✅
 * ```
 *
 * ## ★★ 位置与尺寸
 *
 * ```
 * ★ 位置：* `getElementPosition` → `getViewportByCanvas` ⇒ 视口坐标 ✅
 * ★ 尺寸：* 全部乘 `graph.getZoom()`（* 视口坐标下节点也是按 zoom 缩放的）⚠
 * ★ 起点 / 终点各留**节点半径** ⇒ 流星停在节点边界，不穿模 ✅
 * ```
 */

import type { Graph } from '@antv/g6'

/** 首尾各淡入/淡出的占比（占全程比例） */
const FADE = 0.08
/** 最多同时飞多少条边 */
const MAX_EDGES = 120
/** 每帧相位推进（默认；用户设置可覆盖） */
const DEFAULT_SPEED = 0.005
/** 头部半径 = 节点半径 × 这个比例（默认 1/4 直径） */
const DEFAULT_SIZE_RATIO = 0.25

/** ★ 可调项（来自用户设置 `graph.meteor.*`） */
export interface MeteorOptions {
  /** 每帧相位增量：越小越慢 */
  speed?: number
  /** 头部直径 / 节点直径 */
  sizeRatio?: number
}

/** 十六进制 → rgb */
function hexRgb(hex: string): { r: number; g: number; b: number } {
  const m = /^#?([0-9a-fA-F]{6})$/.exec((hex || '').trim())
  if (!m) return { r: 59, g: 130, b: 246 }
  const v = parseInt(m[1], 16)
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 }
}

const rgba = (c: { r: number; g: number; b: number }, a: number) =>
  `rgba(${c.r},${c.g},${c.b},${a})`

/** 取节点屏幕坐标（视口坐标优先，无效回落画布坐标） */
function posOf(graph: Graph, id: string): [number, number] | null {
  let raw: unknown
  try {
    raw = graph.getElementPosition(id)
  } catch {
    return null
  }
  if (!raw) return null
  const canvas = Array.from(raw as ArrayLike<number>)
  if (!isFinite(canvas[0]) || !isFinite(canvas[1])) return null
  try {
    const vp = Array.from(graph.getViewportByCanvas(raw as never) as ArrayLike<number>)
    if (isFinite(vp[0]) && isFinite(vp[1])) return [vp[0], vp[1]]
  } catch {
    /* 回落 */
  }
  return [canvas[0], canvas[1]]
}

/**
 * 启动流星效果。
 *
 * @param graph     G6 实例（已 render 过）
 * @param container 画布容器（必须 `position: relative`）
 * @param edges     沿哪些边飞：`from` 的 `size`/`color` + `to` 的 `toSize`
 * @param opts      速度 / 大小比例（来自用户设置）
 * @returns 停止函数（卸载时必调）
 */
export function startMeteor(
  graph: Graph,
  container: HTMLElement,
  edges: { from: string; to: string; size: number; color: string; toSize: number }[],
  opts: MeteorOptions = {},
): () => void {
  const canvas = document.createElement('canvas')
  canvas.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:999;'
  container.appendChild(canvas)

  const ctx = canvas.getContext('2d')
  if (!ctx) {
    canvas.remove()
    return () => {}
  }

  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  let w = 0
  let h = 0
  const resize = () => {
    w = container.clientWidth || 0
    h = container.clientHeight || 0
    if (!w || !h) return
    canvas.width = Math.round(w * dpr)
    canvas.height = Math.round(h * dpr)
    canvas.style.width = `${w}px`
    canvas.style.height = `${h}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
  resize()
  const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null
  ro?.observe(container)

  const list = edges.slice(0, MAX_EDGES)
  const speed = opts.speed ?? DEFAULT_SPEED
  const sizeRatio = opts.sizeRatio ?? DEFAULT_SIZE_RATIO
  let t = 0
  let raf = 0

  const draw = () => {
    if (!w || !h) {
      resize()
      return
    }
    ctx.clearRect(0, 0, w, h)

    // ★ 当前缩放：* 流星所有尺寸都乘它 ⇒ 滚轮缩放时同步变化 ⚠
    let zoom = 1
    try {
      zoom = graph.getZoom() || 1
    } catch {
      zoom = 1
    }

    const n = list.length
    for (let i = 0; i < n; i++) {
      const e = list[i]
      const p1 = posOf(graph, e.from)
      const p2 = posOf(graph, e.to)
      if (!p1 || !p2) continue

      const dx = p2[0] - p1[0]
      const dy = p2[1] - p1[1]
      const dist = Math.hypot(dx, dy)
      // ★ 起点/终点各留节点半径（* 已乘 zoom）⇒ 不穿模 ⚠
      const padFrom = ((e.size || 14) / 2) * zoom
      const padTo = ((e.toSize || 14) / 2) * zoom
      if (dist <= padFrom + padTo + 2) continue

      const ux = dx / dist
      const uy = dy / dist

      // ---- 进度 + 首尾淡入淡出 ----
      const tt = (t + i / n) % 1
      const alpha =
        tt < FADE ? tt / FADE : tt > 1 - FADE ? (1 - tt) / FADE : 1
      if (alpha <= 0.01) continue

      // ---- 头部 / 尾部（视口坐标）----
      const headD = padFrom + (dist - padFrom - padTo) * tt
      const trailLen = Math.max(18, dist * 0.32)
      const tailD = Math.max(headD - trailLen, padFrom)
      const hx = p1[0] + ux * headD
      const hy = p1[1] + uy * headD
      const tx = p1[0] + ux * tailD
      const ty = p1[1] + uy * tailD

      const rgb = hexRgb(e.color)
      const dotR = Math.max(0.6, ((e.size || 14) * sizeRatio * zoom) / 2)

      // ---- 尾迹：线性渐变（尾透明 → 头 0.9），两层 ----
      const grad = ctx.createLinearGradient(tx, ty, hx, hy)
      grad.addColorStop(0, rgba(rgb, 0))
      grad.addColorStop(1, rgba(rgb, 0.9))
      ctx.strokeStyle = grad
      ctx.lineCap = 'round'

      // 外层：宽而淡
      ctx.globalAlpha = 0.25 * alpha
      ctx.lineWidth = dotR * 2.4
      ctx.beginPath()
      ctx.moveTo(tx, ty)
      ctx.lineTo(hx, hy)
      ctx.stroke()

      // 内层：窄而亮
      ctx.globalAlpha = alpha
      ctx.lineWidth = dotR * 1.2
      ctx.beginPath()
      ctx.moveTo(tx, ty)
      ctx.lineTo(hx, hy)
      ctx.stroke()

      // ---- 光晕：中心白 → 节点色 → 透明 ----
      const glowR = dotR * 4
      const glow = ctx.createRadialGradient(hx, hy, 0, hx, hy, glowR)
      glow.addColorStop(0, `rgba(255,255,255,${(0.95 * alpha).toFixed(3)})`)
      glow.addColorStop(0.35, rgba(rgb, 0.35 * alpha))
      glow.addColorStop(1, rgba(rgb, 0))
      ctx.fillStyle = glow
      ctx.beginPath()
      ctx.arc(hx, hy, glowR, 0, Math.PI * 2)
      ctx.fill()

      // ---- 头部亮点：纯白 ----
      ctx.globalAlpha = alpha
      ctx.fillStyle = '#ffffff'
      ctx.beginPath()
      ctx.arc(hx, hy, dotR, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha = 1
    }
  }

  const loop = () => {
    t = (t + speed) % 1
    draw()
    raf = requestAnimationFrame(loop)
  }
  raf = requestAnimationFrame(loop)

  return () => {
    cancelAnimationFrame(raf)
    ro?.disconnect()
    canvas.remove()
  }
}
