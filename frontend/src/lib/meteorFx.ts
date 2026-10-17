/**
 * ★★ **流星（流光）效果 —— G6 版**（`D98` · 2026-10-17 重写）
 *
 * ## ★ 从哪来的
 *
 * 旧版是 **vis-network** 的（* 还依赖旧站 vendored 补丁的 `__visFlowLayer` 钩子，
 * 靠运行时包装 `_drawNodes` 得到"边 → 流星 → 节点"的层序）⚠
 *
 * ## ★★ G6 版怎么画（* 不复刻内部钩子）
 *
 * ```
 * ★★ 在画布容器上叠一层**独立 canvas**（`pointer-events:none`）——
 *   · · ★ 每帧自己画流星 ⇒* 天然在节点**上方**同层混排，* 不碰 G6 内部渲染 ⚠
 * ★★ 取节点屏幕坐标：* `graph.getElementPosition(id)` ⇒ `graph.getViewportByCanvas()`
 *   （* 后者把世界坐标换算成视口坐标 —— 缩放/平移后也是对的）✅
 * ★★ 尾迹 = 沿直线取 6 段（* 旧版按边曲线取点；* 本图是直线边，* 线性足够）⚠
 * ```
 *
 * ⚠ 位置还没算出来（布局未完成）时**跳过该帧**，* 不报错。
 */

import type { Graph } from '@antv/g6'

export interface MeteorOptions {
  /** 初始相位 0~1（* 多张小图错开） */
  phase?: number
  /** 每步推进量，默认 0.008 */
  speed?: number
}

const TRAIL = 0.2
const SEGS = 6
const MAX_EDGES = 150

/** ★ 读主题色 `--fx-dot`（* 旧站没有该变量，回退 #38bdf8） */
function readFxColor() {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue('--fx-dot').trim()
    const m = v.match(/#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})/)
    if (m) {
      return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) }
    }
  } catch (e) {
    console.error('read --fx-dot failed', e)
  }
  return { r: 56, g: 189, b: 248 }
}

/**
 * ★ 启动流星效果
 *
 * @param graph      G6 图实例（* 已 render 过）
 * @param container  画布容器（* 叠加层挂在它上面，* 需要 `position:relative`）
 * @param edges      要画流星的边（* `{from, to}` 节点 id）
 * @returns ★ **停止函数**（* 组件卸载时必须调，* 否则 rAF 泄漏）⚠
 */
export function startMeteor(
  graph: Graph,
  container: HTMLElement,
  edges: { from: string; to: string }[],
  opts: MeteorOptions = {},
): () => void {
  const overlay = document.createElement('canvas')
  overlay.style.cssText =
    'position:absolute;inset:0;pointer-events:none;z-index:2;'
  container.appendChild(overlay)
  const ctx = overlay.getContext('2d')
  if (!ctx) {
    overlay.remove()
    return () => {}
  }

  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  let w = 0
  let h = 0
  const resize = () => {
    w = container.clientWidth
    h = container.clientHeight
    overlay.width = Math.max(1, Math.round(w * dpr))
    overlay.height = Math.max(1, Math.round(h * dpr))
    overlay.style.width = `${w}px`
    overlay.style.height = `${h}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
  resize()

  // ★ 边太多只画前 MAX_EDGES 条（* 旧版同口径）
  const list = edges.slice(0, MAX_EDGES)
  const color = readFxColor()
  const speed = opts.speed ?? 0.008
  let t = opts.phase ?? 0
  let raf: number | null = null
  let frame = 0

  /** ★ G6 的 `Point` 是 `[x, y]` 元组 / `Float32Array`（* 不是 `{x,y}`）⚠ */
  const toViewport = (p: Float32Array | number[]): number[] => {
    try {
      return Array.from(graph.getViewportByCanvas(p as never) as ArrayLike<number>)
    } catch {
      return Array.from(p)
    }
  }

  const draw = () => {
    if (!w || !h) return
    ctx.clearRect(0, 0, w, h)
    const n = list.length
    for (let i = 0; i < n; i++) {
      const e = list[i]
      let p1: number[]
      let p2: number[]
      try {
        p1 = toViewport(graph.getElementPosition(e.from) as Float32Array | number[])
        p2 = toViewport(graph.getElementPosition(e.to) as Float32Array | number[])
      } catch {
        continue
      }
      if (!p1 || !p2 || !isFinite(p1[0]) || !isFinite(p2[0])) continue
      // ★ 布局还没位置（全 0）⇒ 跳过本帧
      if (p1[0] === 0 && p1[1] === 0 && p2[0] === 0 && p2[1] === 0) continue

      const tt = (t + i / n) % 1
      // 尾迹：逐段描线，透明度 / 线宽向头部渐增
      for (let k = 1; k <= SEGS; k++) {
        const ta = tt - TRAIL + (TRAIL * (k - 1)) / SEGS
        const tb = tt - TRAIL + (TRAIL * k) / SEGS
        if (ta < 0) continue // 尾迹不越过源节点
        const f = k / SEGS
        ctx.strokeStyle = `rgba(${color.r},${color.g},${color.b},${(0.15 + 0.65 * f).toFixed(2)})`
        ctx.lineWidth = 1.5 + 2 * f
        ctx.beginPath()
        ctx.moveTo(p1[0] + (p2[0] - p1[0]) * ta, p1[1] + (p2[1] - p1[1]) * ta)
        ctx.lineTo(p1[0] + (p2[0] - p1[0]) * tb, p1[1] + (p2[1] - p1[1]) * tb)
        ctx.stroke()
      }
      // 头部光晕 + 白色亮核
      const hx = p1[0] + (p2[0] - p1[0]) * tt
      const hy = p1[1] + (p2[1] - p1[1]) * tt
      ctx.fillStyle = `rgba(${color.r},${color.g},${color.b},0.7)`
      ctx.beginPath()
      ctx.arc(hx, hy, 6, 0, Math.PI * 2)
      ctx.fill()
      ctx.fillStyle = '#ffffff'
      ctx.beginPath()
      ctx.arc(hx, hy, 2, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  const loop = () => {
    frame++
    // ★ 每 2 帧推进一次（* 与旧版一致，* 省 CPU）
    if (frame % 2 === 0) t = (t + speed) % 1
    draw()
    raf = requestAnimationFrame(loop)
  }
  raf = requestAnimationFrame(loop)

  const onResize = () => resize()
  window.addEventListener('resize', onResize)

  return () => {
    if (raf != null) cancelAnimationFrame(raf)
    window.removeEventListener('resize', onResize)
    overlay.remove()
  }
}
