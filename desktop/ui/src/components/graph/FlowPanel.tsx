/**
 * ★★ **执行流**：当前节点落在哪几条调用链里
 *
 * 借鉴 GitNexus 的 `Process` 概念 —— 但**不存库**：
 * 调用链每次从 `Rel` 现算（几千条边，毫秒级），
 * 图库 schema 一行没改。
 *
 * ⚠ `minSteps = 3` 是照抄它的门槛：两步只是「A 调 B」，不算一条流程。
 *
 * ## 交互
 *
 * ```\n * 点一条 → 通知画布高亮整条链（onPick(steps)）\n * 再点一次 → 取消高亮\n * 换节点 → 自动清空（不残留上一条链的高亮）\n * ```
 */
import { useEffect, useRef, useState } from 'react'

import { personalApi } from '../../api/personal'

interface Flow {
  id: string
  steps: number[]
  length: number
}

interface Props {
  projectRef?: string | null
  /** 当前选中的节点 */
  vid?: number | null
  /** 把 vid 翻成名字（由父组件用图数据提供） */
  nameOf?: (vid: number) => string
  /** 选中一条链 → 交给画布高亮；`key` 为 null 表示取消 */
  onPick: (vids: number[], key: string | null) => void
  /** 当前被高亮的是谁（与社区面板共用） */
  activeKey?: string | null
}

export default function FlowPanel({ projectRef, vid, nameOf, onPick, activeKey }: Props) {
  const [items, setItems] = useState<Flow[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  // ⚠ onPick 每次渲染都是新函数，放进依赖会让 effect 无限重跑
  const pickRef = useRef(onPick)
  pickRef.current = onPick

  useEffect(() => {
    pickRef.current([], null)
    if (!projectRef || !vid) {
      setItems([])
      setErr('')
      return
    }
    let alive = true
    setBusy(true)
    setErr('')
    personalApi
      .graphFlows(projectRef, vid)
      .then((d) => {
        if (alive) setItems(d.items || [])
      })
      .catch((e) => {
        if (alive) {
          setItems([])
          setErr(e instanceof Error ? e.message : String(e))
        }
      })
      .finally(() => {
        if (alive) setBusy(false)
      })
    return () => {
      alive = false
    }
  }, [projectRef, vid])

  if (!vid) return null

  const toggle = (f: Flow) => {
    if (activeKey === f.id) {
      pickRef.current([], null)
    } else {
      pickRef.current(f.steps, f.id)
    }
  }

  return (
    <div className="card" style={{ padding: '10px 12px', marginBottom: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
        执行流
        {!busy && items.length > 0 && (
          <span className="faint" style={{ fontWeight: 400, marginLeft: 6 }}>
            在 {items.length} 条调用链里
          </span>
        )}
      </div>

      {busy && (
        <div className="faint" style={{ fontSize: 11 }}>
          计算中…
        </div>
      )}
      {err && <div style={{ fontSize: 11, color: 'var(--err)' }}>{err}</div>}
      {!busy && !err && items.length === 0 && (
        <div className="faint" style={{ fontSize: 11, lineHeight: 1.6 }}>
          没有 3 步以上的调用链（两步只是「谁调用了谁」）。
        </div>
      )}

      {items.map((f) => {
        const on = activeKey === f.id
        const first = nameOf ? nameOf(f.steps[0]) : String(f.steps[0])
        const last = nameOf ? nameOf(f.steps[f.steps.length - 1]) : String(f.steps[f.steps.length - 1])
        return (
          <button
            key={f.id}
            type="button"
            onClick={() => toggle(f)}
            title={on ? '再点一次取消高亮' : '在画布上高亮这条链'}
            style={{
              display: 'block',
              width: '100%',
              textAlign: 'left',
              border: 0,
              borderRadius: 6,
              padding: '4px 6px',
              marginBottom: 2,
              cursor: 'pointer',
              fontSize: 11.5,
              lineHeight: 1.7,
              background: on ? 'var(--accent-dim)' : 'transparent',
            }}
          >
            <span style={{ color: 'var(--accent)' }}>{f.length} 步</span>
            <span className="faint">
              {' '}
              · {first} → {last}
            </span>
          </button>
        )
      })}
    </div>
  )
}
