/**
 * ★★ **问 AI**：针对当前节点提问（流式）
 *
 * 所有者原话（2026-11-15）：「做问答面板（/ai/ask/）…」
 *
 * ## 为什么不是一个新页面
 *
 * ```\n * 问的是「这个函数」\ 上下文就是打开着的那一个节点\n * ⇒ 就地弹窗，关掉就回到正文，⛔ 不切路由、⛔ 不丢正在写的草稿\n * ```
 *
 * ⚠ 回答**不落库**：用户看清了想留下，自己复制进正文。
 *   （自动写进笔记会让「写作进度」失真，也和 AI 草稿的 origin 标记冲突）
 */
import { useState } from 'react'

import MarkdownText from '../ui/MarkdownText'

import { streamCall } from '../../api/personal'
import Modal from '../ui/Modal'

interface Props {
  projectRef?: string | null
  /** 问的是哪个节点（`vid`） */
  vid?: number | null
  open: boolean
  onClose: () => void
}

interface Turn {
  q: string
  a: string
}

export default function AskPanel({ projectRef, vid, open, onClose }: Props) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [usage, setUsage] = useState('')

  const ask = async () => {
    const q = input.trim()
    if (!q || busy) return
    if (!projectRef || !vid) {
      setErr('缺少节点信息，无法提问')
      return
    }
    setErr('')
    setUsage('')
    setInput('')
    setTurns((ts) => [...ts, { q, a: '' }])
    setBusy(true)
    let got = false
    try {
      await streamCall(
        `/api/projects/${encodeURIComponent(projectRef)}/ai/ask/`,
        { vid, question: q },
        (evt) => {
          if (evt.event === 'delta') {
            got = true
            const piece = String(evt.text ?? '')
            setTurns((ts) => {
              if (!ts.length) return ts
              const next = ts.slice()
              const last = next[next.length - 1]
              next[next.length - 1] = { ...last, a: last.a + piece }
              return next
            })
          } else if (evt.event === 'usage') {
            setUsage(`${Number(evt.in || 0)} in / ${Number(evt.out || 0)} out`)
          }
        },
      )
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      // ★ 一个 delta 都没收到 ⇒ 明确说出来。⛔ 不能留个空回答让人以为「模型没反应」
      if (!got) setErr((prev) => prev || '没有收到任何内容（连接中断或模型未返回），请检查 AI 设置')
    }
  }

  return (
    <Modal open={open} title="问 AI" onClose={onClose} width={640}>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          maxHeight: '56vh',
          overflow: 'auto',
          paddingRight: 4,
        }}
      >
        {turns.length === 0 && (
          <div className="faint" style={{ fontSize: 12.5, lineHeight: 1.7 }}>
            问这个节点的任何事。上下文只包含：它的源码片段、它调用与被调用的函数签名。
            <br />
            例：「它在整条链路里起什么作用」「这里为什么要加锁」「失败会怎样」
          </div>
        )}
        {turns.map((t, i) => (
          <div key={`${i}-${t.q.slice(0, 8)}`}>
            <div style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>你：{t.q}</div>
            <div style={{ marginTop: 4 }}>
              {t.a ? (
                <MarkdownText text={t.a} compact />
              ) : busy && i === turns.length - 1 ? (
                <span className="faint" style={{ fontSize: 12.5 }}>…</span>
              ) : null}
            </div>
          </div>
        ))}
        {err && <div style={{ fontSize: 12, color: 'var(--err)' }}>{err}</div>}
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void ask()
            }
          }}
          placeholder="问点什么…（Enter 发送）"
          style={{ flex: 1, fontSize: 12.5 }}
        />
        <button
          type="button"
          className="tag"
          disabled={busy || !input.trim()}
          onClick={() => void ask()}
        >
          {busy ? '回答中…' : '发送'}
        </button>
      </div>

      {usage && (
        <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
          本次消耗：{usage}
        </div>
      )}
    </Modal>
  )
}
