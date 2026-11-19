import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { RefreshCw } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { personalApi } from '../../api/personal'
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
  const [questions, setQuestions] = useState<QaQuestion[] | null>(null)
  const [asking, setAsking] = useState(false)
  /** ★ 出题的取消控制器：点「停止」时同时断浏览器 + 通知后端 */
  const abortRef = useRef<AbortController | null>(null)
  const backendTokenRef = useRef('')

  useEffect(() => {
    setQuestions(questionCache.get(node.vid) ?? null)
    setAsking(false)
  }, [node.vid])

    const ask = async (refresh = false) => {
      if (asking) return
      if (!projectRef || !node.vid) {
        setQuestions([])
        return
      }
      const ctl = new AbortController()
      abortRef.current = ctl
      backendTokenRef.current = ''
      setAsking(true)
      try {
        const r = await personalApi.aiQuestions(
          projectRef,
          { vid: Number(node.vid), refresh },
          ctl.signal,
        )
        if (r._cancelled) return // 用户已停止，别覆盖已显示的
        const items = r.items || []
        questionCache.set(node.vid, items)
        setQuestions(items)
      } catch (e) {
        // ★ 用户主动停止不弹错误；其它原因显示真实报错
        if (!(e instanceof DOMException && e.name === 'AbortError')) {
          setQuestions([
            {
              type: '简评',
              text: `出题请求失败：${e instanceof Error ? e.message : String(e)}`,
            },
          ])
        }
      } finally {
        abortRef.current = null
        setAsking(false)
      }
    }

    /** ★ 停止出题：真断后端 LLM + 断前端 fetch */
    const stop = () => {
      const token = backendTokenRef.current
      if (token && projectRef) {
        void personalApi.cancelAi(projectRef, token).catch(() => {})
      }
      abortRef.current?.abort()
      abortRef.current = null
      setAsking(false)
      // ⛔ 不清 questions：已显示的保留
    }


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

      {/* ────────────────────────── 思考题 */}
      <div
        style={{
          marginTop: 9,
          paddingTop: 8,
          borderTop: '1px dashed var(--card-border)',
        }}
      >
        {/* 还没出过题：只给按钮 */}
        {questions === null && (
          <button
            type="button"
            // ★ 出题中也可点：点它是「停止」，不是「再问一次」
            onClick={asking ? stop : () => void ask()}
            style={{
              fontSize: 11,
              lineHeight: '18px',
              padding: '2px 10px',
              borderRadius: 999,
              border: asking ? '1px solid var(--accent)' : '1px solid var(--card-border)',
              background: asking ? 'var(--accent)' : 'transparent',
              color: asking ? '#fff' : 'var(--accent)',
              cursor: 'pointer',
            }}
            >
              {asking ? '■ 停止出题' : '💭 挑战问题'}
            </button>
        )}

        {questions !== null && questions.length === 0 && (
          <div className="faint" style={{ fontSize: 10.5 }}>
            模型没有返回任何内容
          </div>
        )}

        {!!questions?.length && (
          <>
            {/* 区块标题 + 换一批 */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                marginBottom: 6,
              }}
            >
              <span
                style={{
                  fontSize: 10.5,
                  fontWeight: 600,
                  color: 'var(--text-sub)',
                  letterSpacing: '.02em',
                }}
              >
                💭 想一想
              </span>
              <button
                type="button"
                title="换一批问题"
                disabled={asking}
                onClick={() => void ask(true)}
                style={{
                  marginLeft: 'auto',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 3,
                  fontSize: 10,
                  padding: '1px 7px',
                  borderRadius: 999,
                  border: '1px solid var(--card-border)',
                  background: 'transparent',
                  color: 'var(--text-faint)',
                  cursor: asking ? 'default' : 'pointer',
                }}
              >
                <RefreshCw size={9} />
                {asking ? '出题中…' : '换一批'}
              </button>
            </div>

            {/* 每条问题一张小卡片：类型徽章 + 正文 */}
            {questions.map((q, i) => {
              const st = TYPE_STYLE[q.type] || { color: 'var(--accent)', icon: '·' }
              return (
                <div
                  key={`${i}-${q.type}`}
                  style={{
                    marginTop: i === 0 ? 0 : 6,
                    padding: '7px 9px',
                    borderRadius: 7,
                    background: 'rgba(127,127,127,.055)',
                    borderLeft: `2px solid ${st.color}`,
                  }}
                >
                  <div
                    style={{
                      fontSize: 9.5,
                      fontWeight: 600,
                      color: st.color,
                      marginBottom: 3,
                      letterSpacing: '.02em',
                    }}
                  >
                    {st.icon} {q.type}
                  </div>
                  <div
                    style={{
                      fontSize: 11.5,
                      lineHeight: 1.75,
                      color: 'var(--text-main)',
                      wordBreak: 'break-word',
                    }}
                  >
                    {inlineMd(q.text)}
                  </div>
                </div>
              )
            })}
          </>
        )}
      </div>
    </div>,
    document.body,
  )
}
