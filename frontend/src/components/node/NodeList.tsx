import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Search } from 'lucide-react'
import type { GraphNode } from '../../lib/mergeGraph'
import { useGraphNodes } from '../../query/graph'
import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'

/**
 * ★ 节点列表（`F2` · 契约 D92）
 *
 * ⚠★ **刻意不做图谱画布** ——* 那是 2b 的活，* 值得单独一批做好 ✅
 *   · · ★ 本组件只回答一件事：* 「**怎么走到某个节点**」⚠
 *
 * ## 三条口径
 *
 * | # | 口径 |
 * |---|---|
 * | ① | ★ 搜索按 `name` / `qname` 命中（⛔ 不按 file_path —— 那样搜出来太杂） |
 * | ② | ★ kind 过滤用**数据里出现过的**种类（⛔ 不写死 —— 后端可能加新种类） |
 * | ③ | ★ 分页「加载更多」而不是无限滚动（一次一页，请求可数） |
 */
interface NodeListProps {
  projectRef: string
  /** 当前选中的节点 uid（受控） */
  selectedUid?: string | null
  onSelect: (node: GraphNode) => void
  /** ★ `?think=1`：* 列表就绪后自动选中第一个节点（* 让思考白板有节点可开）⚠ */
  autoSelectFirst?: boolean
  /**
   * ★★ `?node=<vid>` 深链（`D120` · 2026-10-27）⚠
   *
   * 用途：「继续上次」跳回来时，自动选中那个节点 ⚠
   * ⚠ 用 **stable_vid**（和 `reading_path` 一致），⛔ 不是自增 id、也不是 uid ⚠
   */
  selectVid?: number
}

const PAGE = 100

export default function NodeList({
  projectRef,
  selectedUid,
  onSelect,
  autoSelectFirst,
  selectVid,
}: NodeListProps) {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const [limit, setLimit] = useState(PAGE)

  const nodes = useGraphNodes(projectRef, { limit })

  const items = nodes.data?.items || []
  const total = nodes.data?.total || 0

  /** ★ kind 过滤选项从**数据里出现过的**种类来（口径②） */
  const kinds = useMemo(() => {
    const set = new Set(items.map((n) => n.kind).filter(Boolean))
    return [...set].sort()
  }, [items])

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return items.filter((n) => {
      if (kind && n.kind !== kind) return false
      if (!kw) return true
      return (
        n.name.toLowerCase().includes(kw) || (n.qname || '').toLowerCase().includes(kw)
      )
    })
  }, [items, q, kind])

  /**
   * ★★ `selectVid`：把深链指向的节点选中（`D120`）⚠
   *
   * ⚠ 列表是**分页**的（`PAGE=100`）⇒ 目标可能还没加载
   *   ⇒ 找不到就扩大 limit 重取一次（* 上限 2000，防止大项目拉全量）⚠
   * ⚠ 只做一次（`ref` 守门）—— 之后用户怎么点都不干预 ✅
   */
  const deepLinkDone = useRef(false)
  useEffect(() => {
    if (!selectVid || deepLinkDone.current) return
    if (nodes.isLoading) return
    const hit = items.find((n) => n.vid === selectVid)
    if (hit) {
      deepLinkDone.current = true
      if (hit.uid !== selectedUid) onSelect(hit)
      return
    }
    // ★ 还没加载到 ⇒ 扩大一次（* 最多到 2000）⚠
    if (items.length < total && limit < 2000) {
      setLimit(Math.min(2000, Math.max(total, limit * 4)))
    } else {
      // ★ 图里压根没这个 vid（* 代码变了 / 存档过期）⇒ 放弃，⛔ 别无限重试 ⚠
      deepLinkDone.current = true
    }
  }, [selectVid, items, total, limit, nodes.isLoading, onSelect, selectedUid])

  // ★★ `autoSelectFirst`：* 只在**第一次**列表就绪时选一个，* 之后不再干预用户 ⚠
  const autoPicked = useRef(false)
  useEffect(() => {
    if (!autoSelectFirst || autoPicked.current) return
    if (selectedUid) {
      autoPicked.current = true
      return
    }
    if (filtered.length > 0) {
      autoPicked.current = true
      onSelect(filtered[0])
    }
  }, [autoSelectFirst, filtered, onSelect, selectedUid])

  if (nodes.isError) {
    return (
      <div className="card" style={{ padding: 20 }}>
        <div className="text-sm" style={{ color: 'var(--err)' }}>
          节点列表加载失败：项目不存在或无权访问。
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 mb-3">
        <div className="relative flex-1">
          <Search
            size={13}
            className="absolute left-2.5 top-1/2 -translate-y-1/2"
            style={{ color: 'var(--text-sub)' }}
          />
          <input
            className="input"
            style={{ paddingLeft: 28, fontSize: 13 }}
            placeholder="搜索函数 / 类 / 文件…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {kinds.length > 1 && (
          <select
            className="input"
            style={{ width: 108, fontSize: 13 }}
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            aria-label="按类型过滤"
          >
            <option value="">全部类型</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto pr-1">
        {nodes.isLoading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 size={16} className="animate-spin" style={{ color: 'var(--text-sub)' }} />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState title="没有匹配的节点" hint={q ? `换个关键词试试（当前：${q}）` : '这个项目还没有可读的节点'} />
        ) : (
          <ul className="flex flex-col gap-1">
            {filtered.map((n) => {
              const active = selectedUid === n.uid
              return (
                <li key={n.uid}>
                  <button
                    type="button"
                    onClick={() => onSelect(n)}
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
                      <span className="mono" style={{ fontSize: 12.5, color: 'var(--text-main)' }}>
                        {n.name}
                      </span>
                      <span className="tag" style={{ fontSize: 10.5 }}>
                        {n.kind}
                      </span>
                    </div>
                    {/* ★ 空白结构没有文件/行号 ⇒ **整行不渲染**（类型上面那个 tag 已经显示过了）⚠ */}
                    {n.file_path && (
                      <div className="faint mono" style={{ fontSize: 11, marginTop: 2 }}>
                        {n.file_path}:{n.line}
                      </div>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {items.length < total && (
        <div className="pt-3">
          <Button
            block
            loading={nodes.isFetching}
            onClick={() => setLimit((v) => v + PAGE)}
          >
            加载更多（已显示 {items.length} / {total}）
          </Button>
        </div>
      )}
    </div>
  )
}
