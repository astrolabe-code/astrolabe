import { useEffect, useRef } from 'react'
import { DataSet, Network } from 'vis-network/standalone'
import type { Edge, Node } from 'vis-network'
import { startMeteor } from '../lib/meteorFx'

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
  /** 是否启用流星(流光)效果(演示窗口/卡片预览都启用,相位与速度错开) */
  meteor?: { phase?: number; speed?: number }
  /** 容器可见性变化时重新适配画布(懒加载后尺寸从 0 → 实际) */
  active?: boolean
}

// 目录配色(与图谱页 DIR_COLORS 一致)
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
  const netRef = useRef<Network | null>(null)
  const stopRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    const box = boxRef.current
    if (!box) return

    const visNodes = new DataSet<Node>(
      nodes.map((n) => ({
        id: n.id,
        label: n.label,
        x: n.x,
        y: n.y,
        color: { background: colorOf(n.id), border: colorOf(n.id) },
        font: { color: '#ffffff', size: 13, strokeWidth: 3, strokeColor: '#1e293b', face: 'PingFang SC, Microsoft YaHei' },
        shape: 'dot',
        size: n.size || 22,
      })),
    )
    const visEdges = new DataSet<Edge>(
      nodes
        .filter((n) => n.linkTo)
        .map((n, i) => ({
          id: `e${i}`,
          from: n.id,
          to: n.linkTo as string,
          color: { color: '#d97706', opacity: 0.9 },
          arrows: { to: { enabled: true, scaleFactor: 0.7 } },
          smooth: { enabled: true, type: 'dynamic' as const, roundness: 0.5 },
        })),
    )

    const network = new Network(
      box,
      { nodes: visNodes, edges: visEdges },
      {
        physics: false,
        interaction: { hover: true, tooltipDelay: 100, navigationButtons: false, keyboard: false },
        edges: { smooth: { enabled: true, type: 'dynamic', roundness: 0.5 } },
      },
    )
    netRef.current = network

    if (meteor) {
      stopRef.current = startMeteor(network, visEdges.getIds(), meteor)
    }

    const onResize = () => network.redraw()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      stopRef.current?.()
      network.destroy()
      netRef.current = null
    }
    // nodes 为静态演示数据,只在挂载时构建一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 从隐藏切到可见时,容器尺寸才有效 → 重新适配
  useEffect(() => {
    if (!active) return
    const id = window.setTimeout(() => netRef.current?.fit({ animation: false }), 60)
    return () => window.clearTimeout(id)
  }, [active])

  return <div ref={boxRef} className={className} style={{ width: '100%', height: '100%' }} />
}
