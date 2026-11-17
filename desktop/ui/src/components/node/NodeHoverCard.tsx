import { useEffect, useState } from 'react'
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
}

const CARD_W = 320

export default function NodeHoverCard({ node, x, y }: NodeHoverCardProps) {
  const vw = typeof window === 'undefined' ? 1200 : window.innerWidth
  const vh = typeof window === 'undefined' ? 800 : window.innerHeight
  // ★★ 从路由取项目（浮窗在图谱页和列表页都用，⛔ 不想再给两处加 prop）
  const { projectRef } = useParams<{ projectRef: string }>()

  // ★★ 思考题：**停留 1.2 秒**才请求 —— 鼠标滑过十几个节点不该烧掉十几次调用
  //   ⚠ 后端有 (节点, 模型) 缓存，同一个节点再看是 0 调用
  const [questions, setQuestions] = useState<{ type: string; text: string }[] | null>(null)
  const [asking, setAsking] = useState(false)
  const vid = node.vid
  useEffect(() => {
    setQuestions(null)
    setAsking(false)
    if (!projectRef || !vid) return
    const t = setTimeout(() => {
      setAsking(true)
      personalApi
        .aiQuestions(projectRef, { vid: Number(vid) })
        .then((r) => setQuestions(r.items || []))
        .catch(() => setQuestions([])) // ⛔ 没配模型 / 出错都不打扰，只是不显示
        .finally(() => setAsking(false))
    }, 1200)
    return () => clearTimeout(t)
  }, [projectRef, vid])

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

      {/* ★★ 思考题：只有拿到了才显示，⛔ 不显示空块（没配模型时整块不出现） */}
      {asking && (
        <div className="faint" style={{ fontSize: 10.5, marginTop: 8 }}>
          💭 想一想…
        </div>
      )}
      {!!questions?.length && (
        <div
          style={{
            marginTop: 8,
            paddingTop: 7,
            borderTop: '1px dashed var(--card-border)',
          }}
        >
          <div className="faint" style={{ fontSize: 10.5, marginBottom: 3 }}>
            💭 读这个节点时想一想
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
