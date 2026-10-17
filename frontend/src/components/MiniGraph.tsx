import { useEffect, useRef } from 'react'
import { Graph } from '@antv/g6'
import { startMeteor } from '../lib/meteorFx'

/**
 * ★ 首页 / 演示窗的小图（`D98` · AntV G6 版）
 *
 * ## ★★ 与旧版的差别（* 不是重写需求，是引擎换了）
 *
 * | | 旧版（vis-network） | 现在（G6） |
 * |---|---|---|
 * | 引擎 | `vis-network`（* 已从依赖删除） | ★ AntV G6 ✅ |
 * | 位置 | 写死 x/y（physics:false） | ★ 同样写死 x/y（不跑布局）✅ |
 * | 流星 | 运行时包装 vis-network 私有钩子 | ★ **独立 canvas 叠加层**（`lib/meteorFx`）✅ |
 *
 * ⚠★ 位置从数据来（`style.x/y`）+ **不配 layout** —— 静态装饰图不需要力导向 ⚠
 */
export interface MiniNode {
  id: string
  label: string
  x: number
  y: number
  size?: number
  linkTo?: string
}

interface Props {
  nodes: MiniNode[]
  className?: string
  /** 流星（流光）效果（* 演示窗 / 卡片预览启用，* 相位与速度错开） */
  meteor?: { phase?: number; speed?: number }
  /** 容器可见性变化时重算尺寸（* 懒加载后尺寸从 0 → 实际） */
  active?: boolean
}

// 目录配色（与图谱页 DIR_COLORS 一致）
const DIR: Record<string, string> = {
  kernel: '#ef4444',
  'kernel/blk_drv': '#f87171',
  'kernel/chr_drv': '#ec4899',
  'kernel/math': '#f43f5e',
  fs: '#f97316',
  mm: '#22c55e',
  lib: '#eab308',
  init: '#84cc16',
  boot: '#f59e0b',
  tools: '#f59e0b',
}

const colorOf = (id: string) => DIR[id.split('/')[0]] || '#f59e0b'

export default function MiniGraph({ nodes, className, meteor, active = true }: Props) {
  const boxRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  const stopRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    const box = boxRef.current
    if (!box) return

    const edges = nodes
      .filter((n) => n.linkTo)
      .map((n, i) => ({
        id: `e${i}`,
        source: n.id,
        target: n.linkTo as string,
        style: { stroke: '#d97706', opacity: 0.9, lineWidth: 1, endArrow: true },
      }))

    const g = new Graph({
      container: box,
      autoResize: true,
      autoFit: { type: 'view' },
      animation: false,
      data: {
        nodes: nodes.map((n) => ({
          id: n.id,
          style: {
            // ★ 静态位置：来自数据（* 不跑布局）
            x: n.x,
            y: n.y,
            size: n.size || 22,
            fill: colorOf(n.id),
            stroke: colorOf(n.id),
            labelText: n.label,
            labelPlacement: 'bottom',
            labelFill: '#e2e8f0',
            labelFontSize: 9,
          },
        })),
        edges,
      },
      node: { style: { labelPlacement: 'bottom', labelFill: '#e2e8f0', labelFontSize: 9 } },
      edge: { style: { endArrow: true, lineWidth: 1 } },
      // ★ 纯装饰：* 不给交互（避免用户拖动卡片里的图）
      behaviors: [],
    })
    void g.render()
    graphRef.current = g

    const list = nodes.filter((n) => n.linkTo).map((n) => ({ from: n.id, to: n.linkTo as string }))
    let timer: number | null = null
    if (meteor && list.length > 0) {
      // ★ 等渲染完成（位置才有效）再启动流星
      timer = window.setTimeout(() => {
        stopRef.current = startMeteor(g, box, list, meteor)
      }, 120)
    }

    return () => {
      if (timer != null) window.clearTimeout(timer)
      stopRef.current?.()
      stopRef.current = null
      graphRef.current = null
      g.destroy()
    }
    // nodes 为静态演示数据,只在挂载时构建一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 从隐藏切到可见时,容器尺寸才有效 → 重算画布
  useEffect(() => {
    if (!active) return
    const id = window.setTimeout(() => graphRef.current?.resize(), 60)
    return () => window.clearTimeout(id)
  }, [active])

  return (
    <div
      ref={boxRef}
      className={className}
      style={{ width: '100%', height: '100%', position: 'relative' }}
    />
  )
}
