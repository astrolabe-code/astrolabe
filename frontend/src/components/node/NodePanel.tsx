import { useState } from 'react'
import { FileCode2 } from 'lucide-react'
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
}

export default function NodePanel({ projectRef, node, canWrite, meUsername }: NodePanelProps) {
  const [editing, setEditing] = useState<Note | null>(null)
  const [creating, setCreating] = useState(false)
  const [readOnlyNote, setReadOnlyNote] = useState<Note | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Note | null>(null)
  const [delErr, setDelErr] = useState('')
  const del = useDeleteNote()

  if (!node) {
    return (
      <div className="card flex items-center justify-center" style={{ minHeight: 320, padding: 24 }}>
        <div className="faint" style={{ fontSize: 13 }}>
          从左边选一个节点，看别人在这里写了什么 —— 或者写下你自己的。
        </div>
      </div>
    )
  }

  const noteWritable = (n: Note) => canWrite || n.created_by === meUsername

  const openNote = (n: Note) => {
    // ★ 能写 ⇒ 编辑器；不能写 ⇒ 只读查看（同一组件两种模式，⛔ 不另做一套）✅
    if (noteWritable(n)) setEditing(n)
    else setReadOnlyNote(n)
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
    <div className="flex flex-col gap-3">
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
        </div>
        {node.qname && node.qname !== node.name && (
          <div className="mono faint" style={{ fontSize: 11.5, marginTop: 4 }}>
            {node.qname}
          </div>
        )}
        <div className="mono faint" style={{ fontSize: 11.5, marginTop: 2 }}>
          {node.file_path}:{node.line} · {node.lang}
        </div>
      </div>

      {/* ② 笔记区 */}
      <div className="card" style={{ padding: '12px 14px' }}>
        <NoteSection
          projectRef={projectRef}
          nodeId={node.vid}
          canWrite={canWrite}
          meUsername={meUsername}
          onOpenNote={openNote}
          onCreateNote={() => setCreating(true)}
        />
      </div>

      {/* ③ 编辑器 / 只读 */}
      <NoteEditor
        open={creating || !!editing || !!readOnlyNote}
        note={editing}
        projectRef={projectRef}
        nodeId={node.vid}
        readOnly={!!readOnlyNote && !editing}
        onDelete={editing ? () => setPendingDelete(editing) : undefined}
        onClose={() => {
          setCreating(false)
          setEditing(null)
          setReadOnlyNote(null)
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
