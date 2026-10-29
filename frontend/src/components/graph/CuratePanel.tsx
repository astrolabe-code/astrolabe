/**
 * ★★★ **改图面板**（个人版最关键的"兜底"能力）
 *
 * ## 为什么它比解析精度更重要
 *
 * ```\n * 解析器不可能 100% 准确：\n *   · 同名函数歧义        ⇒ 边不连（实测 2,319 条）\n *   · 动态调用 / 别名     ⇒ 连不上\n *   · 解析器不认识的写法   ⇒ 节点都没有\n * ```\n *
 * 没有手改，这些问题就是**永久错误**；有手改，它们只是**待修补**。
 *
 * ## 六种动作（与社区版 `curate.py` 对齐）
 *
 * ```\n * add_node / update_node / remove_node\n * add_edge / update_edge / remove_edge\n * ```\n *
 * ⚠★ **每次都要写一句理由**（`reason` 必填）——
 *   不是形式主义：半年后你自己也想知道"这条边当初为什么加上"。
 *   为了不打断，提供几个常用理由一键点（也可自己写）。
 *
 * ⚠ 视觉上人手补的节点/边要和解析出来的区分开（`origin=manual`）。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { X, Search, Plus, Trash2, Pencil, GitBranch } from 'lucide-react'
import type { GraphNode } from '../../lib/mergeGraph'

interface Props {
  open: boolean
  projectRef: string
  nodes: GraphNode[]
  onClose: () => void
  /** 改完之后让图谱重取 */
  onChanged: () => void
}

interface EdgeRow {
  id: number
  src_vid: number
  dst_vid: number
  kind: string
  origin: string
  to_name?: string
  from_name?: string
  to_file?: string
  from_file?: string
}

const REASONS = ['解析漏了', '解析连错', '名字/类型不对', '补一条关系', '去掉噪声']

const PRESET_KINDS = ['function', 'type', 'file', 'variable']

async function curate(projectRef: string, payload: Record<string, unknown>) {
  const r = await fetch(`/api/projects/${encodeURIComponent(projectRef)}/curate/`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const j = await r.json()
  if (!j.ok) throw new Error(j.error || '改图失败')
  return j.data
}

export default function CuratePanel({ open, projectRef, nodes, onClose, onChanged }: Props) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState<GraphNode | null>(null)
  const [edges, setEdges] = useState<{ out: EdgeRow[]; in: EdgeRow[] }>({ out: [], in: [] })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  /** 待确认的动作（点了先问理由，确认后才提交） */
  const [pending, setPending] = useState<{ action: string; payload: Record<string, unknown>; hint: string } | null>(null)
  const [reason, setReason] = useState('')
  /** ★ 内联编辑（⚠ `window.prompt` 在 Electron 里不可靠 ⇒ 一律用输入框）*/
  const [editName, setEditName] = useState('')
  const [editKind, setEditKind] = useState('')
  const [newName, setNewName] = useState('')
  const [newFile, setNewFile] = useState('')

  const hits = useMemo(() => {
    const kw = q.trim().toLowerCase()
    const list = kw
      ? nodes.filter((n) => n.name.toLowerCase().includes(kw) || (n.file_path || '').toLowerCase().includes(kw))
      : nodes
    return list.slice(0, 60)
  }, [q, nodes])

  const loadEdges = useCallback(
    async (vid: number) => {
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectRef)}/edges/?vid=${vid}`)
        const j = await r.json()
        if (j.ok) setEdges({ out: j.data.out || [], in: j.data.in || [] })
      } catch {
        /* 边加载失败不影响主流程 */
      }
    },
    [projectRef],
  )

  useEffect(() => {
    if (sel) {
      setEditName(sel.name)
      setEditKind(sel.kind)
      void loadEdges(sel.vid)
    } else {
      setEdges({ out: [], in: [] })
    }
  }, [sel, loadEdges])

  if (!open) return null

  const ask = (action: string, payload: Record<string, unknown>, hint: string) => {
    setErr('')
    setPending({ action, payload, hint })
    setReason('')
  }

  const submit = async () => {
    if (!pending) return
    if (!reason.trim()) {
      setErr('写一句理由吧（就一句，免得以后犯迷糊）')
      return
    }
    setBusy(true)
    setErr('')
    try {
      await curate(projectRef, { action: pending.action, reason: reason.trim(), ...pending.payload })
      setPending(null)
      onChanged()
      if (sel) await loadEdges(sel.vid)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const box = {
    position: 'fixed' as const,
    top: 0,
    right: 0,
    bottom: 0,
    width: 420,
    maxWidth: '92vw',
    background: '#fff',
    borderLeft: '1px solid var(--card-border)',
    zIndex: 60,
    display: 'flex',
    flexDirection: 'column' as const,
    boxShadow: '-12px 0 32px rgba(0,0,0,.08)',
  }

  const label = { fontSize: 11, color: 'var(--text-faint)', marginBottom: 4 } as const
  const btn = {
    fontSize: 12,
    fontFamily: 'inherit',
    padding: '4px 10px',
    borderRadius: 6,
    border: '1px solid var(--card-border)',
    background: '#fff',
    cursor: 'pointer',
    color: 'var(--text-main)',
  } as const

  return (
    <aside style={box}>
      {/* 头 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '10px 14px',
          borderBottom: '1px solid var(--card-border)',
        }}
      >
        <GitBranch size={14} />
        <b style={{ fontSize: 13 }}>改图</b>
        <span className="faint" style={{ fontSize: 11 }}>
          解析不准的地方，这里补
        </span>
        <button type="button" onClick={onClose} style={{ ...btn, marginLeft: 'auto', border: 'none' }}>
          <X size={14} />
        </button>
      </div>

      {/* 搜索 */}
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--card-border)' }}>
        <div style={{ position: 'relative' }}>
          <Search size={13} style={{ position: 'absolute', left: 8, top: 8, opacity: 0.5 }} />
          <input
            className="input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜节点名 / 文件"
            style={{ width: '100%', paddingLeft: 26, fontSize: 12.5 }}
          />
        </div>
        <div style={{ maxHeight: 150, overflow: 'auto', marginTop: 8 }}>
          {hits.map((n) => (
            <button
              key={n.vid}
              type="button"
              onClick={() => setSel(n)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '3px 6px',
                fontSize: 12,
                fontFamily: 'inherit',
                background: sel?.vid === n.vid ? 'rgba(0,0,0,.05)' : 'transparent',
                border: 'none',
                borderRadius: 4,
                cursor: 'pointer',
              }}
            >
              {n.name}
              <span className="faint" style={{ marginLeft: 6, fontSize: 10.5 }}>
                {n.file_path}:{n.line}
              </span>
              {sel && sel.vid !== n.vid && (
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation()
                    ask('add_edge', { from: sel.vid, to: n.vid, type: 'call' }, `${sel.name} → ${n.name}`)
                  }}
                  style={{
                    marginLeft: 6,
                    fontSize: 10,
                    color: '#fff',
                    background: '#111',
                    borderRadius: 3,
                    padding: '0 4px',
                  }}
                >
                  连
                </span>
              )}
            </button>
          ))}
          {hits.length === 0 && (
            <div className="faint" style={{ fontSize: 11.5, padding: 6 }}>
              没找到 —— 可以用下面的「加一个节点」。
            </div>
          )}
        </div>
      </div>

      {/* 主体 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '10px 14px' }}>
        {!sel && (
          <div className="faint" style={{ fontSize: 12, lineHeight: 1.7 }}>
            先在上面选一个节点，再补/改/删它和别的关系。
          </div>
        )}

        {sel && (
          <>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{sel.name}</div>
            <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>
              {sel.file_path}:{sel.line} · {sel.kind}
            </div>

            {/* 改名 / 改类型（内联，不用 prompt） */}
            <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
              <input
                className="input"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="名字"
                style={{ flex: 1, fontSize: 12 }}
              />
              <input
                className="input"
                value={editKind}
                onChange={(e) => setEditKind(e.target.value)}
                placeholder="类型"
                style={{ width: 92, fontSize: 12 }}
              />
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
              <button
                type="button"
                style={btn}
                onClick={() =>
                  ask(
                    'update_node',
                    { vid: sel.vid, name: editName.trim() || undefined, kind: editKind.trim() || undefined },
                    `改「${sel.name}」`,
                  )
                }
              >
                <Pencil size={11} /> 保存修改
              </button>
              <button
                type="button"
                style={{ ...btn, color: '#c00' }}
                onClick={() => ask('remove_node', { vid: sel.vid }, `删掉节点「${sel.name}」`)}
              >
                <Trash2 size={11} /> 删节点
              </button>
            </div>

            <div style={label}>加一条关系</div>
            <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>
              在上面搜索结果里，点任意一行右侧的「连」⇒ 从当前节点连到它。
            </div>

            <div style={label}>出边（{edges.out.length}）</div>
            {edges.out.map((e) => (
              <Row key={e.id} text={`→ ${e.to_name || e.dst_vid}`} file={e.to_file} origin={e.origin}
                onDel={() => ask('remove_edge', { id: e.id }, '去掉这条关系')} />
            ))}
            {edges.out.length === 0 && <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>没有</div>}

            <div style={{ ...label, marginTop: 12 }}>入边（{edges.in.length}）</div>
            {edges.in.map((e) => (
              <Row key={e.id} text={`← ${e.from_name || e.src_vid}`} file={e.from_file} origin={e.origin}
                onDel={() => ask('remove_edge', { id: e.id }, '去掉这条关系')} />
            ))}
            {edges.in.length === 0 && <div className="faint" style={{ fontSize: 11 }}>没有</div>}
          </>
        )}

        {err && <div style={{ color: '#c00', fontSize: 11.5, marginTop: 10 }}>{err}</div>}
      </div>

      {/* 底部：加节点 */}
      <div style={{ borderTop: '1px solid var(--card-border)', padding: '10px 14px' }}>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            className="input"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="新节点名"
            style={{ flex: 1, fontSize: 12 }}
          />
          <input
            className="input"
            value={newFile}
            onChange={(e) => setNewFile(e.target.value)}
            placeholder="文件路径"
            style={{ flex: 1, fontSize: 12 }}
          />
          <button
            type="button"
            style={btn}
            onClick={() => {
              if (!newName.trim()) {
                setErr('先写个名字')
                return
              }
              ask(
                'add_node',
                { kind: 'function', name: newName.trim(), file_path: newFile.trim(), line: 0 },
                `加节点「${newName.trim()}」`,
              )
            }}
          >
            <Plus size={11} /> 加
          </button>
        </div>
      </div>

      {/* 理由弹窗（⚠ reason 必填 —— 半年后你会感谢现在的自己） */}
      {pending && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: 'rgba(255,255,255,.94)',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            padding: 24,
            gap: 10,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600 }}>{pending.hint}</div>
          <div className="faint" style={{ fontSize: 11.5 }}>
            留一句理由 —— 半年后你会感谢现在的自己。
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {REASONS.map((r) => (
              <button key={r} type="button" style={{ ...btn, fontSize: 11 }} onClick={() => setReason(r)}>
                {r}
              </button>
            ))}
          </div>
          {err && <div style={{ color: '#c00', fontSize: 11.5 }}>{err}</div>}
          <input
            className="input"
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="为什么改"
            style={{ fontSize: 12.5 }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void submit()
            }}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button type="button" style={btn} onClick={() => setPending(null)}>
              取消
            </button>
            <button
              type="button"
              disabled={busy}
              style={{ ...btn, background: '#111', color: '#fff', border: 'none' }}
              onClick={() => void submit()}
            >
              {busy ? '提交中…' : '确认'}
            </button>
          </div>
        </div>
      )}
    </aside>
  )
}

function Row({
  text,
  file,
  origin,
  onDel,
}: {
  text: string
  file?: string
  origin: string
  onDel: () => void
}) {
  const manual = origin === 'manual'
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '3px 0',
        borderBottom: '1px dashed var(--card-border)',
      }}
    >
      <span style={{ fontSize: 12, fontStyle: manual ? 'italic' : 'normal' }}>{text}</span>
      {manual && (
        <span
          style={{
            fontSize: 9.5,
            color: '#8a6d00',
            border: '1px solid #e5d9a8',
            borderRadius: 3,
            padding: '0 3px',
          }}
        >
          人补
        </span>
      )}
      <span
        className="faint"
        style={{ fontSize: 10, marginLeft: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {file}
      </span>
      <button
        type="button"
        onClick={onDel}
        title="删掉这条关系"
        style={{
          marginLeft: 'auto',
          border: 'none',
          background: 'transparent',
          cursor: 'pointer',
          color: 'var(--text-faint)',
          padding: 2,
        }}
      >
        <Trash2 size={11} />
      </button>
    </div>
  )
}
