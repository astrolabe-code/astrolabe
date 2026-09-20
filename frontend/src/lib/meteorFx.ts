/**
 * vis-network 流星(流光)效果 —— 旧站 vis_flow_fx.js 的等价重写
 *
 * 层序(关键):旧站用的是**打过补丁的** vis-network(vendored 版内含 `window.__visFlowLayer`
 *   钩子,绘制顺序为 drawEdges → 流星 → drawNodes)。npm 版 vis-network v10 没有该钩子,
 *   但其 CanvasRenderer._draw 的调用序列是:
 *     beforeDrawing → _drawEdges → _drawNodes → afterDrawing   (见 v10 源码 2989/3000/3008/3034)
 *   因此这里在**运行时包装** `renderer._drawNodes`:先画流星,再调用原方法 ——
 *   既得到"边 → 流星 → 节点"的正确层序(节点不会被流星盖住),又不修改 node_modules,
 *   且 stop() 时原样还原。若未来内部结构变化导致包装失败,自动退回 afterDrawing(画在最上层)。
 *
 * 行为保持:尾迹 0.2 长度 / 6 段采样 / 头部光晕 + 白色亮核;
 *           拖拽暂停、缩放暂停 120ms、每 2 帧推进一次、边数 >150 抽样。
 */
import type { Network } from 'vis-network'

export interface MeteorOptions {
  /** 初始相位 0~1(多图谱错开) */
  phase?: number
  /** 每步推进量,默认 0.008 */
  speed?: number
}

interface Layer {
  network: Network
  edgeIds: string[]
  t: number
  speed: number
  paused: boolean
  raf: number | null
  frame: number
  color: { r: number; g: number; b: number } | null
}

const TRAIL = 0.2
const SEGS = 6
const MAX_EDGES = 150

/** 读取主题色 --fx-dot(旧站未定义该变量,回退 #38bdf8,保持 1:1) */
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
  return { r: 56, g: 189, b: 248 } // #38bdf8
}

function draw(layer: Layer, ctx: CanvasRenderingContext2D) {
  if (layer.paused || !layer.edgeIds.length) return
  if (!layer.color) layer.color = readFxColor()
  const fc = layer.color
  const body = (layer.network as any).body
  if (!body) return

  const n = layer.edgeIds.length
  for (let i = 0; i < n; i++) {
    const ev = body.edges[layer.edgeIds[i]]
    if (!ev || !ev.edgeType) continue

    const t = (layer.t + i / n) % 1
    const pts: { x: number; y: number }[] = []
    try {
      for (let k = 0; k <= SEGS; k++) {
        const tk = t - TRAIL + (TRAIL * k) / SEGS
        if (tk < 0) continue // 尾迹不越过源节点
        const p = ev.edgeType.getPoint(tk)
        if (!p) break
        pts.push(p)
      }
    } catch (e) {
      continue
    }
    if (pts.length < 2) continue

    // 尾迹:逐段描线,透明度/线宽向尾部渐减
    for (let k = 1; k < pts.length; k++) {
      const f = k / (pts.length - 1)
      ctx.strokeStyle = `rgba(${fc.r},${fc.g},${fc.b},${(0.25 + 0.6 * f).toFixed(2)})`
      ctx.lineWidth = 2 + 2.2 * f
      ctx.beginPath()
      ctx.moveTo(pts[k - 1].x, pts[k - 1].y)
      ctx.lineTo(pts[k].x, pts[k].y)
      ctx.stroke()
    }

    // 流星头部:光晕 + 白色亮核
    const head = pts[pts.length - 1]
    ctx.fillStyle = `rgba(${fc.r},${fc.g},${fc.b},0.7)`
    ctx.beginPath()
    ctx.arc(head.x, head.y, 6, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = 'rgba(255,255,255,0.95)'
    ctx.beginPath()
    ctx.arc(head.x, head.y, 2.8, 0, Math.PI * 2)
    ctx.fill()
  }
}

/**
 * 启动流星效果;返回停止函数。
 * @param network vis-network 实例
 * @param edgeIds 参与流星的边 id
 */
export function startMeteor(
  network: Network,
  edgeIds: (string | number)[],
  opts: MeteorOptions = {},
): () => void {
  const ids = edgeIds.slice(0, MAX_EDGES).map(String)
  if (!ids.length) return () => {}

  const layer: Layer = {
    network,
    edgeIds: ids,
    t: (opts.phase ?? 0) % 1,
    speed: opts.speed ?? 0.008,
    paused: false,
    raf: null,
    frame: 0,
    color: null,
  }

  const onAfterDrawing = (ctx: CanvasRenderingContext2D) => draw(layer, ctx)
  const onDragStart = () => {
    layer.paused = true
  }
  const onDragEnd = () => {
    layer.paused = false
  }
  const onZoom = () => {
    layer.paused = true
    window.setTimeout(() => {
      layer.paused = false
    }, 120)
  }

  // 首选:包装 renderer._drawNodes,把流星插在「边之后、节点之前」(与旧站层序一致)
  const renderer: any = (network as any).renderer
  const origDrawNodes: ((ctx: CanvasRenderingContext2D, alwaysShow?: boolean) => unknown) | undefined =
    renderer && typeof renderer._drawNodes === 'function' ? renderer._drawNodes : undefined
  const usingPatch = !!origDrawNodes
  if (usingPatch) {
    renderer._drawNodes = function (this: unknown, ctx: CanvasRenderingContext2D, alwaysShow?: boolean) {
      draw(layer, ctx)
      return origDrawNodes!.call(this, ctx, alwaysShow)
    }
  } else {
    // 兜底:内部结构变化时至少保证流星可见(代价:画在节点上层)
    network.on('afterDrawing', onAfterDrawing)
  }

  network.on('dragStart', onDragStart)
  network.on('dragEnd', onDragEnd)
  network.on('zoom', onZoom)

  const loop = () => {
    // 每 2 帧推进一次,降频保帧率;页面切后台时暂停
    if (layer.frame++ % 2 === 0) {
      if (!layer.paused && !document.body.classList.contains('page-hidden')) {
        layer.t = (layer.t + layer.speed) % 1
        const body = (network as any).body
        // 优先走 vis 内部请求重绘(便宜);每 10 帧兜底一次强制重绘
        if (body?.emitter) {
          try {
            body.emitter.emit('_allowRedraw')
          } catch (e) {
            /* 内部 API 不可用则忽略 */
          }
          try {
            body.emitter.emit('_requestRedraw')
          } catch (e) {
            /* 同上 */
          }
        }
        if (layer.frame % 20 === 0) {
          try {
            network.redraw()
          } catch (e) {
            console.error('network.redraw failed', e)
          }
        }
      }
    }
    layer.raf = window.requestAnimationFrame(loop)
  }
  layer.raf = window.requestAnimationFrame(loop)

  return () => {
    if (layer.raf !== null) window.cancelAnimationFrame(layer.raf)
    if (usingPatch) {
      renderer._drawNodes = origDrawNodes // 原样还原,避免影响其它实例
    } else {
      network.off('afterDrawing', onAfterDrawing)
    }
    network.off('dragStart', onDragStart)
    network.off('dragEnd', onDragEnd)
    network.off('zoom', onZoom)
  }
}
