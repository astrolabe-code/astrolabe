import { useEffect, useState } from 'react'
import { patchRibbon, clearRibbon } from '../../lib/ribbonBus'
import type { Note, NoteKind } from '../../api/types'
import { useNotes } from '../../query/notes'
import { errorMessage } from '../../api/errors'
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
  /** 能否写（个人版恒为 true，没有身份判断） */
  canWrite: boolean
  /** 当前登录用户名（判断"是不是我写的"用） */
  /** ★★ `F3`：点卡片进阅读页（NoteCard 内部 navigate，这里只作预留扩展位） */
  onOpenNote?: (note: Note) => void
  /** 新建笔记（打开编辑器） */
  onCreateNote: () => void
  /** ★★ `F3`：编辑某篇（打开编辑器） */
  onEditNote: (note: Note) => void
  /** ★★ 删除某篇（* 卡片上的「删除」与弹窗里的删除共用同一个确认框）⚠ */
  onDeleteNote?: (note: Note) => void
  /** ★ 深入：新开一张空白笔记，挂成这篇文章的子代 */
  onDeriveNote?: (note: Note) => void
  /** ★ 参见：引用已写好的笔记 */
  onSeeAlsoNote?: (note: Note) => void
  /** ★ 链：打开这个节点的白板（走真实路由） */
  onSeeChainNote?: (note: Note) => void
}

export default function NoteSection({
  projectRef,
  nodeId,
  canWrite,
  onOpenNote,
  onCreateNote,
  onEditNote,
  onDeleteNote,
  onDeriveNote,
  onSeeAlsoNote,
  onSeeChainNote,
}: NoteSectionProps) {
  // ★★★ 当前选中的「盒子」：* 'all' = 全部（按分组展示）；* 否则只看这一类 ⚠
  const [activeKind, setActiveKind] = useState<NoteKind | 'all'>('all')
  const notes = useNotes(projectRef)  // 取当前项目全部笔记

  // ★ 只把「新建笔记」注册给全局 ribbon（TabBar 的 ＋ 用）
  //   ★★ 白板是节点下的一篇特殊笔记，有自己的真实路由 ⇒ 不再在这里挂覆盖层
  useEffect(() => {
    patchRibbon({ createNote: onCreateNote })
    return () => clearRibbon(['createNote'])
  }, [onCreateNote])

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
  /**
   * ★★★ 2026-10-28（`D134`）：**空盒子也保留** ⚠
   *
   * 所有者：「**突然明白的一件事这些提示只有写了笔记才能看到，没写笔记，
   *   相应的盒子就没有提示，我感觉不行**」
   *
   * ⚠ 原来 `.filter(items.length > 0)` 会把空类别整组删掉 ⇒
   *   某个节点只有「灵光一闪」，另外四个盒子（连同它们的说明）**从不出现** ⇒
   *   用户只能靠记忆，而"不用记"正是这套分类的前提 ⚠
   */
  const groups = NOTE_KINDS.map((kind: NoteKind) => ({
    kind,
    items: mine.filter((n) => n.kind === kind),
  }))
  // ★★ 五个盒子的**各自数量**（* 0 也显示，* 一眼看出这节点哪类多）⚠
  const counts = NOTE_KINDS.map((kind: NoteKind) => ({
    kind,
    n: mine.filter((x) => x.kind === kind).length,
  }))

  // ★ 当前要展示的分组：* 全部 ⇒ 原分组（可折叠）；* 某类 ⇒ 只留那一组 ⚠
  const visibleGroups =
    activeKind === 'all'
      ? groups   /* ★ 五个盒子全显示（`D134`）：空的只有一行，成本很低 ⚠ */
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
      title={
        key === 'all'
          ? '显示全部笔记'
          : `${KIND_META[key].hint}（点一下只看「${label}」）`
      }
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
    <div className="note-section">
      {/* ★★★ 2026-11-07：标题行整行删掉，按钮并入 chips 行
          所有者：「这些信息和功能按钮占了3排，而vscode没有，
                    过于想把信息按钮放在显眼的位置了」
          · 「笔记」标题与 tab 名重复 ⇒ 删
          · 思考模式 / 写笔记 改成细线小图标按钮，靠右放在 chips 行末尾
          ⇒ 从两排压成一排，功能一个不少 */}

      <div className="note-head-chips">
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

      <div className="flex flex-col gap-4">
        {visibleGroups.map((g) => (
          <div key={g.kind}>
            {/* ⚠ 空盒子也显示这一行（`D134`）：说明文字必须在**没写笔记时**也看得到，
                否则用户只能靠记 —— 而「不用记」正是这套分类成立的前提 ⚠ */}
            <div
              className="flex items-center gap-2 mb-1.5"
              style={{ opacity: g.items.length === 0 ? 0.6 : 1 }}
            >
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
              <span
                className="faint"
                style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                · {KIND_META[g.kind].hint}
              </span>
              {g.items.length === 0 && (
                <span className="faint" style={{ fontSize: 10.5, marginLeft: 'auto', flexShrink: 0 }}>
                  还没有
                </span>
              )}
            </div>
            <div className="flex flex-col gap-2" style={{ display: g.items.length ? undefined : 'none' }}>
              {g.items.map((n) => (
                <NoteCard
                  key={n.id}
                  note={n}
                  projectRef={projectRef}
                  canWrite={canWrite}
                  onEdit={onEditNote}
                  onDelete={onDeleteNote}
                  onDerive={onDeriveNote}
                  onSeeAlso={onSeeAlsoNote}
                  onSeeChain={onSeeChainNote}
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

    </div>
  )
}
