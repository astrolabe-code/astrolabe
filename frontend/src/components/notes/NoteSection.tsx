import { useState } from 'react'
import { Plus } from 'lucide-react'
import type { Note, NoteKind } from '../../api/types'
import { useNotes } from '../../query/notes'
import { errorMessage } from '../../api/errors'
import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'
import NoteCard from './NoteCard'
import { NOTE_KINDS, KIND_META } from './kindMeta'

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
  onOpenNote: (note: Note) => void
  onCreateNote: () => void
}

export default function NoteSection({
  projectRef,
  nodeId,
  canWrite,
  meUsername,
  onOpenNote,
  onCreateNote,
}: NoteSectionProps) {
  const [showAll, setShowAll] = useState(false)
  const notes = useNotes(projectRef, { limit: 200 })

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
      <EmptyState
        title="这个节点还没有笔记"
        hint={canWrite ? '做第一个写笔记的人 —— 你的一闪念，可能正好解开别人的困惑' : '登录后可撰写笔记'}
        action={
          canWrite ? (
            <Button variant="primary" icon={<Plus size={14} />} onClick={onCreateNote}>
              写笔记
            </Button>
          ) : undefined
        }
      />
    )
  }

  const shown = showAll ? groups : groups.slice(0, 2)
  return (
    <div>
      <div className="flex items-center justify-between mb-2.5">
        <div className="h2" style={{ fontSize: 14 }}>
          笔记 <span className="faint">（{mine.length}）</span>
        </div>
        {canWrite && (
          <Button variant="primary" icon={<Plus size={14} />} onClick={onCreateNote}>
            写笔记
          </Button>
        )}
      </div>

      <div className="flex flex-col gap-4">
        {shown.map((g) => (
          <div key={g.kind}>
            <div className="flex items-center gap-2 mb-1.5">
              <span style={{ fontSize: 12.5, fontWeight: 600 }}>{KIND_META[g.kind].label}</span>
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
                  canWrite={canWrite || n.created_by === meUsername}
                  onOpen={onOpenNote}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {groups.length > 2 && (
        <div className="mt-3">
          <Button block onClick={() => setShowAll((v) => !v)}>
            {showAll ? '收起分组' : `展开其余 ${groups.length - 2} 个分组`}
          </Button>
        </div>
      )}
    </div>
  )
}
