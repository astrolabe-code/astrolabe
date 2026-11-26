/**
 * 左侧栏（EXPLORER）：代码 + 笔记 两组，各自可折叠。
 *
 * 设计（见原型）：像 VS Code 的侧边栏 —— 一个面板里放多个分组，
 * ⛔ 不再用图标栏切换「代码/笔记」（用户：一眼就能看出来，没必要）。
 */
import { useMemo, useState } from 'react'
import type { Note, NoteKind } from '../../api/types'
import type { FileTreeData, FileTreeNode } from '../../api/code'
import { useNotes } from '../../query/notes'
import { KIND_META, NOTE_KINDS } from '../notes/kindMeta'
import FileTree from '../code/FileTree'

interface ExplorerProps {
  projectRef: string
  /** 代码组数据（由 useCodeData 提供） */
  tree: FileTreeData | null
  treeError: string
  expanded: Set<string>
  onToggleDir: (path: string) => void
  activePath: string
  onPickFile: (path: string) => void
  /** 点笔记 → 父组件决定在哪打开 */
  onOpenNote?: (note: Note) => void
  /** 新建笔记 */
  onNewNote?: () => void
}

function Section({
  title,
  count,
  children,
  defaultOpen = true,
}: {
  title: string
  count?: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ borderBottom: '1px solid var(--divider, #eef2f7)' }}>
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px',
          fontSize: 11, color: 'var(--text-muted, #64748b)', letterSpacing: '.3px',
          cursor: 'pointer', userSelect: 'none',
        }}
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{
          fontSize: 8, color: 'var(--text-faint, #cbd5e1)',
          display: 'inline-block', transition: 'transform .12s',
          transform: open ? 'rotate(90deg)' : 'none',
        }}>▶</span>
        <span>{title}</span>
        <span style={{ flex: 1 }} />
        {count && <span style={{ fontSize: 10, color: 'var(--text-faint, #cbd5e1)' }}>{count}</span>}
      </div>
      {open && <div>{children}</div>}
    </div>
  )
}

export default function Explorer({
  projectRef,
  tree,
  treeError,
  expanded,
  onToggleDir,
  activePath,
  onPickFile,
  onOpenNote,
  onNewNote,
}: ExplorerProps) {
  const notesQ = useNotes(projectRef, { limit: 2000 })
  const [openKind, setOpenKind] = useState<NoteKind | null>(null)

  const byKind = useMemo(() => {
    const m = new Map<NoteKind, Note[]>()
    for (const k of NOTE_KINDS) m.set(k, [])
    for (const n of notesQ.data ?? []) {
      const arr = m.get(n.kind)
      if (arr) arr.push(n)
    }
    return m
  }, [notesQ.data])

  const total = notesQ.data?.length ?? 0

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--bg, #fff)' }}>
      <div style={{
        height: 30, flex: 'none', display: 'flex', alignItems: 'center', gap: 6,
        padding: '0 10px', borderBottom: '1px solid var(--divider, #eef2f7)',
        fontSize: 11, color: 'var(--text-faint, #94a3b8)', letterSpacing: '.4px',
      }}>
        <span>EXPLORER</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10 }}>{projectRef}</span>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {/* ── 代码 ── */}
        <Section title="代码" count={tree ? String(countFiles(tree.items)) : undefined}>
          {treeError ? (
            <div style={{ padding: '4px 12px 10px', fontSize: 11, color: 'var(--err, #ef4444)' }}>{treeError}</div>
          ) : tree ? (
            <FileTree
              items={tree.items}
              activePath={activePath}
              expanded={expanded}
              onToggle={onToggleDir}
              onPick={onPickFile}
            />
          ) : (
            <div style={{ padding: '4px 12px 10px', fontSize: 11, color: 'var(--text-faint, #cbd5e1)' }}>载入中…</div>
          )}
        </Section>

        {/* ── 笔记 ── */}
        <Section title="笔记" count={`${total} 篇`}>
          {NOTE_KINDS.map((k) => {
            const meta = KIND_META[k]
            const list = byKind.get(k) ?? []
            const isOpen = openKind === k
            return (
              <div key={k}>
                <div
                  style={{
                    display: 'flex', alignItems: 'center', gap: 7,
                    padding: '4px 10px 4px 20px', fontSize: 12,
                    color: 'var(--text, #334155)', cursor: 'pointer',
                  }}
                  onClick={() => setOpenKind(isOpen ? null : k)}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--hover, #f8fafc)' }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <span style={{ width: 7, height: 7, borderRadius: 9, background: meta.color, flex: 'none' }} />
                  <span>{meta.label}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-faint, #cbd5e1)' }}>{list.length}</span>
                </div>
                {isOpen && list.length > 0 && (
                  <div style={{ paddingBottom: 4 }}>
                    {list.map((n) => (
                      <div
                        key={n.id}
                        style={{
                          padding: '3px 10px 3px 34px', fontSize: 11.5,
                          color: 'var(--text-sub, #475569)', cursor: 'pointer',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}
                        title={n.title}
                        onClick={() => onOpenNote?.(n)}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--hover, #f8fafc)' }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                      >
                        {n.title || `节点 #${n.node_id}`}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
          <div
            style={{
              margin: '8px 10px 10px', padding: 5, textAlign: 'center', fontSize: 11.5,
              border: '1px dashed var(--card-border, #cbd5e1)', borderRadius: 6,
              color: 'var(--text-muted, #64748b)', cursor: 'pointer',
            }}
            onClick={() => onNewNote?.()}
          >
            ＋ 写一篇
          </div>
        </Section>
      </div>
    </div>
  )
}

function countFiles(items: FileTreeNode[]): number {
  let n = 0
  for (const it of items) {
    if (it.type === 'dir') n += countFiles(it.children ?? [])
    else n += 1
  }
  return n
}
