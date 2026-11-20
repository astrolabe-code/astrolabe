import { useCallback, useEffect, useRef, useState } from 'react'
import { personalApi, streamCall } from '../api/personal'

/**
 * ★★ AI 问答内核（纯逻辑，零 JSX）。
 *
 * 所有者原话（2026-11-20）：
 * 「ai问答内核不能涉及一点界面上的事，只提供问答能力，停止能力等的接口。
 *   想想Linux内核，难道设计Linux内核时，还要控制图形界面如何显示吗？
 *   图形界面都是后来编写，调用内核基础能力，画的。」
 *
 * ## 内核做什么
 * · 状态：历史 items / 本轮 pending / 流式文本 / 思考步骤 / 忙碌 / 错误 / 用量
 * · 能力：ask(问一句) / stop(停止) / clear(清空历史) / reload(重读历史)
 *
 * ## 内核不做什么
 * ⛔ 不渲染任何东西、不决定输入框/按钮长什么样、不判断「挑战问题」还是「用户提问」
 * —— 那些都是 UI 层（QaPanel / NodeHoverCard）的事。
 */

export interface QaUsage {
  total: number
  hit: number
  miss: number
  write: number
  think: number
  response: number
}

export interface ThinkStep {
  kind: 'think' | 'tool'
  text?: string
  name?: string
  chars?: number
  lines?: number
}

export interface QaItem {
  id: string
  q: string
  a: string
  at: string
  model: string
  tokens_in?: number
  tokens_out?: number
  ms?: number
  usage?: QaUsage
  think?: string
  trace?: { name: string; chars: number; lines: number }[]
  steps?: ThinkStep[]
}

const EMPTY_USAGE: QaUsage = { total: 0, hit: 0, miss: 0, write: 0, think: 0, response: 0 }

export type AiScope = 'main' | 'challenge'

export function useAiChat(
  projectRef: string,
  vid: number | null,
  scope: AiScope = 'main',
) {
  const [items, setItems] = useState<QaItem[]>([])
  const [busy, setBusy] = useState(false)
  const [streaming, setStreaming] = useState('')
  /** 本轮问题（已上屏气泡，回答入库后清空） */
  const [pending, setPending] = useState('')
  const [steps, setSteps] = useState<ThinkStep[]>([])
  const [liveMs, setLiveMs] = useState(0)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  /** ★ 本轮最终条目：浮窗用它显示「最后一轮」，不读全部历史 */
  const [lastItem, setLastItem] = useState<QaItem | null>(null)

  const runRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const backendTokenRef = useRef('')

  /** 载入这个节点的历史（切节点时自动） */
  const reload = useCallback(async () => {
    if (!projectRef || !vid) {
      setItems([])
      return
    }
    let live = true
    setLoading(true)
    try {
      const r = await personalApi.qaList(projectRef, vid, scope)
      if (live) setItems((r.items || []) as QaItem[])
    } catch {
      if (live) setItems([])
    } finally {
      if (live) setLoading(false)
    }
    return () => {
      live = false
    }
  }, [projectRef, vid, scope])

  useEffect(() => {
    void reload()
  }, [reload])

  /** 切节点：作废进行中的请求 */
  useEffect(() => {
    runRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    setPending('')
    setSteps([])
    setStreaming('')
    setLastItem(null)
    setBusy(false)
  }, [vid])

  /** ★ 问一句。UI 层想问什么就传什么（用户输入的，或系统预设的「挑战问题」） */
  const ask = useCallback(
    async (
      question: string,
      replaceId?: string,
      system: 'ask' | 'questions' = 'ask',
    ): Promise<boolean> => {
      const q = String(question || '').trim()
      if (!q || busy || !vid || !projectRef) return false

      const ctl = new AbortController()
      abortRef.current = ctl
      backendTokenRef.current = ''
      setErr('')
      setPending(q)
      setBusy(true)
      setStreaming('')
      setSteps([])
      setLiveMs(0)

      const myRun = ++runRef.current
      const alive = () => runRef.current === myRun

      let acc = ''
      let stepsAcc: ThinkStep[] = []
      let sawThink = false
      let got = false
      let tin = 0
      let tout = 0
      let usage: QaUsage = { ...EMPTY_USAGE }
      const t0 = performance.now()

      const pushStep = (st: ThinkStep) => {
        stepsAcc = [...stepsAcc, st]
        if (alive()) setSteps(stepsAcc)
      }

      try {
        await streamCall(
          `/api/projects/${encodeURIComponent(projectRef)}/ai/ask/`,
          { vid, question: q, system },
          (evt) => {
            if (evt.event === 'started') {
              backendTokenRef.current = String(evt.token ?? '')
            } else if (evt.event === 'delta') {
              got = true
              acc += String(evt.text ?? '')
              if (alive()) setStreaming(acc)
            } else if (evt.event === 'tool_use') {
              pushStep({
                kind: 'tool',
                name: String(evt.name ?? ''),
                chars: Number(evt.chars ?? 0),
                lines: Number(evt.lines ?? 0),
              })
            } else if (evt.event === 'think') {
              sawThink = true
              const piece = String(evt.text ?? '')
              const last = stepsAcc[stepsAcc.length - 1]
              if (last && last.kind === 'think') {
                stepsAcc = [
                  ...stepsAcc.slice(0, -1),
                  { ...last, text: (last.text || '') + piece },
                ]
                if (alive()) setSteps(stepsAcc)
              } else {
                pushStep({ kind: 'think', text: piece })
              }
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
            } else if (evt.event === 'error') {
              throw new Error(String(evt.message || '生成失败'))
            }
          },
          ctl.signal,
        )

        if (!got) {
          if (sawThink) {
            acc = '（模型只输出了思考，没有给出回答。可能是思考把额度用完了，请重试或调高 max_tokens。）'
            setStreaming(acc)
            got = true
          } else {
            throw new Error('没有收到任何内容（检查 AI 设置）')
          }
        }

        const ms = Math.round(performance.now() - t0)
        if (alive()) setLiveMs(ms)

        // ★★ 回答一结束就留下本轮快照（供浮窗折叠块显示）。
        //   ⛔ 不依赖 qaAppend 成功 —— 入库失败时也要能折叠回看，
        //     否则 finally 清了 pending 后整个块会消失。
        if (alive()) {
          setLastItem({
            id: `local-${Date.now()}`,
            q,
            a: acc.trim(),
            at: new Date().toISOString(),
            model: '',
            tokens_in: tin,
            tokens_out: tout,
            ms,
            usage,
            steps: stepsAcc,
          })
        }

        if (replaceId) {
          try {
            await personalApi.qaRemove(projectRef, vid, replaceId, scope)
          } catch {
            /* 删不掉也继续 */
          }
        }
        const r = await personalApi.qaAppend(projectRef, {
          vid,
          q: q,
          a: acc.trim(),
          tokens_in: tin,
          tokens_out: tout,
          ms,
          usage,
          steps: stepsAcc,
          scope,
        })
        if (!alive()) return false
        const next = (r.items || []) as QaItem[]
        setItems(next)
        // ★ 最后一条就是这一轮（qaAppend 是追加，顺序稳定）
        setLastItem(next[next.length - 1] || null)
        return true
      } catch (e) {
        if (!(e instanceof DOMException && e.name === 'AbortError')) {
          if (alive()) setErr(e instanceof Error ? e.message : String(e))
        }
        return false
      } finally {
        abortRef.current = null
        backendTokenRef.current = ''
        setAiBusyGlobal(false)
        if (alive()) {
          setBusy(false)
          setStreaming('')
          setPending('')
        }
      }
    },
    [projectRef, vid, busy, scope],
  )

  /** ★ 停止：断后端 LLM + 断前端连接；已输出的内容保留 */
  const stop = useCallback(() => {
    const token = backendTokenRef.current
    if (token && projectRef) {
      void personalApi.cancelAi(projectRef, token).catch(() => {})
    }
    abortRef.current?.abort()
    abortRef.current = null
    runRef.current += 1 // 让 ask 的 finally 不清已输出内容
    setAiBusyGlobal(false)
    setBusy(false)
  }, [projectRef])

  /** ★ 只清「本轮快照」（浮窗用：换一批时清掉上一轮显示，历史仍在） */
  const clearLast = useCallback(() => setLastItem(null), [])

  /** ★ 清空这个节点的历史 */
  const clear = useCallback(async () => {
    if (!projectRef || !vid) return
    await personalApi.qaClear(projectRef, vid, scope)
    setItems([])
    setErr('')
  }, [projectRef, vid, scope])

  return {
    // 状态
    items,
    busy,
    streaming,
    pending,
    steps,
    liveMs,
    err,
    loading,
    lastItem,
    // 能力
    ask,
    stop,
    clearLast,
    clear,
    reload,
    // 给界面读的累计统计（纯派生，不渲染）
    total: (() => {
      const t = items.reduce(
        (a, it) => ({
          tok: a.tok + (it.usage?.total || it.tokens_in || 0) + (it.tokens_out || 0),
          ms: a.ms + (it.ms || 0),
          hit: a.hit + (it.usage?.hit || 0),
          miss: a.miss + (it.usage?.miss || 0),
        }),
        { tok: 0, ms: 0, hit: 0, miss: 0 },
      )
      return {
        ...t,
        rate: t.hit + t.miss > 0 ? t.hit / (t.hit + t.miss) : 0,
      }
    })(),
  }
}

/** 全应用「AI 回答中」状态（让界面层禁用跳转按钮用；内核只置位，不碰 UI） */
import { setAiBusy as setAiBusyGlobal } from './aiBusy'
