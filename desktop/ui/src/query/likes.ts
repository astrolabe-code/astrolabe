import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import type { AnchorKind, LikeResult, LikeStatus } from '../api/types'

/**
 * ★ 点赞数据层（`B203⑤` / `B211` / `B212` / `D83` / `D91` · 契约 §22.4）
 *
 * ## ★★★ 本模块的三个出口
 *
 * | 出口 | 给谁用 | 说明 |
 * |---|---|---|
 * | `useLikeStatus` | ★★ **首屏** | `GET /api/notes/<id>/likes/` —— 初始态的服务端来源（`B211`③） |
 * | `useLikeMutation` | 特殊场景 | 裸 mutation，不做防抖 |
 * | ★★ `useLikeToggle` | ★★ **所有点赞按钮** | 开关 + 防抖 + 初始态来自 `useLikeStatus` |
 *
 * ## ★★★ B站机制（`B211`，所有者三次纠正后定论）
 *
 * ```
 * ⓪ ★★ **计数与状态是两套数据** ⚠
 *      · · ★ 计数 = 聚合合并（* 可滞后）· * 状态 = 每用户独立（* 要准）✅
 * ① ★★ 初始态来自服务端（* `GET .../likes/` ⇒ `{liked, like_count}`）✅
 *      · · ★ B站刷新后红拇指是恢复的 ——* 就是因为加载时知道你的状态 ✅
 * ② ★★ 图标是本地状态 ⇒* 点一下**立即翻**（* 红/灰）✅
 * ③ ★★★ **计数只信服务端回包** ⚠
 *      · · ★ 合并数不是 UI 能本地 ±1 的数字（* `B211`⑥：* 乐观计数已作废）⚠
 *      · · ★ 所以点下去计数**不变**，* 1.2s 防抖后发请求，* 回包才更新 ✅
 *      · · ★★ 这段滞后是**允许的**（* `B212`①：* 有界 + 自愈）✅
 * ④ ★★ 防抖 1–2 秒（* `D83` / `D91`）：* 少与服务器交互（* 服务器性能）——
 *      * ⛔ 不许当延迟优化掉 ✅
 * ⑤ ★★ 待发状态在页面隐藏 / 卸载时补发（* `D83④(a)`）⚠
 * ```
 *
 * ⚠★ 正确性红线（`B212`①）：**滞后无罪，漂移有罪** ——
 *   允许计数滞后 ≤1.2s / 卸载补发失败丢一次（±1 有界自愈）；
 *   ❌ 不许只涨不减、重复计（后端 `B211`①② 已修）。
 */

/** ⚠ 防抖时长（`D83`：1 秒（所有者：「等一秒」）；`D91`：省写库，不是延迟优化） */
const DEBOUNCE_MS = 1000

/**
 * GET /api/notes/<id>/likes/?anchor_kind=&block_id=（① 型）
 * ★★ 初始态的服务端来源（`B211`③）—— B站刷新后恢复红拇指就靠这个
 *
 * ⚠ 未登录也能调（返回 `liked:false` + 计数）—— 计数对所有人可见 ✅
 */
export function useLikeStatus(
  noteId: string | null | undefined,
  anchor: AnchorKind = 'chapter',
  blockId?: number | null,
) {
  const params = new URLSearchParams({ anchor_kind: anchor })
  if (anchor === 'paragraph' && blockId != null) params.set('block_id', String(blockId))
  return useQuery({
    queryKey: ['like-status', noteId, anchor, blockId ?? null],
    enabled: !!noteId,
    queryFn: async (): Promise<LikeStatus> =>
      unwrap(await apiGet<LikeStatus>(`/api/notes/${noteId!}/likes/?${params.toString()}`, 'data')),
  })
}

/**
 * POST/DELETE /api/notes/<id>/likes/（① 型）—— 裸 mutation，不做防抖
 *
 * ⚠★★ **段赞必须带 `block_id`，而且两个方法放的位置不同**（后端如此实现）：
 *   · · ★ `POST` 读**请求体**：`{anchor_kind, block_id}`
 *   · · ★ `DELETE` 读**查询参数**：`?anchor_kind=&block_id=`
 *   · · ⛔ 之前两边都只传了 `anchor_kind` ⇒ 段赞被当成章赞
 *     （* 表现为：点段赞图标变了、计数不动，取消也是 `removed:false`）⚠
 */
export function useLikeMutation(
  noteId?: string | null,
  anchor: AnchorKind = 'chapter',
  blockId?: number | null,
) {
  return useMutation({
    mutationFn: async (liked: boolean): Promise<LikeResult> => {
      const path = `/api/notes/${noteId!}/likes/`
      const params = new URLSearchParams({ anchor_kind: anchor })
      if (anchor === 'paragraph' && blockId != null) params.set('block_id', String(blockId))

      return unwrap(
        liked
          ? // POST：请求体
            await apiPost<LikeResult>(
              `${path}?${params.toString()}`,
              {
                anchor_kind: anchor,
                ...(anchor === 'paragraph' && blockId != null ? { block_id: blockId } : {}),
              },
              'data',
            )
          : // DELETE：查询参数（⛔ body 后端不读）
            await apiDelete<LikeResult>(`${path}?${params.toString()}`, undefined, 'data'),
      )
    },
  })
}

export interface LikeToggleState {
  liked: boolean
  like_count: number
}

/**
 * ★★ **点赞开关钩子**（`D83` + `B211`）—— 所有点赞按钮用它
 *
 * @param noteId 笔记 id
 * @param anchor 章赞 / 段赞（`chapter` / `paragraph`）
 * @param initial 初始态 —— ★★ **来自 `useLikeStatus`**（`B211`③），⛔ 不再默认 false
 *
 * ⚠ 实现要点：`desired`（图标态，本地）与 `count`（合并数，只信回包）**分离**；
 *   定时器只保留**一个**（后到覆盖前到）⇒ 连续点击永远只发一次最终态 ✅
 */
export function useLikeToggle(
  noteId: string | null | undefined,
  anchor: AnchorKind = 'chapter',
  initial: LikeToggleState = { liked: false, like_count: 0 },
  /** ★★ 段赞必传（* 否则后端当成章赞）⚠ */
  blockId?: number | null,
) {
  const [state, setState] = useState<LikeToggleState>(initial)
  const desired = useRef(state.liked)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sending = useRef(false)

  /**
   * ★★ **初始态查询回来后同步**（`F3` 补的洞）⚠
   *
   * ⚠ 为什么需要：`useState(initial)` 的初值**只在首渲染读一次** ——
   *   · ★ 而 `GET .../likes/` 是**异步**的（`useLikeStatus`）⇒ ★ 首渲染时它还没回来 ⚠
   *   · · ★ 后果：* 按钮先显示「未赞 / 0」，* 查询回来后**不会自己更正** ⚠
   *   · ★★ 这正是 `B211`③ 要修的「刷新后想不起自己赞没赞过」——
   *     * 数据层有了初始态端点，* 前端必须真的用它 ✅
   *
   * ⚠★ 只认**值变化**（`liked:count` 拼成 key）——
   *   · · ★ 调用方每次渲染都会传新的对象字面量 ⇒* ⛔ 不能直接依赖 `initial` 引用 ⚠
   *   · · ★ 值没变就不重置（* 否则会把用户的乐观翻牌**拍回去**）⚠
   */
  const initKey = `${initial.liked}:${initial.like_count}`
  useEffect(() => {
    setState({ liked: initial.liked, like_count: initial.like_count })
    desired.current = initial.liked
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initKey])

  const mutation = useLikeMutation(noteId, anchor, blockId)

  /** ★ 把「最终态」发出去（⛔ 不判断要不要发——`D83④(b)`：照发，靠服务端幂等） */
  const flush = useCallback(() => {
    if (timer.current != null) {
      clearTimeout(timer.current)
      timer.current = null
    }
    if (sending.current) return
    sending.current = true
    mutation.mutate(desired.current, {
      onSettled: () => {
        sending.current = false
      },
    })
  }, [mutation])

  /** ★★ 服务端回包 ⇒* 以它为准校正（`liked` + `like_count` 都来自服务端）✅ */
  useEffect(() => {
    const r = mutation.data
    if (!r) return
    setState({ liked: r.liked, like_count: r.like_count })
  }, [mutation.data])

  /**
   * ★★ 点一下 = 翻图标（* 本地状态，* 立即）✅
   *
   * ⚠★★ **计数不动**（`B211`⑥）——* 合并数不是 UI 能本地 ±1 的数字；
   *   * 它 1.2s 后由回包带来（* `B212`①：* 这段滞后是允许的）⚠
   */
  const toggle = useCallback(() => {
    desired.current = !desired.current
    setState((s) => ({ liked: desired.current, like_count: s.like_count }))
    if (timer.current != null) clearTimeout(timer.current)
    timer.current = setTimeout(flush, DEBOUNCE_MS)
  }, [flush])

  /** ★★ `D83④(a)`：待发状态在页面隐藏 / 卸载时必须发出 ⚠ */
  useEffect(() => {
    const onHide = () => {
      if (document.hidden && timer.current != null) flush()
    }
    document.addEventListener('visibilitychange', onHide)
    window.addEventListener('beforeunload', flush)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      window.removeEventListener('beforeunload', flush)
      // ⚠ 卸载时还有待发的 ⇒ 立刻发（fire-and-forget；token 在闭包里带着）
      if (timer.current != null) flush()
    }
  }, [flush])

  return {
    liked: state.liked,
    like_count: state.like_count,
    /** ★ 有待发请求（防抖窗口里）—— UI 可显示「稍后保存」 */
    pending: timer.current != null,
    toggle,
  }
}
