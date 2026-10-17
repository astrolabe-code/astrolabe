import { ThumbsUp } from 'lucide-react'
import type { AnchorKind } from '../../api/types'
import { useLikeStatus, useLikeToggle } from '../../query/likes'
import { useMe } from '../../hooks/useMe'

/**
 * ★ 点赞按钮（`F3` · D92 之外的互动层第一件）
 *
 * ## ★★★ B站机制（`B211` / `D89` · 所有者三次纠正后定论）
 *
 * ```
 * · ★ 竖大拇指图标；* 点一下 ⇒* **符号变红**，* 再点一下 ⇒* **符号变灰** ✅
 * · ★★ **计数只信服务端回包**（* 合并数不是 UI 能本地 ±1 的数字）✅
 * · ★★ 防抖 1.2 秒在 `useLikeToggle` 里（* 省写库，* `D91`）✅
 * · ★ 初始态来自 `GET .../likes/`（* `B211`③：* 刷新后恢复红拇指）✅
 * ```
 *
 * ⚠ 游客：**只显示计数**、不可点（未登录没有状态可改）✅
 * ⚠ `pending`（防抖窗口里）给一个极轻的视觉提示 —— ⛔ 不做倒计时动画（分散注意）⚠
 */
interface LikeButtonProps {
  noteId: number
  /** 章赞（默认）/ 段赞 */
  anchor?: AnchorKind
  /** 段赞必填 */
  blockId?: number | null
  size?: 'sm' | 'md'
}

export default function LikeButton({
  noteId,
  anchor = 'chapter',
  blockId,
  size = 'md',
}: LikeButtonProps) {
  const me = useMe()
  const authed = !!me.data?.authenticated
  const status = useLikeStatus(noteId, anchor, blockId)
  const t = useLikeToggle(noteId, anchor, {
    liked: status.data?.liked ?? false,
    like_count: status.data?.like_count ?? 0,
  })

  const dim = size === 'sm' ? 12 : 15
  const liked = t.liked

  return (
    <button
      type="button"
      disabled={!authed}
      onClick={t.toggle}
      title={authed ? (liked ? '取消赞' : '点赞') : '登录后可点赞'}
      className="flex items-center gap-1.5"
      style={{
        padding: size === 'sm' ? '2px 6px' : '5px 10px',
        borderRadius: 999,
        fontSize: size === 'sm' ? 11.5 : 12.5,
        border: `1px solid ${liked ? 'var(--err)' : 'var(--card-border)'}`,
        // ★★ `D89`：红 = 赞过、灰 = 没有 ——* 图标颜色就是「我赞过没有」的答案 ✅
        color: liked ? 'var(--err)' : 'var(--text-sub)',
        background: liked ? 'color-mix(in srgb, var(--err) 8%, transparent)' : 'transparent',
        cursor: authed ? 'pointer' : 'default',
        opacity: t.pending ? 0.75 : 1,
      }}
    >
      <ThumbsUp size={dim} fill={liked ? 'currentColor' : 'none'} />
      <span>{t.like_count}</span>
    </button>
  )
}
