/**
 * ★★ 鼠标悬停在**聚合边**上时的浮窗
 *
 * 所有者原话（2026-11-14）：
 * 「前端展示的时候聚合，就是和节点展示的时候一样，鼠标移到边上时，
 *   弹出一个展示详细信息的窗口，这样两点之间多边就没问题了」
 *
 * 图上两点之间只画一条线，但底下可能有多条不同属性（类型/方向/行号/来源）的边；
 * 这里把 `details` 里每一条都列出来，用户点改图面板能逐条改、逐条删。
 *
 * ⚠ 与 NodeHoverCard 一样 portal 到 body —— 否则会被 flex 栏 / transform
 *   的层叠上下文关住，z-index 再高也盖不住笔记卡片。
 */
import { createPortal } from 'react-dom'

import type { EdgeDetail, GraphEdge } from '../../lib/mergeGraph'

interface Props {
  edge: GraphEdge
  /** 鼠标位置（视口坐标） */
  x: number
  y: number
}

const CARD_W = 330

export default function EdgeHoverCard({ edge, x, y }: Props) {
  const details: EdgeDetail[] = edge.details?.length
    ? edge.details
    : [
        {
          from: edge.from,
          to: edge.to,
          type: edge.type,
          origin: edge.origin,
          line: edge.line ?? 0,
        },
      ]

  const vw = typeof window === 'undefined' ? 1200 : window.innerWidth
  const vh = typeof window === 'undefined' ? 800 : window.innerHeight
  const left = x + 14 + CARD_W > vw ? Math.max(8, x - CARD_W - 14) : x + 14
  const top = Math.min(y + 14, Math.max(8, vh - 70 - details.length * 26))

  return createPortal(
    <div
      style={{
        position: 'fixed',
        left,
        top,
        zIndex: 9999,
        width: CARD_W,
        maxWidth: '80vw',
        pointerEvents: 'none',
        padding: '10px 12px',
        borderRadius: 10,
        border: '1px solid var(--card-border)',
        background: 'var(--card-bg, #fff)',
        boxShadow: '0 8px 24px rgba(15,23,42,.18)',
        fontSize: 12,
        lineHeight: 1.6,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6 }}>
        两点之间共 {details.length} 条关系
      </div>
      {details.map((d, i) => {
        const sameDir = d.from === edge.from && d.to === edge.to
        return (
          <div
            key={`${d.from}-${d.to}-${d.type}-${d.line}-${i}`}
            className="flex items-center gap-2"
            style={{ padding: '2px 0', color: 'var(--text-sub)' }}
          >
            <span className="mono" style={{ color: 'var(--text-main)', minWidth: 68 }}>
              {d.type}
            </span>
            <span style={{ minWidth: 28 }}>{sameDir ? '同向' : '反向'}</span>
            <span>第 {d.line} 行</span>
            <span className="faint" style={{ marginLeft: 'auto' }}>
              {d.origin === 'manual' ? '人工补' : '解析'}
            </span>
          </div>
        )
      })}
    </div>,
    document.body,
  )
}
