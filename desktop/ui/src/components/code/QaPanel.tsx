import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowUp, Check, Copy, Info, Loader2, RefreshCw, Square, Trash2 } from 'lucide-react'

import { personalApi } from '../../api/personal'
import { useAiChat, type QaItem, type QaUsage } from '../../lib/useAiChat'
import MarkdownText from '../ui/MarkdownText'

/**
 * ★★ 问答区 = 界面层。所有问答能力来自 useAiChat 内核（零 JSX）；
 * 这里只画界面。浮窗用同一个 hook 画自己的界面（挑战问题按钮）。
 */

interface QaPanelProps {
  projectRef: string
  vid: number | null
  name?: string
}

type ThinkStep = {
  kind: 'think' | 'tool'
  text?: string
  name?: string
  chars?: number
  lines?: number
}

function fmt(n: number): string {
  const v = Math.max(0, Math.round(n || 0))
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}
function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}
function hitRate(u?: QaUsage): number {
  if (!u || u.hit + u.miss === 0) return 0
  return u.hit / (u.hit + u.miss)
}
const emptyUsage: QaUsage = { total: 0, hit: 0, miss: 0, write: 0, think: 0, response: 0 }

/** 思考块（纯 UI 组件） */
function ThinkBlock({ steps, live, ms }: {
  steps?: ThinkStep[]
  live?: boolean
  ms?: number
}) {
  const [manual, setManual] = useState<boolean | null>(null)
  const open = manual ?? Boolean(live)
  const list = steps || []
  if (!list.length) return null
  const secs = ms && ms > 0 ? Math.max(1, Math.round(ms / 1000)) : 0
  return (
    <div style={{ marginBottom: 10 }}>
      <button type="button" onClick={() => setManual((v) => !(v ?? Boolean(live)))}
        className="faint" style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          fontSize: 11, padding: '2px 9px', borderRadius: 999,
          border: '1px solid var(--card-border)', background: 'transparent',
          color: 'var(--text-faint)', cursor: 'pointer',
        }}>
        {live && <Loader2 size={10} className="animate-spin" />}
        {live ? '思考中' : '已思考'}
        {secs > 0 && `（${secs} 秒）`}
        <span style={{ opacity: 0.6 }}>{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div style={{
          marginTop: 6, paddingLeft: 10, borderLeft: '2px solid var(--card-border)',
          fontSize: 11.5, lineHeight: 1.75, color: 'var(--text-faint)',
          maxHeight: 300, overflowY: 'auto',
        }}>
          {list.map((st, i) => st.kind === 'tool' ? (
            <div key={`t${i}`} className="mono" style={{
              display: 'flex', alignItems: 'center', gap: 5,
              fontSize: 10.5, margin: '3px 0', opacity: 0.85,
            }}>
              <span style={{ opacity: 0.7 }}>⌕</span>
              {st.name || '工具'}
              <span style={{ opacity: 0.55 }}>· {st.lines || 0} 行 / {fmt(st.chars || 0)} 字</span>
            </div>
          ) : (
            <div key={`k${i}`} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '2px 0' }}>
              {st.text}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function UsageLine({ item }: { item: QaItem }) {
  const u = item.usage || emptyUsage
  const rate = hitRate(u)
  return (
    <span className="faint" style={{ fontSize: 10.5 }}>
      {fmt((item.tokens_in || 0) + (item.tokens_out || 0))} tok
      {rate > 0 && ` · 命中 ${(rate * 100).toFixed(1)}%`}
      {item.ms ? ` · ${fmt(item.ms)}ms` : ''}
    </span>
  )
}

export default function QaPanel({ projectRef, vid, name }: QaPanelProps) {
  const { items, busy, err, loading, total, ask, stop, clear: clearAll } =
    useAiChat(projectRef, vid)

  const [q, setQ] = useState('')
  const [copiedId, setCopiedId] = useState('')
  const boxRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items])

  const copy = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedId(id)
      window.setTimeout(() => setCopiedId((c) => (c === id ? '' : c)), 1400)
    } catch { /* 剪贴板不可用 */ }
  }

  const send = async () => {
    const text = q.trim()
    if (!text) return
    setQ('')
    const ok = await ask(text)
    if (!ok) setQ(text)
  }

  const canSend = Boolean(q.trim())
  const strong = busy || canSend

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
      }}
    >
      {/* 头：标题 + 累计统计 + 清空 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          borderBottom: '1px solid var(--card-border)',
          flexShrink: 0,
          flexWrap: 'wrap',
        }}
      >
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>问答</span>
        {name && (
          <span className="mono faint" style={{ fontSize: 11 }}>
            {name}
          </span>
        )}

        {/* ★ 累计统计：总 token / 耗时 / 命中率（对齐 OpenWebUI 的顶部胶囊） */}
                  <span
            className="faint"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 10.5,
              padding: '2px 8px',
              borderRadius: 999,
              border: '1px solid var(--card-border)',
            }}
            title="本次会话累计"
          >
            Tokens {fmt(total.tok)}
          </span>
          <span
            className="faint"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 10.5,
              padding: '2px 8px',
              borderRadius: 999,
              border: '1px solid var(--card-border)',
            }}
          >
            Elapsed {fmtMs(total.ms)}
          </span>
          {total.hit + total.miss > 0 && (
            <span
              className="faint"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontSize: 10.5,
                padding: '2px 8px',
                borderRadius: 999,
                border: '1px solid var(--card-border)',
              }}
              title="前缀缓存命中率"
            >
              Hit {(total.rate * 100).toFixed(1)}%
            </span>
          )}

        {!!items.length && (
          <button
            type="button"
            style={{
              // ★ 跟左边的三个统计胶囊用**同一套**样式：
              //   圆角药丸 / 细边框 / 淡色 / inline-flex（⛔ 不用 .tag，
              //   那会让图标与文字错位，也和这一排不搭）
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              marginLeft: 'auto',
              fontSize: 10.5,
              padding: '2px 9px',
              borderRadius: 999,
              border: '1px solid var(--card-border)',
              background: 'transparent',
              color: 'var(--text-faint)',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
            }}
            title="清空这个节点的全部问答"
            onClick={() => void clearAll()}
          >
            <Trash2 size={11} /> 清空
          </button>
        )}
      </div>

      {/* 历史 */}
      <div ref={boxRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px' }}>
        {loading && (
          <div className="faint" style={{ fontSize: 12 }}>
            <Loader2 size={13} className="animate-spin" /> 正在读取历史…
          </div>
        )}
        {!loading && !items.length && (
          <div className="faint" style={{ fontSize: 12, lineHeight: 1.8 }}>
            就着这个节点问点什么。回答会存下来，下次打开还在。
            <br />
            比如：<span className="mono">它为什么先检查 fd？</span>
          </div>
        )}

        {items.map((it) => (
          <div key={it.id} style={{ marginBottom: 16 }}>
            {/* 问 */}
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <div
                style={{
                  maxWidth: '82%',
                  padding: '6px 10px',
                  borderRadius: '10px 10px 2px 10px',
                  background: 'var(--accent)',
                  color: '#fff',
                  fontSize: 12.5,
                  lineHeight: 1.7,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {it.q}
              </div>
            </div>

            {/* ★ 思考过程在**回答上方**（所有者 2026-11-19：「折叠的思考过程
                怎么跑到回答下面了？不应该在回答上面吗？」） */}
            <ThinkBlock steps={it.steps} live={it.streaming} ms={it.ms} />

            {/* 答 */}
            <div style={{ display: 'flex', justifyContent: 'flex-start', marginTop: 6 }}>
              <div
                style={{
                  maxWidth: '88%',
                  padding: '6px 10px',
                  borderRadius: '10px 10px 10px 2px',
                  background: 'var(--card, #fff)',
                  border: '1px solid var(--card-border)',
                  fontSize: 12.5,
                  lineHeight: 1.75,
                  wordBreak: 'break-word',
                }}
              >
                {it.a ? (
                  <MarkdownText text={it.a} compact />
                ) : it.streaming ? (
                  <span className="faint">
                    <Loader2 size={11} className="animate-spin" /> 正在回答…
                  </span>
                ) : (
                  <span className="faint">（没有回答）</span>
                )}
              </div>
            </div>

            {/* ★ 操作 + 统计 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
              <button
                type="button"
                className="tag"
                style={{ fontSize: 10.5, display: 'inline-flex', alignItems: 'center', gap: 3 }}
                onClick={() => void copy(it.a, it.id)}
              >
                {copiedId === it.id ? <Check size={10} /> : <Copy size={10} />}
                {copiedId === it.id ? '已复制' : '复制'}
              </button>
              <button
                type="button"
                className="tag"
                style={{ fontSize: 10.5, display: 'inline-flex', alignItems: 'center', gap: 3 }}
                disabled={busy}
                title="用同样的问题重新问一次"
                onClick={() => void ask(it.q, it.id)}
              >
                <RefreshCw size={10} /> 重新回答
              </button>
              <UsageLine item={it} />
            </div>
          </div>
        ))}
      </div>

      {/* 输入 */}
      <div style={{ flexShrink: 0, padding: '8px 12px 12px', borderTop: '1px solid var(--card-border)' }}>
        {err && <div style={{ fontSize: 11.5, color: 'var(--err)', marginBottom: 6 }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <textarea
            className="input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            placeholder="就这个节点问点什么…（Enter 发送，Shift+Enter 换行）"
            rows={2}
            style={{ flex: 1, fontSize: 12.5, lineHeight: 1.6, resize: 'none' }}
          />
          <button
            type="button"
            onClick={busy ? stop : () => void send()}
            disabled={!busy && !q.trim()}
            style={{
              // ★★ 三态（对齐 DeepSeek 输入框，所有者截图 2026-11-19）：
                //   空输入 → 淡色、不可点
                //   有输入 → 实心强调色 + 白色箭头
                //   回答中 → 实心强调色 + 白色方块（点它停止）
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 5,
                height: 34,
                minWidth: 68,
                padding: '0 13px',
                borderRadius: 999,
                border: strong ? '1px solid var(--accent)' : '1px solid var(--card-border)',
                background: strong ? 'var(--accent)' : 'transparent',
                color: strong ? '#fff' : 'var(--text-faint)',
                cursor: canSend || busy ? 'pointer' : 'default',
                fontSize: 11.5,
                opacity: strong ? 1 : 0.45,
                whiteSpace: 'nowrap',
              }}
              title={busy ? '停止回答' : '发送（Enter）'}
            >
              {busy ? (
                <Square size={11} fill="currentColor" />
              ) : (
                <ArrowUp size={15} strokeWidth={2.2} />
              )}
              {busy ? '停止' : '发送'}
            
          </button>
        </div>
      </div>
    </div>
  )
}
