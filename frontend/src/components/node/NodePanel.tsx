import { useState } from 'react'
import { FileCode2, ChevronUp, ChevronDown } from 'lucide-react'
import type { Note } from '../../api/types'
import type { GraphNode } from '../../lib/mergeGraph'
import { useDeleteNote } from '../../query/notes'
import { errorMessage } from '../../api/errors'
import ConfirmDialog from '../ui/ConfirmDialog'
import NoteEditor from '../notes/NoteEditor'
import NoteSection from '../notes/NoteSection'

/**
 * ★ 节点面板（`F2` · D92）——* 双栏的右栏
 *
 * ## 职责
 *
 * | 块 | 内容 |
 * |---|---|
 * | ① | 节点信息（名称 / qname / 文件:行 / 类型 / 语言） |
 * | ② | **笔记区**（`NoteSection`：按 kind 分组） |
 * | ③ | 编辑器 / 只读查看（`NoteEditor`） |
 * | ④ | 删除确认（`ConfirmDialog` + `B210` 文案） |
 *
 * ⚠★ 删除文案是**硬约束**（`D92`⑤ / `B210` / `D86③）：
 *   「删除后可从回收站恢复」——* ⛔ **不得**向用户承诺「彻底删除」⚠
 *   （* 彻底删除只有管理员下架一条路，* 且**不可恢复**）⚠
 */
interface NodePanelProps {
  projectRef: string
  node: GraphNode | null
  /** 项目级写权限（后端 `can_edit` 字段） |
   *  ⚠ 作者本人另算（`NoteSection` 里按 `created_by` 判）✅ */
  canWrite: boolean
  /** 当前登录用户名（判断"是不是我写的"） */
  meUsername?: string
  /** ★★ `D106`：这个节点在学习路径里的序号（* null = 不在路径里）⚠ */
  inPathOrdinal?: number | null
  /** ★★ `D106`：能不能改学习路径（* owner ∨ 协作者）⚠ */
  canEditPath?: boolean
  /** ★★ `D106`：加入路径 */
  onAddToPath?: () => void
  /** ★★ `D106`：从路径移除 */
  onRemoveFromPath?: () => void
}

export default function NodePanel({
  projectRef,
  node,
  canWrite,
  meUsername,
  inPathOrdinal,
  canEditPath,
  onAddToPath,
  onRemoveFromPath,
}: NodePanelProps) {
  const [editing, setEditing] = useState<Note | null>(null)
  const [creating, setCreating] = useState(false)
  // ★★ 节点信息区可**收起**（* 给下面写作腾位置）⚠
  const [infoOpen, setInfoOpen] = useState(true)
  const [pendingDelete, setPendingDelete] = useState<Note | null>(null)
  const [delErr, setDelErr] = useState('')
  const del = useDeleteNote()

  if (!node) {
    return (
      <div
        className="card flex items-center justify-center"
        style={{ flex: 1, minHeight: 320, padding: 24 }}
      >
        <div className="faint" style={{ fontSize: 13 }}>
          从左边选一个节点，看别人在这里写了什么 —— 或者写下你自己的。
        </div>
      </div>
    )
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    setDelErr('')
    try {
      await del.mutateAsync(pendingDelete.id)
      setPendingDelete(null)
    } catch (e) {
      setDelErr(errorMessage(e))
    }
  }

  return (
    // ★★ 根要撑满父容器（* 否则右侧只到内容高度，* 下面空一大块）⚠
    <div className="flex flex-col gap-3" style={{ flex: 1, minHeight: 0 }}>
      {/* ① 节点信息 */}
      <div className="card" style={{ padding: '12px 14px' }}>
        <div className="flex items-center gap-2 flex-wrap">
          <FileCode2 size={14} style={{ color: 'var(--text-sub)' }} />
          <span className="mono" style={{ fontSize: 14, fontWeight: 600 }}>
            {node.name}
          </span>
          <span className="tag" style={{ fontSize: 10.5 }}>
            {node.kind}
          </span>
          {/* ★★ 收起 / 展开（* 收起后只留这一行，* 笔记区自动变大）⚠ */}
          <button
            type="button"
            onClick={() => setInfoOpen((v) => !v)}
            title={infoOpen ? '收起节点信息' : '展开节点信息'}
            aria-label={infoOpen ? '收起节点信息' : '展开节点信息'}
            style={{
              marginLeft: 'auto',
              display: 'inline-flex',
              alignItems: 'center',
              background: 'none',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              color: 'var(--text-sub)',
            }}
          >
            {infoOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
        {infoOpen && (
        <>
        {node.qname && node.qname !== node.name && (
          <div className="mono faint" style={{ fontSize: 11.5, marginTop: 4 }}>
            {node.qname}
          </div>
        )}
        <div className="mono faint" style={{ fontSize: 11.5, marginTop: 2 }}>
          {node.file_path}:{node.line} · {node.lang}
        </div>
        {/* ★★ `D106`：学习路径入口（* 作者才能改；* 在路径里显示序号）⚠ */}
        {canEditPath && (
          <div className="flex items-center gap-2" style={{ marginTop: 8 }}>
            {inPathOrdinal != null ? (
              <>
                <span className="tag" style={{ fontSize: 10.5 }}>
                  学习路径第 {inPathOrdinal + 1} 个
                </span>
                <button
                  type="button"
                  className="faint"
                  style={{ fontSize: 11.5, cursor: 'pointer', background: 'none', border: 'none' }}
                  onClick={onRemoveFromPath}
                >
                  从路径移除
                </button>
              </>
            ) : (
              <button
                type="button"
                style={{
                  fontSize: 11.5,
                  cursor: 'pointer',
                  color: 'var(--accent)',
                  background: 'none',
                  border: 'none',
                  padding: 0,
                }}
                onClick={onAddToPath}
              >
                + 加入学习路径
              </button>
            )}
          </div>
        )}
        </>
        )}
      </div>

      {/* ② 笔记区：* 吃掉剩余高度，* 内容多了在自己内部滚（* 不把整页撑高）⚠ */}
      <div
        className="card"
        style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '12px 14px' }}
      >
        <NoteSection
          projectRef={projectRef}
          nodeId={node.vid}
          canWrite={canWrite}
          meUsername={meUsername}
          onOpenNote={() => {
            /* ★★ `F3`：点卡片进**阅读页**（NoteCard 内部 navigate）——
               这里不需要再做跳转，⛔ 不留空转的入口 ✅ */
          }}
          onCreateNote={() => setCreating(true)}
          onEditNote={setEditing}
        />
      </div>

      {/* ③ 编辑器（只承担「新建 / 编辑」—— 阅读与互动在 NotePage） */}
      <NoteEditor
        open={creating || !!editing}
        note={editing}
        projectRef={projectRef}
        nodeId={node.vid}
        onDelete={editing ? () => setPendingDelete(editing) : undefined}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
        onSaved={() => {
          // ⚠ 保存后刷新由 react-query 的 invalidate 负责（useUpdateNote 内部已做）✅
        }}
      />

      {/* ④ 删除确认 */}
      <ConfirmDialog
        open={!!pendingDelete}
        title="删除笔记"
        danger
        loading={del.isPending}
        error={delErr}
        confirmText="删除"
        message={
          pendingDelete
            ? `删除「${pendingDelete.title || '（无标题）'}」？\n删除后可从回收站恢复，评论和点赞都还在。`
            : ''
        }
        onConfirm={confirmDelete}
        onCancel={() => {
          setPendingDelete(null)
          setDelErr('')
        }}
      />
    </div>
  )
}
