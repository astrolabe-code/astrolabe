/**
 * ★★★ **改锚点**（`D125` · 2026-10-27）⚠
 *
 * ## 所有者原话（逐字）
 *
 * > 「**漂流笔记不要，会积的越来越多，就跟obsidian一样了，
 * >   每篇笔记必须有挂的明确的节点，哪怕是挂错了，也要有。**」
 *
 * ## 为什么必须有这个组件
 *
 * 「每篇必须挂」的前提是「挂错了能改」——
 * ⚠ 否则挂错一次就是永久错，用户会因此不敢写（比漂流还糟）⚠
 *
 * 所以这里只做一件事：**把笔记重挂到另一个节点**，成本压到两步
 * （搜节点 → 点一下）。
 */
import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'

import type { GraphNode } from '../../lib/mergeGraph'
import { useGraphNodes } from '../../query/graph'
import Modal from '../ui/Modal'

interface AnchorPickerProps {
  open: boolean
  projectRef: string
  /** 当前的 stable_vid（* 用来高亮「就是它」）⚠ */
  currentVid?: number
  onClose: () => void
  /** ⚠ 带上名字 —— 调用方要显示「挂在 X」，⛔ 不要再查一次 ⚠ */
  onPick: (vid: number, name: string) => void
}

export default function AnchorPicker({
  open,
  projectRef,
  currentVid,
  onClose,
  onPick,
}: AnchorPickerProps) {
  const [q, setQ] = useState('')
  // ★ 一次多取一些（* 项目平均几百个节点），在本地过滤，⛔ 不做后端搜索 ⚠
  const nodes = useGraphNodes(projectRef, { limit: 1000, enabled: open })
  const items = nodes.data?.items || []

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase()
    if (!kw) return items.slice(0, 40)
    return items
      .filter(
        (n) =>
          n.name.toLowerCase().includes(kw) ||
          (n.qname || '').toLowerCase().includes(kw) ||
          (n.file_path || '').toLowerCase().includes(kw),
      )
      .slice(0, 60)
  }, [items, q])

  return (
    <Modal open={open} onClose={onClose} title="改挂载的节点">
      <div className="flex flex-col gap-3">
        <div className="faint" style={{ fontSize: 12, lineHeight: 1.7 }}>
          每篇笔记必须挂在一个代码节点上。挂错了就在这儿换一个 —— 正文和段评都不受影响。
        </div>

        <div className="relative">
          <Search
            size={13}
            className="absolute left-2.5 top-1/2 -translate-y-1/2"
            style={{ color: 'var(--text-sub)' }}
          />
          <input
            className="input"
            autoFocus
            placeholder="搜函数 / 类 / 文件名…"
            style={{ paddingLeft: 28, fontSize: 13 }}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        <div style={{ maxHeight: 340, overflow: 'auto' }} className="flex flex-col gap-1">
          {nodes.isLoading && (
            <div className="faint" style={{ fontSize: 12.5 }}>
              加载中…
            </div>
          )}
          {!nodes.isLoading && filtered.length === 0 && (
            <div className="faint" style={{ fontSize: 12.5 }}>
              没有匹配的节点
            </div>
          )}
          {filtered.map((n: GraphNode) => {
            const active = n.vid === currentVid
            return (
              <button
                key={n.uid}
                type="button"
                onClick={() => onPick(n.vid, n.name)}
                className="w-full text-left"
                style={{
                  padding: '7px 10px',
                  borderRadius: 8,
                  border: `1px solid ${active ? 'var(--accent)' : 'transparent'}`,
                  background: active ? 'var(--accent-dim)' : 'transparent',
                  cursor: 'pointer',
                }}
              >
                <div className="flex items-center gap-2">
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{n.name}</span>
                  <span className="tag" style={{ fontSize: 10 }}>
                    {n.kind}
                  </span>
                  {active && (
                    <span className="faint" style={{ fontSize: 11 }}>
                      · 就是它
                    </span>
                  )}
                </div>
                <div
                  className="faint"
                  style={{ fontSize: 11, marginTop: 2, fontFamily: 'var(--font-mono, monospace)' }}
                >
                  {n.file_path}
                  {n.line ? `:${n.line}` : ''}
                </div>
              </button>
            )
          })}
        </div>
      </div>
    </Modal>
  )
}
