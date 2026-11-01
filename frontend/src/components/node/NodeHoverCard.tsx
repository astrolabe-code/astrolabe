import type { GraphNode } from '../../lib/mergeGraph'
import { kindColor, kindKnown, kindLabel } from '../../lib/kindLabel'

/**
 * ★★ 鼠标悬停时的**节点浮窗**（图谱 / 节点列表共用）⚠
 *
 * 所有者原话（2026-11-01）：
 * 「不用这么复杂，图谱上，在鼠标移到相应节点时就一个浮窗，显示相应详细信息，
 *   列表哪里也是一样。还有，边如果连不准确，还不如不连，给初学者错误信息，
 *   是很不好的。gitnexus 那置信度那套只对专家或 ai 有用。」
 *
 * ## 为什么要有它
 *
 * ```
 * 重载      三个 `A.run` 在列表里长得一模一样 ⇒ 浮窗里看签名就能分清
 *            （`void run(int x)` / `void run(String s)` / `void run()`）
 * 图谱      圆点上只有个名字，细节只能点开右栏 ⇒ 悬停先看一眼，不打断阅读
 * ```
 *
 * ⚠ 只读展示：⛔ 不做任何推断、不显示"置信度"
 *   （所有者：置信度那套只对专家 / AI 有用，对初学者是噪声）
 */
interface NodeHoverCardProps {
  node: GraphNode
  /** 鼠标位置（视口坐标） */
  x: number
  y: number
}

const CARD_W = 320

export default function NodeHoverCard({ node, x, y }: NodeHoverCardProps) {
  const vw = typeof window === 'undefined' ? 1200 : window.innerWidth
  const vh = typeof window === 'undefined' ? 800 : window.innerHeight

  // ★ 贴边时翻到另一侧（否则会被视口切掉）
  const left = x + 14 + CARD_W > vw ? Math.max(8, x - CARD_W - 14) : x + 14
  const top = Math.min(y + 14, Math.max(8, vh - 140))

  const kc = kindColor(node.kind)
  const title = node.qname && node.qname !== node.name ? node.qname : node.name

  return (
    <div
      style={{
        position: 'fixed',
        left,
        top,
        zIndex: 9999,
        width: CARD_W,
        maxWidth: '80vw',
        pointerEvents: 'none', // ⛔ 不吃鼠标事件（否则浮窗会挡住 hover）
        padding: '10px 12px',
        borderRadius: 10,
        border: '1px solid var(--card-border)',
        background: 'var(--card-bg, #fff)',
        boxShadow: '0 8px 24px rgba(15,23,42,.18)',
        fontSize: 12,
        lineHeight: 1.6,
      }}
    >
      <div className="flex items-center gap-2" style={{ marginBottom: 4 }}>
        <span
          className="mono"
          style={{ fontSize: 12.5, color: 'var(--text-main)', wordBreak: 'break-word' }}
        >
          {title}
        </span>
        <span
          style={{
            fontSize: 10,
            flexShrink: 0,
            padding: '1px 6px',
            borderRadius: 999,
            lineHeight: '15px',
            color: kc,
            border: `1px ${kindKnown(node.kind) ? 'solid' : 'dashed'} ${kc}`,
          }}
        >
          {kindLabel(node.kind)}
        </span>
      </div>

      {/* ★ 签名：重载靠它区分（这就是"不用复杂方案"的那条路）⚠ */}
      {node.signature && node.signature !== node.name && (
        <div
          className="mono faint"
          style={{
            fontSize: 11,
            marginBottom: 4,
            paddingLeft: 8,
            borderLeft: '2px solid var(--card-border)',
            wordBreak: 'break-word',
          }}
        >
          {node.signature}
        </div>
      )}

      {node.file_path && (
        <div className="mono faint" style={{ fontSize: 11 }}>
          {node.file_path}:{node.line}
        </div>
      )}
    </div>
  )
}
