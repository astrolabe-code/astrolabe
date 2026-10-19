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

/** 兜底颜色（* 边上的节点查不到时用） */
const FALLBACK = { r: 148, g: 163, b: 184 }

/** ★ 十六进制 → rgb（* 节点颜色是 `#4db8d6` 这种） */
function hexRgb(hex: string): { r: number; g: number; b: number } {
  const m = /^#?([0-9a-fA-F]{6})$/.exec((hex || '').trim())
  if (!m) return FALLBACK
  const v = parseInt(m[1], 16)
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 }
}

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
 * @param edges     沿哪些边飞 —— ★ 每条边带**发出节点**的 `size` / `color`：
 *                  * 流星大小 = 节点直径的 **1/10**，* 颜色 = 节点颜色 ✅
 * @returns 停止函数
 */
export function startMeteor(
  graph: Graph,
  container: HTMLElement,
  edges: { from: string; to: string; size: number; color: string }[],
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

      // ★★★ 所有者口径：**流星大小 = 发出节点直径的 1/6**（* 从 1/10 调大），
      //     **颜色 = 发出节点的颜色** ⚠
      const size = list[i].size || 14
      const headD = Math.max(2, size / 6) // 直径（* 节点 14 ⇒ ≈2.3px）
      const headR = headD / 2
      const glowR = headR * 5 // 光晕比头部大 5 倍（* 小尺寸也要看得见）
      const rgb = hexRgb(list[i].color)
      const lw0 = Math.max(0.9, headR * 1.6) // 尾迹基准线宽

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
        const lw = lw0 * (0.7 + 1.3 * f)
        // ★★ 先描一层**深色外框** ——* 浅色主题下亮青几乎隐形，
        //    * 有这层描边就任何背景都看得清 ⚠
        ctx.strokeStyle = `rgba(15,23,42,${(0.3 + 0.35 * f).toFixed(2)})`
        ctx.lineWidth = lw + 1.2
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.stroke()
        // ★ 亮芯
        ctx.strokeStyle = `rgba(${rgb.r},${rgb.g},${rgb.b},${(0.45 + 0.55 * f).toFixed(2)})`
        ctx.lineWidth = lw
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.stroke()
      }

      // ---- 头部：径向光晕 + 白色亮核 ----
      const hx = p1[0] + dx * tt
      const hy = p1[1] + dy * tt
      // ★ 深色兜底圈（* 浅色背景上亮色不显形，* 靠它勾出轮廓）⚠
      ctx.fillStyle = 'rgba(15,23,42,0.5)'
      ctx.beginPath()
      ctx.arc(hx, hy, glowR + 0.8, 0, Math.PI * 2)
      ctx.fill()

      // ★ 光晕：**颜色 = 发出节点的颜色**
      const glow = ctx.createRadialGradient(hx, hy, 0, hx, hy, glowR)
      glow.addColorStop(0, `rgba(${rgb.r},${rgb.g},${rgb.b},0.95)`)
      glow.addColorStop(0.45, `rgba(${rgb.r},${rgb.g},${rgb.b},0.5)`)
      glow.addColorStop(1, `rgba(${rgb.r},${rgb.g},${rgb.b},0)`)
      ctx.fillStyle = glow
      ctx.beginPath()
      ctx.arc(hx, hy, glowR, 0, Math.PI * 2)
      ctx.fill()

      // ★ 亮核（* 同色偏白，* 保证小尺寸下也能看清）
      ctx.fillStyle = `rgba(${Math.min(255, rgb.r + 90)},${Math.min(255, rgb.g + 90)},${Math.min(255, rgb.b + 90)},1)`
      ctx.beginPath()
      ctx.arc(hx, hy, Math.max(0.7, headR), 0, Math.PI * 2)
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
