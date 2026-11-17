import { useEffect, useRef, useState } from 'react'
import { Loader2, Send, Trash2 } from 'lucide-react'

import { personalApi, streamCall } from '../../api/personal'
import MarkdownText from '../ui/MarkdownText'

/**
 * ★★ **问答**（顶部第五个 tab）
 *
 * 所有者原话（2026-11-17）：
 * 「顶部这一排加第五个选项，问答，就像现在的大模型厂商的网页版一样，
 *   可以让人提问，回答，记录问答历史。加一个问答历史数据的json，挂在节点上」
 *
 * ## 与 AskPanel 的区别
 *
 * AskPanel 是**临时弹窗**：关掉就没了，回答不落库。
 * 这里是**长期会话**：每条问答写进 `<data>/qa/<vid>.json`，下次打开还在。
 *
 * ⚠ 只保存「问题 + 完整回答」，⛔ 不存流式中间态；
 *   失败时把问题填回输入框，避免白打一遍。
 */

interface QaItem {
  id: string
  q: string
  a: string
  at: string
  model: string
}

interface QaPanelProps {
  projectRef: string
  vid: number | null
  /** 节点名，仅用于标题 */
  name?: string
}

export default function QaPanel({ projectRef, vid, name }: QaPanelProps) {
  const [items, setItems] = useState<QaItem[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [streaming, setStreaming] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const boxRef = useRef<HTMLDivElement | null>(null)

  // 换节点 ⇒ 重新拉历史（⛔ 不保留上一个节点的问答，那会张冠李戴）
  useEffect(() => {
    setItems([])
    setQ('')
    setStreaming('')
    setErr('')
    if (!projectRef || !vid) return
    let live = true
    setLoading(true)
    personalApi
      .qaList(projectRef, vid)
      .then((r) => {
        if (live) setItems(r.items || [])
      })
      .catch(() => {
        /* 读失败当空，不打扰 */
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
  }, [projectRef, vid])

  // 新内容 → 滚到底
  useEffect(() => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items, streaming])

  const send = async () => {
    const text = q.trim()
    if (!text || busy || !vid || !projectRef) return
    setQ('')
    setErr('')
    setBusy(true)
    setStreaming('')
    let acc = ''
    let got = false
    try {
      await streamCall(
        `/api/projects/${encodeURIComponent(projectRef)}/ai/ask/`,
        { vid, question: text },
        (evt) => {
          if (evt.event === 'delta') {
            got = true
            acc += String(evt.text ?? '')
            setStreaming(acc)
          }
        },
      )
      if (!got) throw new Error('没有收到任何内容（检查 AI 设置）')
      const r = await personalApi.qaAppend(projectRef, { vid, q: text, a: acc.trim() })
      setItems(r.items || [])
    } catch (e) {
      // ★ 失败把问题填回去：不然用户白打一遍
      setQ(text)
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      setStreaming('')
    }
  }

  const clearAll = async () => {
    if (!vid || !projectRef) return
    try {
      await personalApi.qaClear(projectRef, vid)
      setItems([])
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  if (!vid) {
    return <div className="faint" style={{ padding: 16, fontSize: 12 }}>先选一个节点</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* 头：标题 + 清空 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          borderBottom: '1px solid var(--card-border)',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>问答</span>
        {name && (
          <span className="mono faint" style={{ fontSize: 11 }}>
            {name}
          </span>
        )}
        <span className="faint" style={{ fontSize: 11, marginLeft: 4 }}>
          {items.length ? `${items.length} 条历史` : '还没有问答'}
        </span>
        {!!items.length && (
          <button
            type="button"
            className="tag"
            style={{ marginLeft: 'auto', fontSize: 10.5 }}
            title="清空这个节点的全部问答"
            onClick={() => void clearAll()}
          >
            <Trash2 size={10} /> 清空
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
        {!loading && !items.length && !streaming && (
          <div className="faint" style={{ fontSize: 12, lineHeight: 1.8 }}>
            就着这个节点问点什么。回答会存下来，下次打开还在。
            <br />
            比如：<span className="mono">它为什么先检查 fd？</span>
          </div>
        )}

        {items.map((it) => (
          <div key={it.id} style={{ marginBottom: 14 }}>
            {/* 问：右对齐气泡 */}
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
            {/* 答：左对齐气泡 */}
            <div style={{ display: 'flex', justifyContent: 'flex-start', marginTop: 6 }}>
              <div
                style={{
                  maxWidth: '88%',
                  padding: '6px 10px',
                  borderRadius: '10px 10px 10px 2px',
                  background: 'var(--card-bg)',
                  border: '1px solid var(--card-border)',
                  fontSize: 12.5,
                  lineHeight: 1.75,
                  wordBreak: 'break-word',
                }}
              >
                {it.a ? (
                  <MarkdownText text={it.a} compact />
                ) : (
                  <span className="faint">（没有回答）</span>
                )}
              </div>
            </div>
            <div
              className="faint"
              style={{ fontSize: 10, marginTop: 3, textAlign: 'right' }}
            >
              {it.at.replace('T', ' ')} {it.model && `· ${it.model}`}
            </div>
          </div>
        ))}

        {/* 正在流式输出 */}
        {!!streaming && (
          <div style={{ marginBottom: 14 }}>
            <div
              style={{
                padding: '6px 10px',
                borderRadius: '10px 10px 10px 2px',
                background: 'var(--card-bg)',
                border: '1px solid var(--card-border)',
                fontSize: 12.5,
                lineHeight: 1.75,
                wordBreak: 'break-word',
              }}
            >
              <MarkdownText text={streaming} compact />
            </div>
          </div>
        )}

        {busy && !streaming && (
          <div className="faint" style={{ fontSize: 12 }}>
            <Loader2 size={13} className="animate-spin" /> 思考中…
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div style={{ flexShrink: 0, padding: '8px 12px 12px', borderTop: '1px solid var(--card-border)' }}>
        {err && (
          <div style={{ fontSize: 11.5, color: 'var(--err)', marginBottom: 6 }}>{err}</div>
        )}
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <textarea
            className="input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              // Enter 发送；Shift+Enter 换行（和主流网页版一致）
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
            className="tag"
            disabled={busy || !q.trim()}
            onClick={() => void send()}
            style={{ height: 34, padding: '0 12px', display: 'inline-flex', alignItems: 'center', gap: 4 }}
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
            发送
          </button>
        </div>
      </div>
    </div>
  )
}
