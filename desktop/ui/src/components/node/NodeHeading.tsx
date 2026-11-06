import type { ReactNode } from 'react'

import type { GraphNode } from '../../lib/mergeGraph'
import { kindColor, kindKnown, kindLabel } from '../../lib/kindLabel'

interface NodeHeadingProps {
  node: GraphNode | null
  /** 右侧追加内容（工具按钮 / 收起按钮），会靠右对齐 */
  trailing?: ReactNode
}

/**
 * ★★★ **节点头部**：颜色圆点 + 限定名 + 类型徽标，第二行是 `路径:行号`
 *
 * 两处共用这一份（⛔ 不再各画一套）：
 * ```
 * 代码工作区顶部   名称行右侧跟工具按钮（复制/文件树/沉浸/全屏）
 * 右栏节点面板     名称行右侧跟「收起节点信息」
 * ```
 * ⚠ 所有者：「只要下面那个信息就行」——所以名称行和路径行是**同一块**，
 *   不再有第二个只显示文件路径的标题行。
 */
export default function NodeHeading({ node, trailing }: NodeHeadingProps) {
  if (!node) {
    return trailing ? (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
        {trailing}
      </div>
    ) : null
  }

  const kc = kindColor(node.kind)
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
        {/* ★ 圆点 = 节点类型色（与图谱节点、列表徽标同源） */}
        <span
          style={{ width: 10, height: 10, borderRadius: '50%', background: kc, flexShrink: 0 }}
        />
        <span
          className="mono"
          style={{
            fontSize: 14,
            fontWeight: 600,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={node.qname || node.name}
        >
          {node.name}
        </span>
        <span
          style={{
            fontSize: 10,
            flexShrink: 0,
            padding: '1px 7px',
            borderRadius: 999,
            lineHeight: '16px',
            // ★ 只有文字色 + 同色边框，背景透明（照原型 .code-panel-type）
            color: kc,
            border: `1px ${kindKnown(node.kind) ? 'solid' : 'dashed'} ${kc}`,
            background: 'transparent',
          }}
        >
          {kindLabel(node.kind)}
        </span>
        {trailing && (
          <div
            style={{
              marginLeft: 'auto',
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            {trailing}
          </div>
        )}
      </div>

      {node.file_path && (
        <div
          className="faint mono"
          style={{
            fontSize: 11,
            paddingLeft: 16,
            marginTop: 2,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={`${node.file_path}:${node.line}`}
        >
          {node.file_path}:{node.line}
        </div>
      )}
    </div>
  )
}
