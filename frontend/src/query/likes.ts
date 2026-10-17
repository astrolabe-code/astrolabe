import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { apiDelete, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import type { AnchorKind, LikeResult } from '../api/types'

/**
 * ★ 点赞数据层（`B203⑤` / `B205` / `D83` · 契约 §22.4）
 *
 * ## ★★★ 本模块的两个出口
 *
 * | 出口 | 给谁用 | 说明 |
 * |---|---|---|
 * | `useLikeMutation` | 特殊场景（一次性脚本/管理操作） | 裸 mutation，不做防抖 |
 * | ★★ `useLikeToggle` | ★★ **所有点赞按钮**（章赞/段赞） | **开关语义 + 1–2 秒防抖 + 乐观更新**全在这里（`D83`） |
 *
 * ## ⚠★ `useLikeToggle` 的五条口径（逐条对应 `D83`）
 *
 * ```
 * ① ★★ 开关语义：* 点一下赞、* 再点一下取消；* UI **立即变**（* 乐观）✅
 * ② ★★ 防抖 1–2 秒：* 最后一次点击后**等 1200ms** 才发请求；* 连续点击**只发一次**
 *      （* 带最终态：* 赞 ⇒ POST，* 取消 ⇒ DELETE）✅
 * ③ ★★ 以服务端回包为准：* 回包带 `liked` + `like_count` ⇒* 用它校正 ✅
 * ④ ★★ 待发状态在**页面隐藏 / 卸载**时必须发出（* `visibilitychange` /
 *      `beforeunload`）——* 否则「点了就走」状态丢 ⚠
 * ⑤ ★★ 连点回到原态：* 请求**照发**（* `D83④(b)`），* 服务端幂等返回
 *      （* `already:true` / `removed:false`）⇒* 计数不动 ✅
 * ```
 *
 * ⚠★ **初始态没有服务端来源**（2026-10-17 联调摸底发现，已向所有者报告）：
 *   `note` 载荷里**没有**「我赞过没有」字段，也没有查询端点 ⇒
 *   调用方传 `initialLiked`（默认 `false`）；⚠ 刷新页面后未赞过的会显示为未赞，
 *   用户点一下即被服务端校正（`already:true`）。
 */

/** ⚠ 防抖时长（`D83`：1–2 秒，取中间值） */
const DEBOUNCE_MS = 1200

/** POST/DELETE /api/notes/<id>/likes/（① 型）—— 裸 mutation，不做防抖 */
export function useLikeMutation(noteId?: number | null, anchor: AnchorKind = 'chapter') {
  return useMutation({
    mutationFn: async (liked: boolean): Promise<LikeResult> => {
      const path = `/api/notes/${noteId!}/likes/`
      return unwrap(
        liked
          ? await apiPost<LikeResult>(path, { anchor_kind: anchor }, 'data')
          : await apiDelete<LikeResult>(path, { anchor_kind: anchor }, 'data'),
      )
    },
  })
}

export interface LikeToggleState {
  liked: boolean
  like_count: number
}

/**
 * ★★ **点赞开关钩子**（`D83` 的落点）—— 所有点赞按钮用它
 *
 * @param noteId 笔记 id
 * @param anchor 章赞 / 段赞（`chapter` / `paragraph`）
 * @param initial 初始态（来自笔记载荷的 `like_count`；`liked` 见模块文档的⚠）
 *
 * ⚠ 实现要点：`desired`（UI 态）与 `sent`（已确认态）分离；
 *   定时器只保留**一个**（后到覆盖前到）⇒ 连续点击永远只发一次最终态 ✅
 */
export function useLikeToggle(
  noteId: number | null | undefined,
  anchor: AnchorKind = 'chapter',
  initial: LikeToggleState = { liked: false, like_count: 0 },
) {
  const [state, setState] = useState<LikeToggleState>(initial)
  const desired = useRef(state.liked)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sending = useRef(false)

  const mutation = useLikeMutation(noteId, anchor)

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

  /** ★ 服务端回包 ⇒ 以它为准校正（`liked` + `like_count`） */
  useEffect(() => {
    const r = mutation.data
    if (!r) return
    setState({ liked: r.liked, like_count: r.like_count })
  }, [mutation.data])

  /** ★★ 点一下 = 翻转 + 重排防抖；连续点N次 = 最后一次排的那一次 ✅ */
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
