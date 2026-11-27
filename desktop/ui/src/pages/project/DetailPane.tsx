/**
 * 列表页右栏：按 URL 显示「节点面板 / 笔记正文 / 白板」三选一。
 *
 * ## 为什么不再用 CodeWorkspace
 *
 * 所有者：「这个 CodeWorkspace 已经被我放弃了，这个页面的设计我觉得不好的」
 *
 * CodeWorkspace 有文件树 + 5 个 tab（代码/笔记/内容/仿写/问答），
 * 但列表页右栏只用得到其中三件事：
 *   · 没选中笔记 ⇒ 节点面板（笔记列表）
 *   · `noteView`  ⇒ 笔记正文（读 / 编辑）
 *   · `boardView` ⇒ 白板
 * 文件树、代码 tab、仿写、问答在这里全是多余的 ⇒ 换成本组件。
 *
 * ⛔ 文件树归全局 Explorer（Ribbon 面板）；本页不重复提供。
 */
import { useNavigate } from 'react-router-dom'
import NoteEditPage from '../NoteEditPage'
import ThinkingBoard from '../../components/notes/ThinkingBoard'
import NodePanel from '../../components/node/NodePanel'
import { useNotes } from '../../query/notes'
import type { GraphNode } from '../../lib/mergeGraph'

export interface NoteViewSpec {
  mode: 'read' | 'edit'
  ref: string | null
  nodeId: number
  parent?: string
}

export interface BoardViewSpec {
  boardId: string
  nodeId: number
  focus?: string
}

interface DetailPaneProps {
  projectRef: string
  node: GraphNode | null
  canWrite: boolean
  noteView?: NoteViewSpec
  boardView?: BoardViewSpec
}

export default function DetailPane({
  projectRef,
  node,
  canWrite,
  noteView,
  boardView,
}: DetailPaneProps) {
  const nav = useNavigate()
  const notesQ = useNotes(projectRef, { limit: 2000 })

  if (boardView) {
    return (
      <ThinkingBoard
        open
        projectRef={projectRef}
        nodeId={boardView.nodeId}
        boardId={boardView.boardId}
        notes={notesQ.data || []}
        focusCardId={boardView.focus}
        onClose={() => nav(`/p/${encodeURIComponent(projectRef)}`)}
      />
    )
  }

  if (noteView) {
    return (
      <NoteEditPage
        key={`${noteView.ref ?? 'new'}-${noteView.mode}`}
        projectRef={projectRef}
        noteRef={noteView.ref || undefined}
        nodeId={noteView.nodeId}
        parent={noteView.parent}
        initialMode={noteView.mode}
        onNavigate={(p) => nav(p)}
      />
    )
  }

  return <NodePanel projectRef={projectRef} node={node} canWrite={canWrite} flat hideInfo />
}
