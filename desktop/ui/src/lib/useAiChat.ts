import { useCallback, useEffect, useRef, useState } from 'react'
import { personalApi, streamCall } from '../api/personal'
import { setAiBusy as setAiBusyGlobal } from './aiBusy'

/**
 * ★★ AI 问答内核（纯逻辑，零 JSX）。
 *
 * 所有者原话（2026-11-20）：
 * 「ai问答内核不能涉及一点界面上的事，只提供问答能力，停止能力等的接口。
 *   想想Linux内核，难道设计Linux内核时，还要控制图形界面如何显示吗？」
 * 「对，就仿照 openwebui，前端生成 id 就行了，后端用，就行了。」
 * 「嗯，对呀，就是消息列表，为什么还要两套设计？」
 *
 * ## 核心：一个消息列表（OpenWebUI 风格）
 * ask() 一开头就把一条**乐观消息**插进 items（前端生成 id、a 为空、
 * streaming=true），后续每个事件就地更新那一条：
 *   delta     → it.a += 文本
 *   think     → it.steps 追加/拼接
 *   tool_use  → it.steps 追加
 *   done      → qaAppend 用同一个 id 入库，后端返回列表整体替换
 *
 * ⛔ 没有 pending / streaming / steps / lastItem 这些独立状态 ——
 *   那些是「历史区 + 临时区」两套设计的产物，这正是要消除的东西。
 *
 * ## 内核不做什么
 * 不渲染、不决定按钮/输入框长什么样、不判断「挑战问题」还是「用户提问」。
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
  /** ★ 仅前端：这一条正在流式生成（后端不会存这个字段） */
  streaming?: boolean
}

const EMPTY_USAGE: QaUsage = { total: 0, hit: 0, miss: 0, write: 0, think: 0, response: 0 }

export type AiScope = 'main' | 'challenge'

/** 前端生成消息 id（OpenWebUI 风格：请求发出前就有，全程不变） */
function newMessageId(): string {
  return `m-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export function useAiChat(
  projectRef: string,
  vid: number | null,
  scope: AiScope = 'main',
  /** ★ false = 不读历史（浮窗用：只显示本次打开期间 generated 的消息） */
  loadHistory = true,
) {
  const [items, setItems] = useState<QaItem[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  const runRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const backendTokenRef = useRef('')
  /** 当前正在流式的那条消息 id（停止时用它把 streaming 标记去掉） */
  const currentIdRef = useRef('')

  /** 载入这个节点的历史（切节点时自动） */
  const reload = useCallback(async () => {
    if (!loadHistory || !projectRef || !vid) {
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
  }, [projectRef, vid, scope, loadHistory])

  useEffect(() => {
    void reload()
  }, [reload])

  /** 切节点：作废进行中的请求 */
  useEffect(() => {
    runRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    currentIdRef.current = ''
    setBusy(false)
  }, [vid])

  /**
   * ★ 问一句。UI 层想问什么就传什么（用户输入的，或系统预设的「挑战问题」）。
   * @returns 这条消息的 id（成功）；失败返回空串
   */
  const ask = useCallback(
    async (
      question: string,
      replaceId?: string,
      system: 'ask' | 'questions' = 'ask',
    ): Promise<string> => {
      const q = String(question || '').trim()
      if (!q || busy || !vid || !projectRef) return ''

      // ★ 前端生成 id —— 这条消息从这一刻起就在列表里，全程不换 id
      const id = newMessageId()
      currentIdRef.current = id

      const optimistic: QaItem = {
        id,
        q,
        a: '',
        at: new Date().toISOString(),
        model: '',
        steps: [],
        streaming: true,
      }
      // 「重新回答」：新消息顶掉旧的那条（前端立刻移除，后端稍后删）
      setItems((prev) => [...prev.filter((x) => x.id !== replaceId), optimistic])
      setErr('')
      setBusy(true)

      const ctl = new AbortController()
      abortRef.current = ctl
      backendTokenRef.current = ''
      const myRun = ++runRef.current
      const alive = () => runRef.current === myRun

      /** 就地更新这一条消息（不碰其它消息） */
      const patch = (fn: (it: QaItem) => QaItem) => {
        if (!alive()) return
        setItems((prev) => prev.map((it) => (it.id === id ? fn(it) : it)))
      }

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
        patch((it) => ({ ...it, steps: stepsAcc }))
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
              patch((it) => ({ ...it, a: acc }))
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
                patch((it) => ({ ...it, steps: stepsAcc }))
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
            patch((it) => ({ ...it, a: acc }))
            got = true
          } else {
            throw new Error('没有收到任何内容（检查 AI 设置）')
          }
        }

        const ms = Math.round(performance.now() - t0)

        if (replaceId) {
          try {
            await personalApi.qaRemove(projectRef, vid, replaceId, scope)
          } catch {
            /* 删不掉也继续 */
          }
        }

        // ★ 后端用前端传来的同一个 id 入库 ⇒ 不需要换 id、不需要搬移消息
        const r = await personalApi.qaAppend(projectRef, {
          id,
          vid,
          q,
          a: acc.trim(),
          tokens_in: tin,
          tokens_out: tout,
          ms,
          usage,
          steps: stepsAcc,
          scope,
        })
        if (!alive()) return id
        if (loadHistory) {
          // 问答 tab：用后端返回的完整列表（同一批 id，消息没被搬移）
          setItems(((r.items || []) as QaItem[]).map((it) => ({ ...it, streaming: false })))
        } else {
          // 浮窗：不读历史 ⇒ 只把本轮那条标记为已完成，不引入后端历史
          patch((it) => ({ ...it, streaming: false }))
        }
        currentIdRef.current = ''
        return id
      } catch (e) {
        if (!(e instanceof DOMException && e.name === 'AbortError')) {
          if (alive()) {
            const msg = e instanceof Error ? e.message : String(e)
            setErr(msg)
            // ★ 失败也留在列表里：这条消息本来就在，标上错误即可
            patch((it) => ({ ...it, a: it.a || `（失败：${msg}）`, streaming: false }))
          }
        }
        return ''
      } finally {
        abortRef.current = null
        backendTokenRef.current = ''
        setAiBusyGlobal(false)
        if (alive()) setBusy(false)
      }
    },
    [projectRef, vid, busy, scope, loadHistory],
  )

  /** ★ 停止：断后端 LLM + 断前端连接；列表里那条消息原样保留 */
  const stop = useCallback(() => {
    const token = backendTokenRef.current
    if (token && projectRef) {
      void personalApi.cancelAi(projectRef, token).catch(() => {})
    }
    abortRef.current?.abort()
    abortRef.current = null
    runRef.current += 1 // 让进行中的 ask 的 patch/finally 不再改动界面
    // ★ 把正在流式那条标记为已停（否则一直转圈）
    const id = currentIdRef.current
    if (id) {
      setItems((prev) => prev.map((it) => (it.id === id ? { ...it, streaming: false } : it)))
    }
    currentIdRef.current = ''
    setAiBusyGlobal(false)
    setBusy(false)
  }, [projectRef])

  /** ★ 清空这个节点的历史 */
  const clear = useCallback(async () => {
    if (!projectRef || !vid) return
    await personalApi.qaClear(projectRef, vid, scope)
    setItems([])
    setErr('')
  }, [projectRef, vid, scope, loadHistory])

  return {
    // 状态：一个列表，没有 pending/streaming/steps/lastItem
    items,
    busy,
    err,
    loading,
    // 能力
    ask,
    stop,
    clear,
    reload,
    // 累计统计（纯派生）
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
      return { ...t, rate: t.hit + t.miss > 0 ? t.hit / (t.hit + t.miss) : 0 }
    })(),
  }
}
