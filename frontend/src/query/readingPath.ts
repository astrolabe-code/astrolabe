import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client'
import { unwrap } from '../api/errors'
import type { ReadingPathData } from '../api/types'

/**
 * ★ 学习路径数据层（`B234`）
 *
 * ## ★★ 四个端点（* 配合「学到哪里标到哪里」）
 *
 * | 钩子 | 动作 |
 * |---|---|
 * | `useReadingPath` | GET（* 按序 + stale）|
 * | `useAppendToPath` | POST `{vid}`（* 追加，* 幂等）|
 * | `useRemoveFromPath` | DELETE `{vid}` |
 * | `useReplacePath` | PUT `{items:[…]}`（* 整体重排 / 清理失效项）|
 *
 * ⚠★ `D107`：* `stale` 里的 vid 是「已不在图里」的 ——* 前端据此提示用户，
 *   * ⛔ 不自动清理（* 所有者：* 等用户自己处理）✅
 */

/** GET /api/projects/<ref>/reading-path/ */
export function useReadingPath(projectRef?: string | null) {
  return useQuery({
    queryKey: ['reading-path', projectRef],
    enabled: !!projectRef,
    queryFn: async (): Promise<ReadingPathData> =>
      unwrap(
        await apiGet<ReadingPathData>(
          `/api/projects/${encodeURIComponent(projectRef!)}/reading-path/`,
          'data',
        ),
      ),
  })
}

/** POST {vid} —— 追加到队尾（已存在 ⇒ 幂等不动） */
export function useAppendToPath(projectRef?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (vid: number): Promise<ReadingPathData> =>
      unwrap(
        await apiPost<ReadingPathData>(
          `/api/projects/${encodeURIComponent(projectRef!)}/reading-path/`,
          { vid },
          'data',
        ),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['reading-path', projectRef] })
    },
  })
}

/** DELETE {vid} */
export function useRemoveFromPath(projectRef?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (vid: number): Promise<ReadingPathData> =>
      unwrap(
        await apiDelete<ReadingPathData>(
          `/api/projects/${encodeURIComponent(projectRef!)}/reading-path/`,
          { vid },
          'data',
        ),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['reading-path', projectRef] })
    },
  })
}

/** PUT {items:[vid…]} —— 整体重排 / 清理失效项 */
export function useReplacePath(projectRef?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (items: number[]): Promise<ReadingPathData> =>
      unwrap(
        await apiPut<ReadingPathData>(
          `/api/projects/${encodeURIComponent(projectRef!)}/reading-path/`,
          { items },
          'data',
        ),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['reading-path', projectRef] })
    },
  })
}
