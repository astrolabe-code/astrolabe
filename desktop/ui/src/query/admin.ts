import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import type { AdminSettingsData } from '../api/types'

/**
 * ★ 参数中心数据层（`B172` · ★ 管理页用）
 *
 * ## ★★ 权限：**这里只要求 `staff`**（后端 `@staff_only`）
 *
 * ⚠★★ 但**能不能改某一个参数**是**另一回事**（`U2.4` 两级）：
 * ★ 门禁类（`gated=True`）**只有 `superuser` 能改** ⚠
 *
 * ⇒ ★★ 那个判定**在参数层**（`appsettings.set_value()` 自己抛 `PermissionError`），
 *   ★ 视图只负责把它翻成 `403` ✅
 * ⇒ ★ 而前端**不自己猜** —— ★ 直接用后端给的 `editable` 字段置灰按钮 ✅
 *
 * ## ★ 端点
 * | 方法 | 路径 | 说明 |
 * |---|---|---|
 * | `GET` | `/api/admin/settings/` | ★ 全部参数 + `can_edit_gated` |
 * | `POST` | `/api/admin/settings/` | ★ 改一批（★ 后端**全成或全不成**）|
 */

/** ★ 参数键 → 值（★ `bool` / `int` 都在内 —— ⚠ 后端**只认 JSON 原生类型**，❌ 不收 `"true"` 字符串） */
export type SettingsPatch = Record<string, boolean | number>

/**
 * ★ 读全部参数 —— ⚠★ **`enabled` 必须由调用方给**（★ 通常传 `me.is_staff`）。
 *
 * ★ 非管理员调它**必然 403**，★ 而那次失败**没有意义**（★ 只是白打一发）⚠
 */
export function useAdminSettings(enabled: boolean) {
  return useQuery({
    queryKey: ['admin-settings'],
    enabled,
    queryFn: async (): Promise<AdminSettingsData> =>
      unwrap(await apiGet<AdminSettingsData>('/api/admin/settings/', 'data')),
  })
}

/**
 * ★ 改一批参数 —— ★★ **或全成、或全不成**（★ 后端用事务包住了）。
 *
 * ⚠★ 所以这里**不需要**做"部分失败后重新拉取"之类的补救 —— ★ 失败就是**一个都没改** ✅
 */
export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (values: SettingsPatch): Promise<AdminSettingsData> =>
      // ⚠ 包成 `{values:{…}}` —— ★ 那是后端的入参形态（★ 见 `views/admin.py::_update`）
      unwrap(await apiPost<AdminSettingsData>('/api/admin/settings/', { values }, 'data')),
    onSuccess: (d) => {
      // ★ 后端**回传了最新全量** ⇒ ★ 直接写进缓存，❌ 不用再打一枪（★ 也避免"刚改完看到旧值"抖动）
      qc.setQueryData(['admin-settings'], d)
    },
  })
}
