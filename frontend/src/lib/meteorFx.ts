/**
 * ★★ 流星轨迹效果（`D104`）—— 一块透明 canvas 罩在 G6 画布上
 *
 * ## ★★ 所有者口径
 *
 * > 「**用 canvas 罩上就行**」
 * > 「**把流星轨迹的流星做大点，颜色做鲜艳点，我看看是不是透明了**」
 *
 * ## ★★ 用法
 *
 * ```ts
 * const stop = startMeteor(graph, container, edges)
 * // 卸载时调 stop()（⛔ 不调会泄漏 rAF）
 * ```
 *
 * ## ★★ 三条硬要求（* 都是踩过的坑）
 *
 * ```
 * ① ★ container 必须 `position: relative` —— 罩层是 absolute;inset:0，
 *    否则会相对外层已定位祖先定位，整个跑到画布外面（= 看不见）
 * ② ★ 尺寸用 ResizeObserver 盯 —— 不能只信 effect 执行那一刻的 clientHeight
 * ③ ★ 坐标：世界坐标 → getViewportByCanvas 视口坐标；两种都试，取有效的
 * ```
 */

import type { Graph } from '@antv/g6'

/** 尾迹占整条边的比例 */
const TRAIL = 0.3
/** 尾迹分段数（越大越顺滑） */
const SEGS = 8
/** 最多同时飞多少条边（多了糊成一片） */
const MAX_EDGES = 120
/** 每帧相位推进 */
const SPEED = 0.01

/** 亮青（* 深色背景最醒目，* 不与节点蓝 / 边橙撞色） */
const COLOR = { r: 34, g: 211, b: 238 }

/** ★ 取节点屏幕坐标：视口坐标优先，无效则回落到画布坐标 */
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
 * @param graph     G6 实例（* 已 render 过）
 * @param container 画布容器（* 必须 `position: relative`）
 * @param edges     沿哪些边飞（* `{from, to}` = 节点 id）
 * @returns 停止函数
 */
export function startMeteor(
  graph: Graph,
  container: HTMLElement,
  edges: { from: string; to: string }[],
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
  let t = 0
  let raf = 0

  const draw = () => {
    if (!w || !h) {
      resize()
      return
    }
    ctx.clearRect(0, 0, w, h)
    const n = list.length
    if (!n) return

    for (let i = 0; i < n; i++) {
      const p1 = posOf(graph, list[i].from)
      const p2 = posOf(graph, list[i].to)
      if (!p1 || !p2) continue
      // 布局还没给位置（全 0）⇒ 跳过；否则会画在左上角
      if (p1[0] === 0 && p1[1] === 0 && p2[0] === 0 && p2[1] === 0) continue

      const tt = (t + i / n) % 1
      const dx = p2[0] - p1[0]
      const dy = p2[1] - p1[1]

      // ---- 尾迹：逐段描线，越靠近头部越亮越粗 ----
      for (let k = 1; k <= SEGS; k++) {
        const ta = tt - TRAIL + (TRAIL * (k - 1)) / SEGS
        const tb = tt - TRAIL + (TRAIL * k) / SEGS
        if (ta < 0) continue
        const f = k / SEGS
        const x1 = p1[0] + dx * ta
        const y1 = p1[1] + dy * ta
        const x2 = p1[0] + dx * tb
        const y2 = p1[1] + dy * tb
        const lw = 3.5 + 4.5 * f
        // ★★ 先描一层**深色外框** ——* 浅色主题下亮青几乎隐形，
        //    * 有这层描边就任何背景都看得清 ⚠
        ctx.strokeStyle = `rgba(15,23,42,${(0.35 + 0.35 * f).toFixed(2)})`
        ctx.lineWidth = lw + 2.5
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.stroke()
        // ★ 亮芯
        ctx.strokeStyle = `rgba(${COLOR.r},${COLOR.g},${COLOR.b},${(0.45 + 0.55 * f).toFixed(2)})`
        ctx.lineWidth = lw
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.stroke()
      }

      // ---- 头部：径向光晕 + 白色亮核 ----
      const hx = p1[0] + dx * tt
      const hy = p1[1] + dy * tt
      // ★ 深色描边圈（* 浅色背景上白核不显形，* 靠它兜住）⚠
      ctx.fillStyle = 'rgba(15,23,42,0.55)'
      ctx.beginPath()
      ctx.arc(hx, hy, 19, 0, Math.PI * 2)
      ctx.fill()

      const glow = ctx.createRadialGradient(hx, hy, 0, hx, hy, 18)
      glow.addColorStop(0, `rgba(${COLOR.r},${COLOR.g},${COLOR.b},0.95)`)
      glow.addColorStop(0.45, `rgba(${COLOR.r},${COLOR.g},${COLOR.b},0.45)`)
      glow.addColorStop(1, `rgba(${COLOR.r},${COLOR.g},${COLOR.b},0)`)
      ctx.fillStyle = glow
      ctx.beginPath()
      ctx.arc(hx, hy, 18, 0, Math.PI * 2)
      ctx.fill()

      ctx.fillStyle = '#e0fbff'
      ctx.beginPath()
      ctx.arc(hx, hy, 5, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  const loop = () => {
    t = (t + SPEED) % 1
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
