/**
 * 学习路径面板（AI 引导的图遍历）
 *
 * 设计（见方案 v3）：
 *   · 后端查图拿候选 + 附源码 → AI 在候选里挑 + 给理由 → 本地校验
 *   · 推荐是瞬态的：只显示，不写文件
 *   · 已学 = 该节点有 summary 笔记（复用个人版原有判定）
 *   · 路径不保存，每次根据小结重算
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { personalApi } from '../../api/personal'
import { useNotes } from '../../query/notes'

export interface PathStep {
  vid: number
  name: string
  qname: string
  reason: string
  score?: number
  label?: string
}

interface Props {
  projectRef: string
  selectedVid?: number | null
  /** 点路径项 → 图谱高亮 + 打开源码 */
  onPick?: (vid: number) => void
}

export default function LearningPathPanel({ projectRef, selectedVid, onPick }: Props) {
  const [mode, setMode] = useState<'explore' | 'attack'>('explore')
  const [steps, setSteps] = useState<PathStep[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [started, setStarted] = useState(false)
  const [scoring, setScoring] = useState<number | null>(null)

  /** requestId：防快速点两次生成分叉路径 */
  const runIdRef = useRef(0)
  const walkedRef = useRef<Set<number>>(new Set())
  const notesQ = useNotes(projectRef, { kind: 'summary', limit: 1000 })
  const learnedVids = useMemo(() => {
    const s = new Set<number>()
    for (const n of (notesQ.data ?? []) as Array<{ node_id?: number }>) if (n.node_id) s.add(n.node_id)
    return s
  }, [notesQ.data])

  /** 为当前节点写小结（面板内快捷入口），保存后异步打分 */
  const [noteText, setNoteText] = useState('')
  // 小结写入走笔记接口（本面板先做推荐与打分展示）

  /** 走一步：后端查候选 + AI 挑 */
  const step = useCallback(async (currentVid: number | null) => {
    const myRun = ++runIdRef.current
    setBusy(true)
    setErr('')
    try {
      const r = await personalApi.aiRecommend(projectRef, {
        vid: currentVid,
        direction: mode === 'attack' ? 'up' : 'down',
        learned: [...learnedVids, ...walkedRef.current].map((vid) => ({
          vid,
          name: steps.find((s) => s.vid === vid)?.name || '',
          summary: steps.find((s) => s.vid === vid)?.reason || '',
        })),
      })
      if (myRun !== runIdRef.current) return   // 已被新的请求取代
      if (r.vid == null) {
        setErr(r.reason || '没有可推荐的了')
        return
      }
      walkedRef.current.add(r.vid)
      setSteps((prev) => [
        ...prev,
        { vid: r.vid!, name: r.name || String(r.vid), qname: r.qname || '', reason: r.reason },
      ])
    } catch (e) {
      if (myRun === runIdRef.current) setErr(String((e as Error)?.message || e))
    } finally {
      if (myRun === runIdRef.current) setBusy(false)
    }
  }, [projectRef, mode, learnedVids, steps])

  /** 开始：探索模式从入口（vid=null），攻坚模式从当前选中节点 */
  const start = useCallback(() => {
    setStarted(true)
    setSteps([])
    setErr('')
    walkedRef.current.clear()
    void step(mode === 'attack' ? (selectedVid ?? null) : null)
  }, [mode, selectedVid, step])

  /** 给最后一步写小结 → AI 打分 */
  const scoreLast = useCallback(async () => {
    const last = steps[steps.length - 1]
    if (!last || !noteText.trim()) return
    setScoring(last.vid)
    try {
      // ★ 先写 summary 笔记（这才是「已学」的判定依据），再打分
      await personalApi.createNote(projectRef, {
        node_id: last.vid,
        kind: 'summary' as any,
        body: noteText,
        title: `小结：${last.name}`,
      } as any)
      const r = await personalApi.aiScoreSummary(projectRef, {
        body: noteText, vid: last.vid,
      })
      setSteps((prev) => prev.map((s, i) =>
        i === prev.length - 1 ? { ...s, score: r.score, label: r.label } : s,
      ))
      setNoteText('')
      void notesQ.refetch()
    } catch (e) {
      setErr(String((e as Error)?.message || e))
    } finally {
      setScoring(null)
    }
  }, [steps, noteText, projectRef, notesQ])

  return (
    <div style={{ fontSize: 12, lineHeight: 1.55 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
        <button
          style={{ cursor: 'pointer', fontWeight: mode === 'explore' ? 700 : 400 }}
          onClick={() => setMode('explore')}
        >探索</button>
        <button
          style={{ cursor: 'pointer', fontWeight: mode === 'attack' ? 700 : 400 }}
          onClick={() => setMode('attack')}
        >攻坚</button>
        <span style={{ marginLeft: 'auto', color: 'var(--text-faint, #888)' }}>
          已学 {learnedVids.size}
        </span>
      </div>

      {!started ? (
        <div style={{ color: 'var(--text-muted, #888)' }}>
          探索：从入口顺着调用往下学。攻坚：从当前节点逆着依赖往上学。
          <br />AI 只看候选源码挑下一个，并说明理由。
          <div style={{ marginTop: 8 }}>
            <button style={{ cursor: 'pointer' }} onClick={start}>开始推荐</button>
          </div>
        </div>
      ) : (
        <>
          <div style={{ maxHeight: 280, overflow: 'auto', marginBottom: 8 }}>
            {steps.map((s, i) => (
              <div
                key={`${s.vid}-${i}`}
                style={{ padding: '6px 4px', borderBottom: '1px solid var(--divider, #333)', cursor: 'pointer' }}
                onClick={() => onPick?.(s.vid)}
              >
                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                  <b>{i + 1}.</b>
                  <span style={{ fontWeight: 600 }}>{s.name}</span>
                  {learnedVids.has(s.vid) && (
                    <span style={{ color: '#10b981', fontSize: 10 }}>已学</span>
                  )}
                  {s.label && (
                    <span style={{ marginLeft: 'auto', fontSize: 10, color: s.score! >= 80 ? '#10b981' : '#f59e0b' }}>
                      {s.label} {s.score}
                    </span>
                  )}
                </div>
                <div style={{ color: 'var(--text-muted, #aaa)', fontSize: 11, marginTop: 2 }}>
                  {s.reason}
                </div>
              </div>
            ))}
            {busy && <div style={{ color: '#22d3ee', padding: 6 }}>AI 正在从候选里挑…</div>}
          </div>

          {err && <div style={{ color: '#ef4444', marginBottom: 6 }}>{err}</div>}

          {steps.length > 0 && !busy && (
            <div style={{ borderTop: '1px solid var(--divider, #333)', paddingTop: 6 }}>
              <div style={{ color: 'var(--text-muted, #888)', marginBottom: 4 }}>
                为最后一步写小结（写完才算学会）：
              </div>
              <textarea
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                rows={2}
                placeholder="这段代码做什么、怎么做的？"
                style={{ width: '100%', fontSize: 11, resize: 'vertical' }}
              />
              <button
                style={{ marginTop: 4, cursor: 'pointer' }}
                disabled={!noteText.trim() || scoring != null}
                onClick={() => void scoreLast()}
              >
                {scoring != null ? 'AI 打分中…' : '保存并打分'}
              </button>
            </div>
          )}

          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <button style={{ cursor: 'pointer' }} disabled={busy} onClick={() => void step(steps[steps.length - 1]?.vid ?? null)}>
              下一步
            </button>
            <button style={{ cursor: 'pointer' }} onClick={start}>重新开始</button>
          </div>
        </>
      )}
    </div>
  )
}
