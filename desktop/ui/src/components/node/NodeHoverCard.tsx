import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useParams } from 'react-router-dom'

import { personalApi } from '../../api/personal'

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
  /** ★ 鼠标进入浮窗（让画布别急着关掉它，否则按钮点不到） */
  onEnter?: () => void
  /** ★ 鼠标离开浮窗（这时才真的可以关了） */
  onLeave?: () => void
}

const CARD_W = 320

export default function NodeHoverCard({ node, x, y, onEnter, onLeave }: NodeHoverCardProps) {
  const vw = typeof window === 'undefined' ? 1200 : window.innerWidth
  const vh = typeof window === 'undefined' ? 800 : window.innerHeight
  // ★★ 从路由取项目（浮窗在图谱页和列表页都用，⛔ 不想再给两处加 prop）
  const { projectRef } = useParams<{ projectRef: string }>()

  // ★★ 思考题：**用户点按钮才生成** ⛔ 不自动请求
  //   所有者原话（2026-11-17）：「不要停1.2S，在这个弹窗里做个挑战问题的按钮，
  //   用户按了，才ai生成问题」——hover 只是浏览，调用要由用户明确发起。
  const [questions, setQuestions] = useState<{ type: string; text: string }[] | null>(null)
  const [asking, setAsking] = useState(false)
  const ask = async () => {
    if (asking) return
    if (!projectRef || !node.vid) {
      setQuestions([])
      return
    }
    setAsking(true)
    try {
      const r = await personalApi.aiQuestions(projectRef, { vid: Number(node.vid) })
      setQuestions(r.items || [])
    } catch {
      setQuestions([]) // ⛔ 没配模型 / 出错都不打扰
    } finally {
      setAsking(false)
    }
  }

  // ★ 贴边时翻到另一侧（否则会被视口切掉）
  const left = x + 14 + CARD_W > vw ? Math.max(8, x - CARD_W - 14) : x + 14
  const top = Math.min(y + 14, Math.max(8, vh - 260))

  const kc = kindColor(node.kind)
  const title = node.qname && node.qname !== node.name ? node.qname : node.name

  // ★★★ 2026-11-05：**必须 portal 到 body** ⚠
  //   所有者：「提示信息被笔记卡片盖住了，不应该是提示信息盖住笔记卡片吗？」
  //   ⚠ 根因不是 z-index 不够（已经是 9999），而是它被**祖先的层叠上下文**关住了：
  //     flex 栏 + 滚动容器 + `.page.rise` 的 transform ⇒ 再高的 z-index 也出不去
  //   ⇒ 挂到 body，层级才与右栏处在同一层（与 Modal 踩过的是同一个坑）
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
        maxWidth: '80vw',
        // ★ 现在要能点「挑战问题」⇒ 吃鼠标事件；画布那边用延迟 150ms 的方式
        //   判断鼠标是不是进了浮窗，进了就不关掉它（见 GraphCanvas 的 onLeave）
        pointerEvents: 'auto',
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

      {/* ★★ 挑战问题：用户点了才调用（⛔ 不自动烧 token） */}
      <div
        style={{
          marginTop: 8,
          paddingTop: 7,
          borderTop: '1px dashed var(--card-border)',
        }}
      >
        {questions === null && (
          <button
            type="button"
            onClick={() => void ask()}
            disabled={asking}
            style={{
              fontSize: 11,
              lineHeight: '18px',
              padding: '2px 10px',
              borderRadius: 999,
              border: '1px solid var(--card-border)',
              background: 'transparent',
              color: 'var(--accent)',
              cursor: asking ? 'default' : 'pointer',
            }}
          >
            {asking ? '出题中…' : '💭 挑战问题'}
          </button>
        )}
        {questions !== null && questions.length === 0 && (
          <div className="faint" style={{ fontSize: 10.5 }}>
            这次没出题（检查 AI 设置）
          </div>
        )}
      </div>

      {!!questions?.length && (
        <div
          style={{
            marginTop: 8,
            paddingTop: 7,
            borderTop: '1px dashed var(--card-border)',
          }}
        >
          <div className="faint" style={{ fontSize: 10.5, marginBottom: 3 }}>
            💭 想一想
          </div>
          {questions.map((q, i) => (
            <div
              key={`${i}-${q.type}`}
              // ⚠ 浮窗是 pointerEvents:none（鼠标一移开就消失）⇒ 每条限两行，
              //   让用户扫一眼就能抓住关键词；完整内容点节点看右栏
              style={{
                fontSize: 11,
                lineHeight: 1.65,
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }}
            >
              <span style={{ color: 'var(--accent)' }}>{q.type}</span>
              <span className="faint"> · </span>
              {q.text}
            </div>
          ))}
        </div>
      )}
    </div>,
    document.body,
  )
}
