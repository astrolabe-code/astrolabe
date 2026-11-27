import { useEffect, useState } from 'react'
import { Link2, Search, X } from 'lucide-react'

import { cardId, type CardSearchHit } from '../../api/code'
import { personalApi } from '../../api/personal'

interface ReferencePickerProps {
  /** 当前这张卡（全局 id） */
  currentCardId: string
  onClose: () => void
  /** 挂完引用后刷新上层（列表 / 白板） */
  onPicked?: () => void
}

/**
 * ★★★ **参见 = 引用已经写好的卡**（D139）
 *
 * 所有者：「参见则是像写论文时的引用，是已经写好的东西」
 * ⇒ ⛔ 这里**不新建任何笔记**，只从现成的跨项目搜索里挑一张挂上引用。
 *
 * 搜索复用 `/api/search/`（本来就遍历所有项目做 FTS5），
 * 所以跨节点、跨项目都能搜到。
 */
export default function ReferencePicker({
  currentCardId,
  onClose,
  onPicked,
}: ReferencePickerProps) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<CardSearchHit[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!q.trim()) {
      setHits([])
      setBusy(false)
      return
    }
    let alive = true
    setBusy(true)
    const timer = window.setTimeout(() => {
      personalApi
        .searchCards(q.trim())
        .then((d) => {
          if (alive) setHits(d.notes || [])
        })
        .catch((e: Error) => {
          if (alive) setErr(e.message || '搜索失败')
        })
        .finally(() => {
          if (alive) setBusy(false)
        })
    }, 250)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [q])

  const pick = async (h: CardSearchHit) => {
    const id = cardId(h.project_ref, h.ref)
    if (id === currentCardId) return
    setErr('')
    try {
      await personalApi.addReference(currentCardId, id)
      onPicked?.()
      onClose()
    } catch (e) {
      setErr((e as Error).message || '引用失败')
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 120,
        background: 'rgba(15,23,42,.28)',
        display: 'grid',
        placeItems: 'center',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="card"
        style={{
          width: 520,
          maxWidth: '92vw',
          maxHeight: '76vh',
          display: 'flex',
          flexDirection: 'column',
          padding: 0,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 14px',
            borderBottom: '1px solid var(--card-border)',
            flexShrink: 0,
          }}
        >
          <Link2 size={14} style={{ color: 'var(--accent)' }} />
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>参见：引用已写好的笔记</span>
          <button
            type="button"
            onClick={onClose}
            title="关闭"
            style={{ marginLeft: 'auto', border: 0, background: 'transparent', cursor: 'pointer' }}
          >
            <X size={15} />
          </button>
        </div>

        <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--card-border)', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Search size={14} className="faint" />
            <input
              autoFocus
              className="input"
              placeholder="搜标题 / 正文（所有项目）"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ flex: 1, fontSize: 12.5 }}
            />
          </div>
          <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
            只引用已经写好的笔记，⛔ 不会新建；可跨节点、跨项目
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '6px 14px 12px' }}>
          {busy && <div className="faint" style={{ padding: 12, fontSize: 12 }}>搜索中…</div>}
          {!busy && q.trim() && hits.length === 0 && (
            <div className="faint" style={{ padding: 12, fontSize: 12 }}>没找到相关笔记</div>
          )}
          {!q.trim() && (
            <div className="faint" style={{ padding: 12, fontSize: 12 }}>
              输入关键词开始搜索
            </div>
          )}
          {hits.map((h) => {
            const id = cardId(h.project_ref, h.ref)
            const self = id === currentCardId
            return (
              <button
                key={id}
                type="button"
                disabled={self}
                onClick={() => void pick(h)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '8px 10px',
                  marginTop: 4,
                  border: '1px solid var(--card-border)',
                  borderRadius: 8,
                  background: 'transparent',
                  cursor: self ? 'not-allowed' : 'pointer',
                  opacity: self ? 0.5 : 1,
                }}
              >
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>
                  {h.title || '（无标题）'}
                  {self && <span className="faint" style={{ fontWeight: 400 }}> · 当前这篇</span>}
                </div>
                <div className="faint" style={{ fontSize: 11, marginTop: 2 }}>
                  {h.project} · {h.node || '未挂节点'} · {h.kind}
                </div>
                {h.snippet && (
                  <div className="faint" style={{ fontSize: 11, marginTop: 2, lineHeight: 1.5 }}>
                    {h.snippet}
                  </div>
                )}
              </button>
            )
          })}
          {err && <div style={{ padding: 10, fontSize: 12, color: 'var(--err)' }}>{err}</div>}
        </div>
      </div>
    </div>
  )
}
