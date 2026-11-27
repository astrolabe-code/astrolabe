/**
 * ★★★ **个人版 · 项目设置**
 *
 * 社区版的设置页有「可见性 / 许可证 / 协作者 / 审核状态」这些项 ——
 * 个人版只有你一个人，那些一栏都没有对象。
 *
 * 这一页只回答四个问题：
 *
 * ```\n * 1. 这个项目读了哪个目录？\n * 2. 笔记到底存在哪？（⭐ 用户最常问的）\n * 3. 现在的图是什么状态？（解析成功没有 / 人补了几项）\n * 4. 要删掉它 / 重建它，怎么做？\n * ```\n *
 * ⚠ 重新解析是**修复动作**（`graph_exists` 会被拒绝），这里也必须写理由。
 * ⚠ 删除项目**只移出列表，不删文件** —— 笔记是用户的东西，不能替他删。
 */

import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderOpen, RefreshCw, Trash2 } from 'lucide-react'

interface Settings {
  name: string
  root: string
  data: string
  nodes: number
  notes: number
  summary: number
  parseState: string
  parseError: string
  parsedAt: string | null
  manualNodes: number
  manualEdges: number
  curateLog: { id: number; action: string; target: string; reason: string; at: string }[]
}

const ACTION_CN: Record<string, string> = {
  add_node: '加节点',
  update_node: '改节点',
  remove_node: '删节点',
  add_edge: '加关系',
  update_edge: '改关系',
  remove_edge: '删关系',
  reparse: '重新解析',
}

export default function PersonalProjectSettings({ projectRef }: { projectRef: string }) {
  const nav = useNavigate()
  const [d, setD] = useState<Settings | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [reason, setReason] = useState('')

  const api = (window as unknown as { astrolabe?: { openPath?: (p: string) => Promise<boolean> } })
    .astrolabe

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(projectRef)}/settings/`)
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || '读取失败')
      setD(j.data as Settings)
    } catch (e) {
      setErr(String((e as Error).message || e))
    }
  }, [projectRef])

  useEffect(() => {
    void load()
  }, [load])

  const reparse = async () => {
    if (!reason.trim()) {
      setErr('写一句为什么重新解析（图不完整？解析出错了？）')
      return
    }
    setBusy('reparse')
    setErr('')
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(projectRef)}/parse`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ force: true, reason: reason.trim() }),
      })
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || '重新解析失败')
      setReason('')
      await load()
    } catch (e) {
      setErr(String((e as Error).message || e))
    } finally {
      setBusy('')
    }
  }

  const remove = async () => {
    setBusy('remove')
    setErr('')
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(projectRef)}/`, { method: 'DELETE' })
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || '删除失败')
      nav('/')
    } catch (e) {
      setErr(String((e as Error).message || e))
      setBusy('')
    }
  }

  const row: React.CSSProperties = {
    display: 'flex',
    alignItems: 'baseline',
    gap: 10,
    padding: '7px 0',
    borderBottom: '1px dashed var(--card-border)',
    fontSize: 12.5,
  }
  const key: React.CSSProperties = { width: 88, color: 'var(--text-faint)', flex: 'none' }
  const mono: React.CSSProperties = {
    fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
    fontSize: 11.5,
    wordBreak: 'break-all',
  }

  if (err && !d) {
    return (
      <div className="card" style={{ padding: 20 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>打不开设置</div>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
          {err}
        </div>
      </div>
    )
  }
  if (!d) return <div className="faint" style={{ fontSize: 13 }}>加载中…</div>

  return (
    <div style={{ maxWidth: 720 }}>
      <div className="card" style={{ padding: '14px 16px' }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 6 }}>基本信息</div>
        <div style={row}>
          <span style={key}>名称</span>
          <span>{d.name}</span>
        </div>
        <div style={row}>
          <span style={key}>源码目录</span>
          <span style={mono}>{d.root || '（没有源码：手动结构）'}</span>
        </div>
        <div style={row}>
          <span style={key}>笔记存在</span>
          <span style={mono}>{d.data}</span>
          <button
            type="button"
            onClick={() => void api?.openPath?.(d.data)}
            style={{
              marginLeft: 'auto',
              border: '1px solid var(--card-border)',
              background: 'transparent',
              borderRadius: 6,
              padding: '2px 8px',
              fontSize: 11.5,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              flex: 'none',
            }}
          >
            <FolderOpen size={11} /> 打开
          </button>
        </div>
        <div style={row}>
          <span style={key}>规模</span>
          <span>
            {d.nodes} 个节点 · {d.notes} 篇笔记 · 小结 {d.summary} 篇
            {(d.manualNodes > 0 || d.manualEdges > 0) && (
              <span className="faint">（人补 {d.manualNodes + d.manualEdges} 项）</span>
            )}
          </span>
        </div>
        <div style={{ ...row, borderBottom: 'none' }}>
          <span style={key}>解析状态</span>
          <span style={{ color: d.parseState === 'ok' ? '#0a7d32' : '#b00' }}>
            {d.parseState === 'ok' ? '正常' : d.parseState === 'failed' ? '失败' : '还没解析'}
            {d.parseError && <span className="faint"> · {d.parseError}</span>}
          </span>
        </div>
      </div>

      {/* 修补历史 */}
      <div className="card" style={{ padding: '14px 16px', marginTop: 12 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 8 }}>改图记录</div>
        {d.curateLog.length === 0 ? (
          <div className="faint" style={{ fontSize: 12 }}>
            还没有改过图。解析不准的地方，去「图谱 → 改图」补。
          </div>
        ) : (
          d.curateLog.map((x) => (
            <div key={x.id} style={{ ...row, borderBottom: '1px dashed var(--card-border)' }}>
              <span style={{ ...key, width: 72 }}>{x.at.slice(5, 16)}</span>
              <span style={{ width: 74, flex: 'none' }}>{ACTION_CN[x.action] || x.action}</span>
              <span className="faint" style={{ fontSize: 12 }}>
                {x.reason}
              </span>
            </div>
          ))
        )}
      </div>

      {/* 危险区 */}
      <div
        className="card"
        style={{ padding: '14px 16px', marginTop: 12, borderColor: 'rgba(200,0,0,.18)' }}
      >
        <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 6 }}>修复与清理</div>

        <div style={{ fontSize: 12, lineHeight: 1.9, color: 'var(--text-sub)' }}>
          重新解析用于修复「图不完整 / 解析出错」，不是日常操作 —— 人手补的节点和边会保留。
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <input
            className="input"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="为什么重新解析"
            style={{ flex: 1, minWidth: 200, fontSize: 12 }}
          />
          <button
            type="button"
            disabled={busy !== ''}
            onClick={() => void reparse()}
            style={{
              border: '1px solid var(--card-border)',
              background: 'transparent',
              borderRadius: 6,
              padding: '5px 12px',
              fontSize: 12,
              cursor: busy ? 'default' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
            }}
          >
            <RefreshCw size={11} /> {busy === 'reparse' ? '重建中…' : '重新解析'}
          </button>
        </div>

        <div style={{ fontSize: 12, lineHeight: 1.9, color: 'var(--text-sub)', marginTop: 14 }}>
          从列表里移除这个项目。<b>笔记不会被删</b>，还留在上面那个目录里。
        </div>
        <button
          type="button"
          disabled={busy !== ''}
          onClick={() => void remove()}
          style={{
            marginTop: 6,
            border: '1px solid rgba(200,0,0,.35)',
            color: '#b00',
            background: 'transparent',
            borderRadius: 6,
            padding: '5px 12px',
            fontSize: 12,
            cursor: busy ? 'default' : 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
          }}
        >
          <Trash2 size={11} /> {busy === 'remove' ? '移除中…' : '从列表移除'}
        </button>
      </div>

      {err && (
        <div style={{ color: '#c00', fontSize: 12, marginTop: 10 }}>{err}</div>
      )}
    </div>
  )
}
