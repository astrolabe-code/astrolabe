import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, Square } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { useAiChat, type QaItem, type ThinkStep } from '../../lib/useAiChat'

import type { GraphNode } from '../../lib/mergeGraph'
import { kindColor, kindKnown, kindLabel } from '../../lib/kindLabel'

/**
 * ★★ 鼠标悬停时的**节点浮窗**（图谱 / 节点列表共用）
 *
 * 所有者原话（2026-11-01）：
 * 「不用这么复杂，图谱上，在鼠标移到相应节点时就一个浮窗，显示相应详细信息，
 *   列表哪里也是一样。还有，边如果连不准确，还不如不连，给初学者错误信息，
 *   是很不好的。gitnexus 那置信度那套只对专家或 ai 有用。」
 *
 * ## 思考题（2026-11-17 追加）
 *
 * 「点开一个节点，就要根据这个节点涉及到的知识提问」——
 * 问题由后端 `/ai/questions/` 生成（带上下文、引用用户写过的话）。
 *
 * 三条交互约束（都来自所有者原话）：
 * ```
 * ① 位置：朝右下（弹窗方向）走 ⇒ 定住，方便移过去点按钮；其余方向跟随
 * ② 记忆：同一个节点出过题 ⇒ 再次悬停直接显示，⛔ 不用再点一次
 * ③ 换一批：已显示时底部给一个刷新按钮，重新请模型出题
 * ```
 */

interface NodeHoverCardProps {
  node: GraphNode
  /** 鼠标位置（视口坐标） */
  x: number
  y: number
  /** 鼠标进入浮窗（让画布别急着关掉它，否则按钮点不到） */
  onEnter?: () => void
  /** 鼠标离开浮窗（这时才真的可以关了） */
  onLeave?: () => void
}

interface QaQuestion {
  type: string
  text: string
}

/**
 * ★ 已出过题的节点：再次悬停**直接显示**，不再请求、也不用再点按钮。
 *   ⚠ 模块级 Map（不持久化）：后端也有缓存，但那是「0 次调用、仍要走一次 IPC」，
 *     这里存一份纯前端副本，悬停瞬间就能显示。
 */
const questionCache = new Map<number, QaQuestion[]>()

/** 挑战问题：前端把系统预设问题灌进内核，省略用户输入那一步 */
const CHALLENGE_Q = '请根据这个节点，提出几个值得思考的问题（陷阱 / 优化 / 背景），并给出下一步可以读的节点。'

const CARD_W = 440

/** 行内 markdown：只处理反引号 `` `code` `` */
function inlineMd(text: string): ReactNode[] {
  return String(text || '')
    .split('`')
    .map((part, i) =>
      i % 2 === 1 ? (
        <code
          key={i}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.94em',
            padding: '0 3px',
            borderRadius: 3,
            background: 'rgba(127,127,127,.16)',
            wordBreak: 'break-word',
          }}
        >
          {part}
        </code>
      ) : (
        part
      ),
    )
}

/** 三类问题的视觉区分：颜色 + 一句话说明 */
const TYPE_STYLE: Record<string, { color: string; icon: string }> = {
  陷阱: { color: '#ef4444', icon: '⚠' },
  优化: { color: '#3b82f6', icon: '⚡' },
  背景: { color: '#a855f7', icon: '📖' },
  // 「没什么可问」时的一条说明（不是问题，用灰一点的颜色）
  简评: { color: 'var(--text-faint)', icon: '💡' },
}

export default function NodeHoverCard({ node, x, y, onEnter, onLeave }: NodeHoverCardProps) {
  const vw = typeof window === 'undefined' ? 1200 : window.innerWidth
  const vh = typeof window === 'undefined' ? 800 : window.innerHeight
  const { projectRef } = useParams<{ projectRef: string }>()

  // 就跟着鼠标：⛔ 不做位置裁剪（超出屏幕就超出，往左上移自然回来）
  const left = x + 14 + CARD_W > vw ? Math.max(8, x - CARD_W - 14) : x + 14
  const top = y + 14

  // ★ 有缓存就直接显示（②）；没缓存才是 null（显示按钮）
  // ★ 问答内核（纯逻辑）：浮窗界面自己决定「挑战问题」怎么画、怎么调
  const chat = useAiChat(projectRef || '', node.vid)
  const { items, busy, streaming, pending, steps, err, ask, stop } = chat
  const kc = kindColor(node.kind)
  const title = node.qname && node.qname !== node.name ? node.qname : node.name

  // ★★★ 必须 portal 到 body：否则会被祖先的层叠上下文关住（flex + transform）
  return createPortal(
    <div
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={{
        position: 'fixed',
        left,
        top,
        zIndex: 9999,
        width: CARD_W,
        maxWidth: '92vw',
        // 内容长了给个上限 + 滚动条（滑块）
        maxHeight: '72vh',
        overflowY: 'auto',
        overscrollBehavior: 'contain',
        padding: '10px 12px',
        borderRadius: 10,
        border: '1px solid var(--card-border)',
        background: 'var(--card, #fff)',
        boxShadow: '0 8px 24px rgba(15,23,42,.18)',
        fontSize: 12,
        lineHeight: 1.6,
        pointerEvents: 'auto',
      }}
    >
      {/* 标题行 */}
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

      {/* 签名 */}
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

      {node.rel_path && (
        <div className="mono faint" style={{ fontSize: 11 }}>
          {node.rel_path}:{node.line}
        </div>
      )}

        {/* ★★ 浮窗自己的界面：直接调内核 ask/stop；内核不知道「挑战问题」 */}
        <div style={{ marginTop: 10, borderTop: '1px dashed var(--card-border)' }}>
          {err && <div style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 6 }}>{err}</div>}

          {items.map((it: QaItem) => (
            <div key={it.id} style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)', textAlign: 'right' }}>{it.q}</div>
              {!!it.steps?.length && (
                <details style={{ marginTop: 3, fontSize: 10, opacity: 0.65 }}>
                  <summary>思考过程</summary>
                  {it.steps.map((st: ThinkStep, i: number) => (
                    <div key={i} style={{ whiteSpace: 'pre-wrap' }}>
                      {st.kind === 'tool' ? `⌕ ${st.name} · ${st.lines || 0} 行` : st.text}
                    </div>
                  ))}
                </details>
              )}
              <div style={{ fontSize: 11, lineHeight: 1.65, marginTop: 3, whiteSpace: 'pre-wrap' }}>{it.a}</div>
            </div>
          ))}

          {!!pending && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)', textAlign: 'right' }}>{pending}</div>
              {!!steps.length && (
                <div style={{ fontSize: 10, opacity: 0.6, marginTop: 3, whiteSpace: 'pre-wrap' }}>
                  {steps.map((st: ThinkStep, i: number) => (
                    <div key={i}>{st.kind === 'tool' ? `⌕ ${st.name}` : st.text}</div>
                  ))}
                </div>
              )}
              {!!streaming && (
                <div style={{ fontSize: 11, lineHeight: 1.65, marginTop: 3, whiteSpace: 'pre-wrap' }}>{streaming}</div>
              )}
            </div>
          )}

          <button
            type="button"
            onClick={() => (busy ? stop() : void ask(CHALLENGE_Q))}
            style={{
              width: '100%', height: 30, marginTop: 8, borderRadius: 999,
              border: '1px solid var(--accent)',
              background: busy ? 'var(--accent)' : 'transparent',
              color: busy ? '#fff' : 'var(--accent)',
              cursor: 'pointer', fontSize: 11.5,
            }}
          >
            {busy ? <><Square size={10} fill="currentColor" /> 停止</> : '💭 挑战问题'}
          </button>
        </div>
      </div>,
    document.body,
  )
}
