import { useMemo, useState } from 'react'
import type { Note } from '../../api/types'
import { CheckCircle2, Lock, LockOpen } from 'lucide-react'

import Button from '../ui/Button'
import Modal from '../ui/Modal'
import { useBatchVisibility, useNotes } from '../../query/notes'
import { kindMeta } from './kindMeta'

/**
 * ★★★ **批量改公开 / 私有**（* 2026-10-21 · 所有者裁定）⚠
 *
 * > 「不用，加一个批量改公开或私有的功能就可以了，用户选择排除那些笔记，其他批量改，
 * >   不用加个字段。以后，用户想批量修改也方便。」
 *
 * ## ★★ 交互
 *
 * ```
 * 列出本项目**全部**笔记（默认**全部要改**）
 *   · 勾上 = 排除（* 这一篇不动）     ← 所有者要的「选择排除」
 *   · 底部两个按钮：全部设为公开 / 全部设为私有
 * ```
 */
export default function BatchVisibility({
  open,
  projectRef,
  onClose,
}: {
  open: boolean
  projectRef: string
  onClose: () => void
}) {
  const notes = useNotes(projectRef, { limit: 200 })
  const batch = useBatchVisibility(projectRef)
  // ★ 勾上的 = **排除**（⛔ 不是"选中要改的"）
  const [excluded, setExcluded] = useState<Set<number>>(new Set())
  const [msg, setMsg] = useState('')

  // ★ `useNotes` 直接返回 `Note[]`（* 不是 {items}）⚠
  const items = useMemo(() => notes.data ?? [], [notes.data])
  const willChange = items.length - excluded.size

  const toggle = (id: number) => {
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const run = async (isPublic: boolean) => {
    setMsg('')
    try {
      const r = await batch.mutateAsync({ is_public: isPublic, exclude_ids: [...excluded] })
      setMsg(`已修改 ${r.updated} 篇笔记`)
      setExcluded(new Set())
      window.setTimeout(onClose, 600)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '批量修改失败')
    }
  }

  return (
    <Modal
      open={open}
      title="批量修改可见性"
      width={560}
      onClose={onClose}
      footer={
        <div className="flex items-center justify-between" style={{ width: '100%' }}>
          <span className="faint" style={{ fontSize: 11.5 }}>
            勾选 = <b>排除</b>（不动它）· 将修改 <b>{willChange}</b> 篇
          </span>
          <div className="flex items-center gap-2">
            <Button onClick={onClose}>取消</Button>
            <Button
              icon={<LockOpen size={13} />}
              loading={batch.isPending}
              disabled={willChange <= 0}
              onClick={() => void run(true)}
            >
              全部设为公开
            </Button>
            <Button
              icon={<Lock size={13} />}
              loading={batch.isPending}
              disabled={willChange <= 0}
              onClick={() => void run(false)}
            >
              全部设为私有
            </Button>
          </div>
        </div>
      }
    >
      {msg && (
        <div
          className="flex items-center gap-1.5"
          style={{ fontSize: 12, color: 'var(--ok)', marginBottom: 8 }}
        >
          <CheckCircle2 size={13} />
          {msg}
        </div>
      )}

      {notes.isLoading ? (
        <div className="faint" style={{ fontSize: 12.5 }}>
          笔记加载中…
        </div>
      ) : items.length === 0 ? (
        <div className="faint" style={{ fontSize: 12.5 }}>
          这个项目还没有笔记。
        </div>
      ) : (
        <div style={{ maxHeight: '46vh', overflowY: 'auto' }}>
          {items.map((n: Note) => {
            const meta = kindMeta(n.kind)
            const ex = excluded.has(n.id)
            return (
              <label
                key={n.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '6px 4px',
                  borderBottom: '1px solid var(--card-border)',
                  cursor: 'pointer',
                  opacity: ex ? 0.5 : 1,
                }}
              >
                <input type="checkbox" checked={ex} onChange={() => toggle(n.id)} />
                <span
                  style={{
                    fontSize: 10,
                    color: meta.color,
                    border: `1px solid ${meta.color}`,
                    borderRadius: 999,
                    padding: '0 6px',
                    lineHeight: '15px',
                    flexShrink: 0,
                  }}
                >
                  {meta.label}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    flex: 1,
                    minWidth: 0,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {n.title || '（无标题）'}
                </span>
                <span className="faint" style={{ fontSize: 10.5, flexShrink: 0 }}>
                  {n.is_public ? '公开' : '私有'}
                </span>
              </label>
            )
          })}
        </div>
      )}
    </Modal>
  )
}
