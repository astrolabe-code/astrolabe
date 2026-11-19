import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, Copy, Info, Loader2, RefreshCw, Send, Trash2 } from 'lucide-react'

import { personalApi, streamCall } from '../../api/personal'
import MarkdownText from '../ui/MarkdownText'

/**
 * ★★ **问答**（顶部第五个 tab）
 *
 * 所有者原话（2026-11-17）：
 * 「顶部这一排加第五个选项，问答，就像现在的大模型厂商的网页版一样，
 *   可以让人提问，回答，记录问答历史。加一个问答历史数据的json，挂在节点上」
 * 「我说token 速率，你就只弄token速率吗？我是叫你给出全部统计信息呀」
 *
 * ## 统计口径（对齐 OpenWebUI 的 Token Usage Details）
 *
 * ```
 * Input            提示词总 token
 *   Cache hit      命中前缀缓存的部分（便宜约 10 倍）
 *   Cache miss     没命中、要重新计费的部分
 * Output           生成的总 token
 *   Thinking       推理模型的思考部分
 *   Response       实际答出来的部分
 * Cache hit rate   命中率（进度条）
 * ```
 * ⚠ 不同服务商给的字段不一样：DeepSeek 给 hit/miss，OpenAI 给 cached_tokens，
 *   Ollama 根本没有缓存概念 —— 拿不到的项就显示 0，⛔ 不猜。
 */

interface QaUsage {
  total: number
  hit: number
  miss: number
  write: number
  think: number
  response: number
}

interface QaItem {
  id: string
  q: string
  a: string
  at: string
  model: string
  tokens_in?: number
  tokens_out?: number
  ms?: number
  usage?: QaUsage
  /** ★ 思考过程（DeepSeek reasoning_content） */
  think?: string
  /** ★ 工具调用轨迹：调了什么、回来多少 */
  trace?: { name: string; chars: number; lines: number }[]
  /** ★★ 有序步骤：思考与工具调用按发生顺序交错 */
  steps?: ThinkStep[]
}

/** 一步：想了什么，或查了什么 */
type ThinkStep = {
  kind: 'think' | 'tool'
  text?: string
  name?: string
  chars?: number
  lines?: number
}

const EMPTY_USAGE: QaUsage = { total: 0, hit: 0, miss: 0, write: 0, think: 0, response: 0 }

/** 数字缩写：1234 → 1.2k */
function fmt(n: number): string {
  const v = Math.max(0, Math.round(n || 0))
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

/** 耗时：83s → 1m 23s */
function fmtMs(ms: number): string {
  const s = Math.max(0, Math.round((ms || 0) / 1000))
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

/** 缓存命中率（分母是输入总 token） */
function hitRate(u: QaUsage): number {
  const denom = u.hit + u.miss
  return denom > 0 ? u.hit / denom : 0
}

const dot: React.CSSProperties = {
  display: 'inline-block',
  width: 8,
  height: 8,
  borderRadius: 2,
  flexShrink: 0,
}

/**
 * ★★ 思考过程 + 工具调用轨迹（可折叠）。
 *
 * 所有者原话（2026-11-19）：
 * 「思考过程不要清空，还有这个可折叠的思考界面应该看到调用了哪些工具、
 *   返回了多少个值，供用户判断 ai 有没有走偏。」
 *
 * ⇒ 每条回答都有自己的 think + trace（存在 qa JSON 里），
 *   展开能看到「调了 cypher 回来 12 行、读文件 34 行…」。
 */
function ThinkBlock({
  steps,
  live,
  ms,
}: {
  steps?: ThinkStep[]
  /** 正在流式输出：自动展开，结束后自动收起 */
  live?: boolean
  /** 总耗时（毫秒），显示在标题里 */
  ms?: number
}) {
  // ★ 用户手动点过就听用户的；没点过就跟着 live 走
  const [manual, setManual] = useState<boolean | null>(null)
  const open = manual ?? Boolean(live)

  const list = steps || []
  if (!list.length) return null

  const secs = ms && ms > 0 ? Math.max(1, Math.round(ms / 1000)) : 0

  return (
    <div style={{ marginBottom: 10 }}>
      <button
        type="button"
        onClick={() => setManual((v) => !(v ?? Boolean(live)))}
        className="faint"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          fontSize: 11,
          padding: '2px 9px',
          borderRadius: 999,
          border: '1px solid var(--card-border)',
          background: 'transparent',
          color: 'var(--text-faint)',
          cursor: 'pointer',
        }}
      >
        {live && <Loader2 size={10} className="animate-spin" />}
        {live ? '思考中' : '已思考'}
        {secs > 0 && `（${secs} 秒）`}
        <span style={{ opacity: 0.6 }}>{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div
          style={{
            marginTop: 6,
            paddingLeft: 10,
            borderLeft: '2px solid var(--card-border)',
            fontSize: 11.5,
            lineHeight: 1.75,
            color: 'var(--text-faint)',
            maxHeight: 300,
            overflowY: 'auto',
          }}
        >
          {list.map((st, i) =>
            st.kind === 'tool' ? (
              <div
                key={`t${i}`}
                className="mono"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  fontSize: 10.5,
                  margin: '3px 0',
                  opacity: 0.85,
                }}
              >
                <span style={{ opacity: 0.7 }}>⌕</span>
                {st.name || '工具'}
                <span style={{ opacity: 0.55 }}>
                  · {st.lines || 0} 行 / {fmt(st.chars || 0)} 字
                </span>
              </div>
            ) : (
              <div
                key={`k${i}`}
                style={{
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  margin: '2px 0',
                }}
              >
                {st.text}
              </div>
            ),
          )}
        </div>
      )}
    </div>
  )
}

function UsageLine({ item }: { item: QaItem }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ left: number; bottom: number } | null>(null)
  const btnRef = useRef<HTMLButtonElement | null>(null)

  const u = item.usage || EMPTY_USAGE
  const tps = item.ms && item.tokens_out ? item.tokens_out / (item.ms / 1000) : 0
  const rate = hitRate(u)

  const toggle = () => {
    if (open) {
      setOpen(false)
      return
    }
    const r = btnRef.current?.getBoundingClientRect()
    if (r) {
      const W = 300
      setPos({
        left: Math.max(8, Math.min(r.left, window.innerWidth - W - 8)),
        bottom: Math.max(8, window.innerHeight - r.top + 6),
      })
    }
    setOpen(true)
  }

  const row = (color: string, label: string, value: number, muted = false) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      {color ? <span style={{ ...dot, background: color }} /> : null}
      <span className={muted ? 'faint' : undefined}>{label}</span>
      <span className="mono" style={{ marginLeft: 'auto' }}>{fmt(value)}</span>
    </div>
  )

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={toggle}
        className="faint"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 10.5,
          background: 'transparent',
          border: 0,
          padding: 0,
          cursor: 'pointer',
          color: 'var(--text-faint)',
        }}
      >
        <Info size={11} />
        {fmt(u.total || (item.tokens_in || 0) + (item.tokens_out || 0))} tok
        {u.hit + u.miss > 0 && ` · 命中 ${(rate * 100).toFixed(1)}%`}
        {tps > 0 && ` · ${tps.toFixed(1)} tok/s`}
        {!!item.ms && ` · ${fmtMs(item.ms)}`}
      </button>

      {open &&
        pos &&
        createPortal(
          <>
            {/* 点空白处关闭；⛔ 不加背景色，免得挡住阅读 */}
            <div
              onClick={() => setOpen(false)}
              style={{ position: 'fixed', inset: 0, zIndex: 9998 }}
            />
            <div
              style={{
                position: 'fixed',
                left: pos.left,
                bottom: pos.bottom,
                zIndex: 9999,
                width: 300,
                padding: '10px 12px',
                border: '1px solid var(--card-border)',
                borderRadius: 8,
                background: 'var(--card, #fff)',
                boxShadow: '0 8px 24px rgba(15,23,42,.18)',
                fontSize: 11.5,
                lineHeight: 1.9,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                <span>Token 用量</span>
                <span className="mono">{fmt(u.total)}</span>
              </div>

              <div style={{ marginTop: 6 }}>
                {row('#3b82f6', '输入', item.tokens_in || 0)}
              </div>
              <div style={{ paddingLeft: 16 }}>
                {row('#10b981', '缓存命中', u.hit, true)}
                {row('#ef4444', '缓存未命中', u.miss, true)}
                {row('#f59e0b', '缓存写入', u.write, true)}
              </div>

              <div
                style={{
                  marginTop: 6,
                  paddingTop: 6,
                  borderTop: '1px solid var(--card-border)',
                }}
              >
                {row('#a855f7', '输出', item.tokens_out || 0)}
              </div>
              <div style={{ paddingLeft: 16 }}>
                {row('', '思考', u.think, true)}
                {row('', '回答', u.response, true)}
              </div>

              {u.hit + u.miss > 0 && (
                <>
                  <div
                    style={{
                      marginTop: 8,
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontWeight: 600,
                      paddingTop: 6,
                      borderTop: '1px solid var(--card-border)',
                    }}
                  >
                    <span>⚡ 缓存命中率</span>
                    <span style={{ color: '#10b981' }}>{(rate * 100).toFixed(1)}%</span>
                  </div>
                  <div
                    style={{
                      marginTop: 4,
                      height: 6,
                      borderRadius: 3,
                      overflow: 'hidden',
                      display: 'flex',
                      background: 'var(--card-border)',
                    }}
                  >
                    <span style={{ width: `${rate * 100}%`, background: '#10b981' }} />
                    <span
                      style={{
                        width: `${(u.write / (u.hit + u.miss + u.write || 1)) * 100}%`,
                        background: '#f59e0b',
                      }}
                    />
                    <span style={{ flex: 1, background: '#ef4444' }} />
                  </div>
                  <div
                    className="faint"
                    style={{ display: 'flex', gap: 10, marginTop: 4, fontSize: 10 }}
                  >
                    <span><span style={{ ...dot, background: '#10b981' }} /> 命中</span>
                    <span><span style={{ ...dot, background: '#f59e0b' }} /> 写入</span>
                    <span><span style={{ ...dot, background: '#ef4444' }} /> 未命中</span>
                  </div>
                </>
              )}

              {item.model && (
                <div className="faint" style={{ marginTop: 6, fontSize: 10 }}>
                  模型 {item.model}
                </div>
              )}
            </div>
          </>,
          document.body,
        )}
    </>
  )
}


interface QaPanelProps {
  projectRef: string
  vid: number | null
  name?: string
}

export default function QaPanel({ projectRef, vid, name }: QaPanelProps) {
  const [items, setItems] = useState<QaItem[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [streaming, setStreaming] = useState('')
  /**
   * ★★ 正在进行的这一问。
   *
   * 所有者原话（2026-11-19）：「我输入的问题也是在回答完后，再放到问答界面上，
   * 不是问题先上界面，然后再出现思考过程，然后再回答。」
   * ⇒ 提问后先把问题气泡放上去，思考与回答依次出现在它下面；
   *   完成后由 qaAppend 返回的 items 接管，这里清空。
   */
  const [pending, setPending] = useState('')
  // ★ 思考过程（DeepSeek R1 / V3.2 的 reasoning_content），默认折叠
  // ★★ 有序步骤：想一句、查一下、再想一句，按发生顺序排
  const [steps, setSteps] = useState<ThinkStep[]>([])
  const [thinkOpen, setThinkOpen] = useState(false)
  // ★ 本轮工具调用轨迹
  const [liveMs, setLiveMs] = useState(0)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const [copiedId, setCopiedId] = useState('')
  const boxRef = useRef<HTMLDivElement | null>(null)

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
        if (live) setItems((r.items || []) as QaItem[])
      })
      .catch(() => {
        /* 读失败当空 */
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
  }, [projectRef, vid])

  useEffect(() => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items, streaming])

  // ★ 整个会话累计（OpenWebUI 顶部那三个胶囊）
  const total = useMemo(() => {
    let tok = 0
    let ms = 0
    let hit = 0
    let miss = 0
    for (const it of items) {
      tok += (it.tokens_in || 0) + (it.tokens_out || 0)
      ms += it.ms || 0
      hit += it.usage?.hit || 0
      miss += it.usage?.miss || 0
    }
    return { tok, ms, hit, miss, rate: hit + miss > 0 ? hit / (hit + miss) : 0 }
  }, [items])

  const copy = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedId(id)
      window.setTimeout(() => setCopiedId((c) => (c === id ? '' : c)), 1400)
    } catch {
      setErr('复制失败（系统未授权剪贴板）')
    }
  }

  /** 问一次；`replaceId` 有值时先删那条（「重新回答」用） */
  const ask = async (text: string, replaceId?: string): Promise<boolean> => {
    const question = text.trim()
    if (!question || busy || !vid || !projectRef) return false
    setErr('')
    setPending(question)
    setBusy(true)
    setStreaming('')
    setSteps([])
    setLiveMs(0)
    setThinkOpen(false)
    let acc = ''

    let got = false
    let tin = 0
    let tout = 0
    let usage: QaUsage = { ...EMPTY_USAGE }
    const t0 = performance.now()
    try {
      await streamCall(
        `/api/projects/${encodeURIComponent(projectRef)}/ai/ask/`,
        { vid, question },
        (evt) => {
          if (evt.event === 'delta') {
            got = true
            acc += String(evt.text ?? '')
            setStreaming(acc)
          } else if (evt.event === 'tool_use') {
            // 工具调用插在思考流中间（「想了 → 查了 → 又想了」）
            setSteps((prev) => [
              ...prev,
              {
                kind: 'tool',
                name: String(evt.name ?? ''),
                chars: Number(evt.chars ?? 0),
                lines: Number(evt.lines ?? 0),
              },
            ])
          } else if (evt.event === 'think') {
            // ⚠ 思考不算「有回答」；同一段的后续分片拼到当前那条后面
            setSteps((prev) => {
              const last = prev[prev.length - 1]
              const piece = String(evt.text ?? '')
              if (last && last.kind === 'think') {
                return [...prev.slice(0, -1), { ...last, text: (last.text || '') + piece }]
              }
              return [...prev, { kind: 'think', text: piece }]
            })
          } else if (evt.event === 'usage') {
            tin = Number(evt.in || 0)
            tout = Number(evt.out || 0)
            usage = {
              total: Number(evt.total || tin + tout),
              hit: Number(evt.hit || 0),
              miss: Number(evt.miss || 0),
              write: Number(evt.write || 0),
              think: Number(evt.think || 0),
              response: Number(evt.response || tout),
            }
          }
        },
      )
      if (!got) throw new Error('没有收到任何内容（检查 AI 设置）')
      const ms = Math.round(performance.now() - t0)
      setLiveMs(ms) // 流式结束后标题显示「已思考（N 秒）」
      if (replaceId) {
        try {
          await personalApi.qaRemove(projectRef, vid, replaceId)
        } catch {
          /* 删不掉也继续，避免整轮白问 */
        }
      }
      const r = await personalApi.qaAppend(projectRef, {
        vid,
        q: question,
        a: acc.trim(),
        tokens_in: tin,
        tokens_out: tout,
        ms,
        usage,
        steps,
      })
      setItems((r.items || []) as QaItem[])
      return true
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setBusy(false)
      setStreaming('')
      // ★ 收尾：这条已经进了 items（qaAppend 返回的新列表），
      //   撤掉临时气泡，否则会和历史里的同一条重复显示
      setPending('')
    }
  }

  const send = async () => {
    const text = q.trim()
    if (!text) return
    const ok = await ask(text)
    if (ok) setQ('')
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
            <ThinkBlock steps={it.steps} ms={it.ms} />

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

        {/* ★★ 正在进行的一问：问题先上屏 → 思考过程 → 回答 */}
        {!!pending && (
          <div style={{ marginBottom: 16 }}>
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
                {pending}
              </div>
            </div>

            <ThinkBlock steps={steps} live={busy} ms={busy ? 0 : liveMs} />

            {!!streaming && (
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
                  <MarkdownText text={streaming} compact />
                </div>
              </div>
            )}

            {busy && !streaming && !steps.length && (
              <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>
                <Loader2 size={13} className="animate-spin" /> 等待回答…
              </div>
            )}
          </div>
        )}
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
