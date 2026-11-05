/**
 * ★★★ **Ctrl+K 搜索面板**（个人版）
 *
 * 所有者：「obsidian 有搜索笔记的功能吗？」「可以，做吧」
 *
 * ## 为什么是面板，不是搜索页
 *
 * ```\n * 搜索页     跳走 → 搜 → 再跳回来     打断当前阅读\n * 面板       随时唤出，Esc 就回去     符合"随手找一句"\n * ```\n *
 * ## 搜两类东西
 *
 * ```\n * 笔记   正文 / 标题 命中（SQLite FTS5 trigram）→ 打开阅读页\n * 节点   名字 / 文件 命中                      → 打开项目页并选中它\n * ```\n *
 * ⚠ 跨项目搜：结果里带项目名，否则两个项目都有 `init` 时分不清。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Search, X } from 'lucide-react'

interface NoteHit {
  ref: string
  no: number
  title: string
  kind: string
  node: string
  snippet: string
  project: string
  project_ref: string
}

interface NodeHit {
  vid: number
  kind: string
  name: string
  file_path: string
  line: number
  project: string
  project_ref: string
}

const KIND_CN: Record<string, string> = {
  flash: '灵光一闪',
  question: '质疑',
  confusion: '困惑',
  pitfall: '踩坑',
  summary: '小结',
}

export default function CommandPalette() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [notes, setNotes] = useState<NoteHit[]>([])
  const [nodes, setNodes] = useState<NodeHit[]>([])
  const [active, setActive] = useState(0)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // ---- 唤出 / 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (open) {
      setQ('')
      setNotes([])
      setNodes([])
      setActive(0)
      // ⚠ 等一帧再 focus，否则元素还没挂上
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }, [open])

  // ---- 查询（150ms 防抖）
  useEffect(() => {
    if (!open) return
    const kw = q.trim()
    if (!kw) {
      setNotes([])
      setNodes([])
      return
    }
    setBusy(true)
    const t = window.setTimeout(async () => {
      try {
        const r = await fetch(`/api/search/?q=${encodeURIComponent(kw)}`)
        const j = await r.json()
        if (j.ok) {
          setNotes((j.data.notes || []) as NoteHit[])
          setNodes((j.data.nodes || []) as NodeHit[])
          setActive(0)
        }
      } catch {
        /* 搜索失败就当没结果，不打断 */
      } finally {
        setBusy(false)
      }
    }, 150)
    return () => window.clearTimeout(t)
  }, [q, open])

  const flat = useMemo(
    () => [
      ...notes.map((n) => ({ type: 'note' as const, n })),
      ...nodes.map((n) => ({ type: 'node' as const, n })),
    ],
    [notes, nodes],
  )

  const go = useCallback(
    (i: number) => {
      const item = flat[i]
      if (!item) return
      if (item.type === 'note') {
        nav(`/p/${encodeURIComponent(item.n.project_ref)}/notes/${encodeURIComponent(item.n.ref)}`)
      } else {
        nav(`/p/${encodeURIComponent(item.n.project_ref)}?node=${item.n.vid}`)
      }
      setOpen(false)
    },
    [flat, nav],
  )

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, flat.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      go(active)
    }
  }

  if (!open) return null

  return (
    <div
      onClick={() => setOpen(false)}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,.28)',
        zIndex: 80,
        display: 'flex',
        justifyContent: 'center',
        paddingTop: '12vh',
        fontFamily: 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 620,
          maxWidth: '92vw',
          maxHeight: '64vh',
          display: 'flex',
          flexDirection: 'column',
          background: '#fff',
          borderRadius: 10,
          border: '1px solid var(--card-border)',
          boxShadow: '0 12px 40px rgba(0,0,0,.18)',
          overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', borderBottom: '1px solid var(--card-border)' }}>
          <Search size={14} color="var(--text-faint)" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="搜笔记正文、标题、节点名…"
            style={{
              flex: 1,
              border: 'none',
              outline: 'none',
              fontSize: 14,
              fontFamily: 'inherit',
              background: 'transparent',
              color: '#111',
            }}
          />
          {busy && <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>搜索中…</span>}
          <button
            type="button"
            onClick={() => setOpen(false)}
            style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--text-faint)', padding: 2 }}
          >
            <X size={14} />
          </button>
        </div>

        <div style={{ overflowY: 'auto', flex: 1 }}>
          {q.trim() && flat.length === 0 && !busy && (
            <div className="faint" style={{ padding: '18px 14px', fontSize: 12.5 }}>
              没找到。换个词试试 —— 搜的是笔记正文和节点名。
            </div>
          )}

          {notes.length > 0 && (
            <div style={groupLabel}>笔记（{notes.length}）</div>
          )}
          {notes.map((n, i) => (
            <button
              key={`n-${n.ref}`}
              type="button"
              onMouseEnter={() => setActive(i)}
              onClick={() => go(i)}
              style={{ ...itemStyle, background: active === i ? 'rgba(0,0,0,.045)' : 'transparent' }}
            >
              <FileText size={13} color="var(--text-faint)" style={{ flex: 'none', marginTop: 2 }} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, color: '#111', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  №{String(n.no).padStart(3, '0')} {n.title || '无标题'}
                  <span className="faint" style={{ fontSize: 10.5, marginLeft: 6 }}>
                    {KIND_CN[n.kind] || n.kind}
                    {n.project ? ` · ${n.project}` : ''}
                  </span>
                </div>
                <div
                  className="faint"
                  style={{ fontSize: 11.5, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  {n.snippet}
                </div>
              </div>
            </button>
          ))}

          {nodes.length > 0 && (
            <div style={groupLabel}>节点（{nodes.length}）</div>
          )}
          {nodes.map((n, k) => {
            const i = notes.length + k
            return (
              <button
                key={`v-${n.vid}-${n.project_ref}`}
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => go(i)}
                style={{ ...itemStyle, background: active === i ? 'rgba(0,0,0,.045)' : 'transparent' }}
              >
                <span
                  style={{
                    flex: 'none',
                    width: 6,
                    height: 6,
                    borderRadius: 3,
                    marginTop: 6,
                    background: 'var(--text-faint)',
                  }}
                />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: '#111' }}>
                    {n.name}
                    <span className="faint" style={{ fontSize: 10.5, marginLeft: 6 }}>
                      {n.kind}
                      {n.project ? ` · ${n.project}` : ''}
                    </span>
                  </div>
                  <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>
                    {n.file_path}:{n.line}
                  </div>
                </div>
              </button>
            )
          })}
        </div>

        <div
          className="faint"
          style={{
            padding: '6px 12px',
            borderTop: '1px solid var(--card-border)',
            fontSize: 11,
            display: 'flex',
            gap: 12,
          }}
        >
          <span>↑↓ 选择</span>
          <span>Enter 打开</span>
          <span>Esc 关闭</span>
          <span style={{ marginLeft: 'auto' }}>Ctrl+K 随时唤出</span>
        </div>
      </div>
    </div>
  )
}

const groupLabel: React.CSSProperties = {
  padding: '8px 12px 4px',
  fontSize: 10.5,
  color: 'var(--text-faint)',
  letterSpacing: 0.4,
}

const itemStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  width: '100%',
  textAlign: 'left',
  border: 'none',
  background: 'transparent',
  padding: '7px 12px',
  cursor: 'pointer',
  fontFamily: 'inherit',
  alignItems: 'flex-start',
}
