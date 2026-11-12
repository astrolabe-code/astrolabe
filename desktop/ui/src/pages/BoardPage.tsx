import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import ThinkingBoard from '../components/notes/ThinkingBoard'
import { useNotes } from '../query/notes'

/**
 * ★★ **白板页**：白板就是挂载在节点上的一篇「特殊笔记」，所以它和笔记一样
 * 有自己的真实路由 `/p/<项目>/board/<白板id>`，标签栏按 URL 自动显示它。
 *
 * · `?node=<vid>`：挂在哪一个节点上（新建 / 列表打开时带上）
 * · `?focus=<全局卡片id>`：从笔记卡片的「链」进来时聚焦那张卡
 */
export default function BoardPage() {
  const { projectRef = '', boardId = '' } = useParams()
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const notes = useNotes(projectRef) // 与笔记列表同一份数据：卡片就是笔记
  const nodeId = Number(sp.get('node') || 0)

  return (
    <ThinkingBoard
      open
      projectRef={projectRef}
      nodeId={nodeId}
      boardId={boardId}
      notes={notes.data || []}
      focusCardId={sp.get('focus') || undefined}
      onClose={() => nav(`/p/${encodeURIComponent(projectRef)}`)}
    />
  )
}
