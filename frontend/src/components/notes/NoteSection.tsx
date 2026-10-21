import { useEffect, useRef, useState } from 'react'
import { Layers, Lightbulb, Plus } from 'lucide-react'
import type { Note, NoteKind } from '../../api/types'
import { useNotes } from '../../query/notes'
import { errorMessage } from '../../api/errors'
import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'
import NoteCard from './NoteCard'
import { NOTE_KINDS, KIND_META } from './kindMeta'
import ThinkingBoard from './ThinkingBoard'
import BatchVisibility from './BatchVisibility'

/**
 * ★ 一个节点的笔记区（`F2` · D92）
 *
 * ## ★★ 按 kind 分组（`B201` 的产品前提）
 *
 * ⚠★ 所有者原话整句：「**笔记以后我会划分为几个类型…分别放入一个节点下的四个不同盒子**」
 *   ⇒ ★「盒子」是**展示分组**，* ⛔ 不是容器（* ❌ 不是五种表）✅
 *
 * ## 三条口径
 *
 * | # | 口径 |
 * |---|---|
 * | ① | ★ 只有**非空**的组才显示（空组不占地方） |
 * | ② | ★ 组标题带**计数**（一眼看出这节点哪类笔记多） |
 * | ③ | ★ 写入口（新建/编辑）按 `canWrite` 渲染 ——* 普通登录用户与游客看到**只读**版 ⚠ |
 */
interface NoteSectionProps {
  projectRef: string
  nodeId: number
  /** 当前用户能否写（前端拿 `project.can_edit`；作者本人另行判断） */
  canWrite: boolean
  /** 当前登录用户名（判断"是不是我写的"用） */
  meUsername?: string
  /** ★★ `F3`：点卡片进阅读页（NoteCard 内部 navigate，这里只作预留扩展位） */
  onOpenNote?: (note: Note) => void
  /** 新建笔记（打开编辑器） */
  onCreateNote: () => void
  /** ★★ `F3`：编辑某篇（打开编辑器） */
  onEditNote: (note: Note) => void
  /** ★★ 删除某篇（* 卡片上的「删除」与弹窗里的删除共用同一个确认框）⚠ */
  onDeleteNote?: (note: Note) => void
  /** ★ `?think=1`：* 进入后自动打开思考白板（* 只自动开一次）⚠ */
  autoThink?: boolean
}

export default function NoteSection({
  projectRef,
  nodeId,
  canWrite,
  meUsername,
  onOpenNote,
  onCreateNote,
  onEditNote,
  onDeleteNote,
  autoThink,
}: NoteSectionProps) {
  const [showAll, setShowAll] = useState(false)
  // ★★★ 当前选中的「盒子」：* 'all' = 全部（按分组展示）；* 否则只看这一类 ⚠
  const [activeKind, setActiveKind] = useState<NoteKind | 'all'>('all')
  // ★★★ **思考模式**：* 白布上自由排布卡片（* 所有者要求）⚠
  const [thinkingOpen, setThinkingOpen] = useState(false)
  // ★ 批量改公开 / 私有（* 所有者：勾选排除，其余批量改）⚠
  const [batchOpen, setBatchOpen] = useState(false)
  const notes = useNotes(projectRef, { limit: 200 })

  // ★★ 首页「思考模式」卡片直达：* 数据就绪后自动开一次白板 ⚠
  const autoOpened = useRef(false)
  useEffect(() => {
    if (!autoThink || autoOpened.current) return
    if (notes.isLoading) return
    autoOpened.current = true
    setThinkingOpen(true)
  }, [autoThink, notes.isLoading])

  if (notes.isError) {
    return (
      <div className="text-sm" style={{ color: 'var(--err)' }}>
        笔记加载失败：{errorMessage(notes.error)}
      </div>
    )
  }
  if (notes.isLoading) {
    return <div className="faint" style={{ fontSize: 12.5 }}>笔记加载中…</div>
  }

  // ⚠★ 这个节点上的笔记（`node_id` 过滤）
  const mine = (notes.data || []).filter((n) => n.node_id === nodeId)

  /** ★ 每种 kind 一组（`B201`：固定 5 种；顺序按 NOTE_KINDS，⛔ 不打乱） */
  const groups = NOTE_KINDS.map((kind: NoteKind) => ({
    kind,
    items: mine.filter((n) => n.kind === kind),
  })).filter((g) => g.items.length > 0)

  if (groups.length === 0) {
    return (
      <>
        <EmptyState
          title="这个节点还没有笔记"
          hint={
            canWrite
              ? '做第一个写笔记的人 —— 你的一闪念，可能正好解开别人的困惑'
              : '登录后可撰写笔记'
          }
          action={
            canWrite ? (
              <Button variant="primary" icon={<Plus size={14} />} onClick={onCreateNote}>
                写笔记
              </Button>
            ) : undefined
          }
        />
        {/* ★★ 空节点也要能开白板（* 首页「思考模式」卡片直达到空节点时）⚠ */}
        <ThinkingBoard
          open={thinkingOpen}
          projectRef={projectRef}
          nodeId={nodeId}
          notes={mine}
          onClose={() => setThinkingOpen(false)}
        />
        <BatchVisibility
          open={batchOpen}
          projectRef={projectRef}
          onClose={() => setBatchOpen(false)}
        />
      </>
    )
  }

  // ★★ 五个盒子的**各自数量**（* 0 也显示，* 一眼看出这节点哪类多）⚠
  const counts = NOTE_KINDS.map((kind: NoteKind) => ({
    kind,
    n: mine.filter((x) => x.kind === kind).length,
  }))

  // ★ 当前要展示的分组：* 全部 ⇒ 原分组（可折叠）；* 某类 ⇒ 只留那一组 ⚠
  const visibleGroups =
    activeKind === 'all'
      ? showAll
        ? groups
        : groups.slice(0, 2)
      : groups.filter((g) => g.kind === activeKind)

  const chip = (
    key: NoteKind | 'all',
    label: string,
    n: number,
    color: string,
    active: boolean,
  ) => (
    <button
      key={key}
      type="button"
      onClick={() => setActiveKind(active && key !== 'all' ? 'all' : key)}
      title={key === 'all' ? '显示全部笔记' : `只看「${label}」`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 9px',
        borderRadius: 999,
        fontSize: 11,
        lineHeight: '17px',
        cursor: 'pointer',
        whiteSpace: 'nowrap',
        // ★ 选中 = 同色实线 + 12% 淡底；* 未选 = 灰边透明底 ⚠
        border: `1px solid ${active ? color : 'var(--card-border)'}`,
        background: active ? `${color}1f` : 'transparent',
        color: active ? color : 'var(--text-sub)',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: 3,
          background: color,
          flexShrink: 0,
          opacity: active ? 1 : 0.55,
        }}
      />
      {label}
      <span style={{ opacity: 0.7 }}>{n}</span>
    </button>
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-2.5" style={{ gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap', minWidth: 0 }}>
          <span className="h2" style={{ fontSize: 14, flexShrink: 0 }}>
            笔记
          </span>
          {/* ★★★ **五个盒子各带数量** + 「全部」——* 点谁就只看谁 ⚠ */}
          {chip('all', '全部', mine.length, 'var(--text-sub)', activeKind === 'all')}
          {counts.map((c) =>
            chip(
              c.kind,
              KIND_META[c.kind].label,
              c.n,
              KIND_META[c.kind].color,
              activeKind === c.kind,
            ),
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          {/* ★★★ 批量改可见性（* 只有可写的人能看到）⚠ */}
          {canWrite && (
            <Button
              icon={<Layers size={14} />}
              onClick={() => setBatchOpen(true)}
              title="批量把本项目的笔记设为公开或私有（可勾选排除）"
            >
              批量
            </Button>
          )}
          {/* ★★★ 思考模式入口（* 任何人都能用，* 只读用户也能摆着看）⚠ */}
          <Button
            icon={<Lightbulb size={14} />}
            onClick={() => setThinkingOpen(true)}
            title="在白布上自由排布笔记卡片，理清它们之间的联系"
          >
            思考模式
          </Button>
          {canWrite && (
            <Button variant="primary" icon={<Plus size={14} />} onClick={onCreateNote}>
              写笔记
            </Button>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {visibleGroups.map((g) => (
          <div key={g.kind}>
            <div className="flex items-center gap-2 mb-1.5">
              {/* ★★ 每组一个**类型色圆点** + 同色标题（* 五个盒子一眼区分）⚠ */}
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  background: KIND_META[g.kind].color,
                  flexShrink: 0,
                }}
              />
              <span
                style={{ fontSize: 12.5, fontWeight: 600, color: KIND_META[g.kind].color }}
              >
                {KIND_META[g.kind].label}
              </span>
              <span className="faint" style={{ fontSize: 11 }}>
                {g.items.length}
              </span>
              <span className="faint" style={{ fontSize: 11 }}>
                · {KIND_META[g.kind].hint}
              </span>
            </div>
            <div className="flex flex-col gap-2">
              {g.items.map((n) => (
                <NoteCard
                  key={n.id}
                  note={n}
                  projectRef={projectRef}
                  canWrite={canWrite || n.created_by === meUsername}
                  onEdit={onEditNote}
                  onDelete={onDeleteNote}
                />
              ))}
            </div>
          </div>
        ))}

        {/* ★ 选了某个空盒子 ⇒ 给一句提示（* 而不是空白一片）⚠ */}
        {visibleGroups.length === 0 && (
          <div className="faint" style={{ fontSize: 12.5 }}>
            这个盒子里还没有笔记
          </div>
        )}
      </div>

      {/* ★★★ 思考模式白板（* fixed 覆盖层，* 位置按节点存 localStorage）⚠ */}
      <ThinkingBoard
        open={thinkingOpen}
        projectRef={projectRef}
        nodeId={nodeId}
        notes={mine}
        onClose={() => setThinkingOpen(false)}
      />
      {/* ★ 批量改可见性（* 正常分支也要渲染，否则有笔记时点「批量」没反应）⚠ */}
      <BatchVisibility
        open={batchOpen}
        projectRef={projectRef}
        onClose={() => setBatchOpen(false)}
      />

      {activeKind === 'all' && groups.length > 2 && (
        <div className="mt-3">
          <Button block onClick={() => setShowAll((v) => !v)}>
            {showAll ? '收起分组' : `展开其余 ${groups.length - 2} 个分组`}
          </Button>
        </div>
      )}
    </div>
  )
}
