import type { Comment } from '../../api/types'

/**
 * ★★ **这条评论当前用户能不能删**（* `B207`⑤ 的前端侧判据）⚠
 *
 * ★★ 后端口径（* 逐字原话）：「协作者跟作者与管理员一样，可以删别人评论。」✅
 *
 * | 谁能删 | 前端凭什么知道 |
 * |---|---|
 * | 评论作者本人 | `comment.created_by === meUsername` |
 * | 项目 owner / 协作者 | `project.can_edit`（* `F2` 从项目详情拿的字段）✅ |
 * | 站点管理员 | `me.is_staff` |
 *
 * ⚠★ **前端判据只决定「渲染不渲染」**（* `D74` 的口径）——
 *   · · ★★ 真正的拦截在后端（* `comment_deletable` 判据，* `B209` 收束）✅
 *   · · ★ 两边口径必须一致，* 否则用户看到按钮却 403（* 差体验）⚠
 */
export function commentDeletable(comment: Comment, ctx: DeletePerm): boolean {
  if (ctx.meUsername && comment.created_by === ctx.meUsername) return true
  if (ctx.canEdit) return true
  if (ctx.isStaff) return true
  return false
}

/** ★ 删除判据的上下文（* `CommentItem` / 两个区都收这个，* ⛔ 不收布尔）⚠ */
export interface DeletePerm {
  meUsername?: string
  canEdit?: boolean
  isStaff?: boolean
}
