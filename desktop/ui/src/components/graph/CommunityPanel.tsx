/**
 * ★★ **社区聚类**：哪几个函数是「一伙的」
 *
 * 借鉴 GitNexus 的 `Community`（它用 Leiden 算 label / keywords / cohesion），
 * 但**不落库、不加依赖**：后端用纯 Python 的 Louvain 移动阶段现算，
 * 绿色版不为一个聚类多背几十 MB。
 *
 * ⚠ 这里只**建议**分组，⛔ 不自动挂笔记、⛔ 不改任何节点。
 *   「密度」= 社区内部边数 / 可能边数（0~1），越高说明这几块关系越紧。
 */
import { useEffect, useRef, useState } from 'react'

import { personalApi } from '../../api/personal'

interface Community {
  id: string
  label: string
  keywords: string[]
  size: number
  cohesion: number
  nodes: number[]
}

interface Props {
  projectRef?: string | null
  /** 选中一块 → 交给画布高亮；`key` 为 null 表示取消 */
  onPick: (vids: number[], key: string | null) => void
  /** 当前被高亮的是谁（两个面板共用，避免各自显示「已选中」但画布只亮一种） */
  activeKey?: string | null
}

export default function CommunityPanel({ projectRef, onPick, activeKey }: Props) {
  const [items, setItems] = useState<Community[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const pickRef = useRef(onPick)
  pickRef.current = onPick

  useEffect(() => {
    pickRef.current([], null)
    if (!projectRef) {
      setItems([])
      return
    }
    let alive = true
    setBusy(true)
    setErr('')
    personalApi
      .graphCommunities(projectRef)
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
  }, [projectRef])

  const toggle = (c: Community) => {
    if (activeKey === c.id) {
      pickRef.current([], null)
    } else {
      pickRef.current(c.nodes, c.id)
    }
  }

  return (
    <div className="card" style={{ padding: '10px 12px', marginBottom: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
        社区
        {!busy && items.length > 0 && (
          <span className="faint" style={{ fontWeight: 400, marginLeft: 6 }}>
            {items.length} 块
          </span>
        )}
      </div>

      {busy && (
        <div className="faint" style={{ fontSize: 11 }}>
          聚类中…
        </div>
      )}
      {err && <div style={{ fontSize: 11, color: 'var(--err)' }}>{err}</div>}
      {!busy && !err && items.length === 0 && (
        <div className="faint" style={{ fontSize: 11, lineHeight: 1.6 }}>
          还没有明显的分组（节点之间缺少连接）。
        </div>
      )}

      {items.map((c) => {
        const on = activeKey === c.id
        return (
          <button
            key={c.id}
            type="button"
            onClick={() => toggle(c)}
            title={on ? '再点一次取消高亮' : '在画布上高亮这一块'}
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
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {c.label}
            </span>
            <span className="faint">
              {' '}
              · {c.size} 个 · 密度 {c.cohesion.toFixed(2)}
            </span>
          </button>
        )
      })}
    </div>
  )
}
