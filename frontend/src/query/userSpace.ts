import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPatch } from '../api/client'
import { unwrap } from '../api/errors'
import type { MyProfile, SpaceItem, SpacePage, UserSpaceData } from '../api/types'

/**
 * ★★ **用户空间数据层**（2026-10-24）⚠
 *
 * ```\n * 资料 + 统计   GET /api/u/<username>/\n * 笔记          GET /api/u/<username>/notes/?sort=new|hot\n * 项目          GET /api/u/<username>/projects/\n * 动态          GET /api/u/<username>/activity/\n * 本人资料      GET / PATCH /api/me/profile/\n * ```
 *
 * ⚠ 列表统一 **keyset 分页**（`next_cursor`），⛔ 不用 offset ⚠
 */

export function useUserSpace(username?: string | null) {
  return useQuery({
    queryKey: ['user-space', username],
    enabled: Boolean(username),
    queryFn: async (): Promise<UserSpaceData> =>
      unwrap(
        await apiGet<UserSpaceData>(`/api/u/${encodeURIComponent(username!)}/`, 'spread'),
      ),
  })
}

/** ★ 通用游标列表（* 三个 Tab 共用）⚠ */
function useSpaceFeed(
  key: (string | null | undefined)[],
  url: (cursor: string) => string,
  enabled: boolean,
) {
  return useInfiniteQuery({
    queryKey: key,
    enabled,
    initialPageParam: '',
    queryFn: async ({ pageParam }): Promise<SpacePage<SpaceItem>> =>
      unwrap(await apiGet<SpacePage<SpaceItem>>(url(pageParam), 'spread')),
    getNextPageParam: (last) => last.next_cursor || undefined,
  })
}

export function useUserNotes(
  username?: string | null,
  sort: 'new' | 'hot' = 'new',
  kind: string = '',
  enabled = true,
) {
  const k = kind && kind !== 'all' ? `&kind=${encodeURIComponent(kind)}` : ''
  return useSpaceFeed(
    ['user-notes', username, sort, kind],
    (cursor) =>
      `/api/u/${encodeURIComponent(username!)}/notes/?sort=${sort}${k}&cursor=${encodeURIComponent(cursor)}`,
    Boolean(username) && enabled,
  )
}

export function useUserProjects(username?: string | null, enabled = true) {
  return useSpaceFeed(
    ['user-projects', username],
    (cursor) =>
      `/api/u/${encodeURIComponent(username!)}/projects/?cursor=${encodeURIComponent(cursor)}`,
    Boolean(username) && enabled,
  )
}

export function useUserActivity(username?: string | null, enabled = true) {
  return useSpaceFeed(
    ['user-activity', username],
    (cursor) =>
      `/api/u/${encodeURIComponent(username!)}/activity/?cursor=${encodeURIComponent(cursor)}`,
    Boolean(username) && enabled,
  )
}

/** ★ 本人资料 ⚠ */
export function useMyProfile() {
  return useQuery({
    queryKey: ['my-profile'],
    queryFn: async (): Promise<MyProfile> =>
      unwrap(await apiGet<MyProfile>('/api/me/profile/', 'spread')),
  })
}

/** ★ 改昵称 / 签名（* 成功后刷空间页与资料）⚠ */
export function useUpdateMyProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { display_name?: string; bio?: string }): Promise<MyProfile> =>
      unwrap(await apiPatch<MyProfile>('/api/me/profile/', body, 'spread')),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['my-profile'] })
      void qc.invalidateQueries({ queryKey: ['user-space'] })
    },
  })
}
