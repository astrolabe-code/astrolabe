import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPatch } from '../api/client'
import { unwrap } from '../api/errors'
import type { SettingsData, SettingsPatchResult } from '../api/types'

/**
 * ★ 设置数据层（`B190` / `B203`② · 契约 §22.1）
 *
 * ## ⚠★ 三条必须理解的约定
 *
 * | # | 约定 | 前端后果 |
 * |---|---|---|
 * | ① | ★★ PATCH 请求体是**扁平**的 `{键:值}` | ❌ **不是** `{settings:{…}}`（包一层全都 400） |
 * | ② | ★★ 响应带 `specs`（含 `source`） | 前端渲染「这一项为什么是这个值」(`default/global/user/project`) |
 * | ③ | ★★ `gated=true` 只有管理员能改 | 非管理员改 ⇒ 该键进 `rejected` ⇒ **整件 400 `bad_setting`**（❌ 不是部分成功）⇒ 要整份重显 |
 *
 * ⚠ 三级继承：用户档（`/api/me/settings/`）与项目档（`/api/projects/<ref>/settings/`）
 *   **同形**，区别只在 `specs` 里出现哪些键（项目档的键不出现在用户档，反之亦然）。
 */

/** GET /api/me/settings/（② 型） */
export function useUserSettings() {
  return useQuery({
    queryKey: ['settings', 'user'],
    queryFn: async (): Promise<SettingsData> =>
      unwrap(await apiGet<SettingsData>('/api/me/settings/', 'spread')),
  })
}

/**
 * PATCH /api/me/settings/（② 型）
 *
 * ⚠ body 是**扁平**的 `{键:值}`（⛔ 不是 `{settings:{…}}`）；
 * ⚠ 只要有一个键被拒 ⇒ 整件 400 `bad_setting`（带 `applied`/`rejected`），
 *   调用方应整份重显（⛔ 不做部分应用）✅
 */
export function usePatchUserSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (patch: Record<string, unknown>): Promise<SettingsPatchResult> =>
      unwrap(await apiPatch<SettingsPatchResult>('/api/me/settings/', patch, 'spread')),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['settings', 'user'] })
    },
  })
}

/** GET /api/projects/<ref>/settings/（② 型） */
export function useProjectSettings(projectRef?: string | null) {
  return useQuery({
    queryKey: ['settings', 'project', projectRef],
    enabled: !!projectRef,
    queryFn: async (): Promise<SettingsData> =>
      unwrap(
        await apiGet<SettingsData>(
          `/api/projects/${encodeURIComponent(projectRef!)}/settings/`,
          'spread',
        ),
      ),
  })
}

/** PATCH /api/projects/<ref>/settings/（② 型）——需要 can_edit（owner ∨ 协作者） */
export function usePatchProjectSettings(projectRef?: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (patch: Record<string, unknown>): Promise<SettingsPatchResult> =>
      unwrap(
        await apiPatch<SettingsPatchResult>(
          `/api/projects/${encodeURIComponent(projectRef!)}/settings/`,
          patch,
          'spread',
        ),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['settings', 'project', projectRef] })
    },
  })
}
