import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import type {
  CreatedProject,
  ProgressData,
  ProjectListData,
  ProjectSummary,
  UpdatedProject,
} from '../api/types'

/**
 * ★ 项目数据层（`B164` · 前端第二阶段 2a）
 *
 * ## ⚠★ 与旧项目（`/home/webapp/demo/frontend/src/query/projects.ts`）的差别
 *
 * ★★ 对账后**逐条裁定**（见 `docs/backend-decisions.md` 的 `B164`）：
 *
 * | 旧钩子 | 处置 | 原因 |
 * |---|---|---|
 * | `useProjects` · `useCreateProject` · `useDeleteProject` · `useProgress` | ✅ 保留（★ 形态一致） | — |
 * | `useFindProject` | ✏️ **改用它走 detail 端点** | ★ 新后端**有** `GET /api/projects/<ref>/`（①型）⇒ 不必再"拉全列表前端 find" |
 * | `useUpdateProject` | ✏️ **`PUT` → `PATCH`** | ⚠ 新后端只接受 PATCH（PUT 会 **405**） |
 * | `useReparse` | ✏️ **改名 `useTriggerParse` 且语义不同** | ⚠★ 见下 |
 * | `useUploadZip` | ❌ **删除** | ⚠ 新设计**源码只能服务端拉取**（`B109`）—— 没有 zip 上传这条路 |
 * | `useCopyProject` | ❌ **删除** | ❌ 新后端没有 `copy/` |
 *
 * ## ⚠★★ 一个必须理解的语义变化：`useTriggerParse` **不是「重新解析」**
 *
 * ★ `B155`（图不可变）之后，`POST …/parse/` 的语义是「**补投**」：
 *
 * | 项目状态 | 行为 |
 * |---|---|
 * | ★ 未定版（图还没生成） | ✅ 允许投递（★ 正当用途：★ **作业失败/丢了，重投一次**） |
 * | ★★ 已定版 | ★★ **409 `graph_immutable`** —— ⚠ **不会重新解析** |
 *
 * ⇒ ★★ 调用方**必须**处理这个 409（★ 见 `useTriggerParse` 的 `onError`）——
 * ★ 它**不是错误**，★ 而是一个**明确的业务答复**：⚠ 要另一个版本请**新建项目**。
 */

/** ★ 可见项目列表（公开 + 自己的；游客只见公开） */
export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: async (): Promise<ProjectSummary[]> => {
      const data = unwrap(await apiGet<ProjectListData>('/api/projects/', 'spread'))
      return data.projects || []
    },
  })
}

/**
 * ★ 单个项目 —— **走详情端点**（`B164` 改写）
 *
 * ⚠★ 旧做法是「拉全列表再前端 `find`」（★ 因为旧站没有 detail 端点）——
 * 那有两个毛病：★ 白拉一页数据；★ 若项目不在列表里（★ 分页/权限）就**找不到**。
 * ⇒ ★★ 新后端有 `GET /api/projects/<project_ref>/`（**①型**）⇒ ★ 直接问它 ✅
 */
export function useProject(projectRef?: string | null) {
  return useQuery({
    queryKey: ['project', projectRef],
    enabled: !!projectRef,
    queryFn: async (): Promise<ProjectSummary> =>
      unwrap(await apiGet<ProjectSummary>(`/api/projects/${encodeURIComponent(projectRef!)}/`, 'data')),
  })
}

export interface CreateProjectBody {
  name: string
  /** ★★ 必填 —— B109：源码只能服务端拉取 */
  repo_url: string
  /** ★★ 必填 —— `github` / `gitee` */
  provider: string
  /** ★ 可选，缺省 = HEAD */
  commit?: string
  desc?: string
  is_public?: boolean
}

/**
 * ★ 新建项目
 *
 * ⚠★★ 入参与旧项目**完全不同** —— ★ `repo_url` 与 `provider` **都是必填**。
 * ★ 旧前端的 `category` / `icon` **在新后端不存在** ⇒ ★ 表单已相应重做。
 */
export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: CreateProjectBody): Promise<CreatedProject> =>
      unwrap(await apiPost<CreatedProject>('/api/projects/', body, 'data')),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

/** ★ 编辑项目资料 / 切换公开（⚠ **PATCH**，★ 支持部分字段） */
export function useUpdateProject(projectRef: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (
      body: Partial<Pick<UpdatedProject, 'name' | 'desc' | 'is_public'>>,
    ): Promise<UpdatedProject> =>
      unwrap(
        await apiPatch<UpdatedProject>(
          `/api/projects/${encodeURIComponent(projectRef)}/`,
          body,
          'data',
        ),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['project', projectRef] })
    },
  })
}

/** ★ 删除项目（仅 owner；★ 后端会**先释放存储空间**再删数据 —— `B152`） */
export function useDeleteProject(projectRef: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (): Promise<{ project_ref: string; name: string }> =>
      unwrap(
        await apiDelete<{ project_ref: string; name: string }>(
          `/api/projects/${encodeURIComponent(projectRef)}/`,
          undefined,
          'data',
        ),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

/**
 * ★★ 触发解析 —— **「补投」语义**（⚠★ 不是"重新解析"，见文件头说明）
 *
 * ★ 已定版的项目会拿到 **409 `graph_immutable`** —— ★ 调用方应当把它
 * **展示成引导语**（★ 后端已经在错误消息里写清了出路），★ 而不是当成故障。
 */
export function useTriggerParse(projectRef: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      unwrap(await apiPost<{ job_id: number; state: string; created: boolean }>(
        `/api/projects/${encodeURIComponent(projectRef)}/parse/`,
        {},
        'data',
      )),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['progress', projectRef] })
      qc.invalidateQueries({ queryKey: ['jobs', projectRef] })
      qc.invalidateQueries({ queryKey: ['project', projectRef] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
    // ★ 409 不改任何缓存 —— 图没变，重新拉也是白拉
  })
}

/**
 * ★ 解析进度 —— ★ 轮询；★ 进入终态自动停（★ 页面隐藏时也停，⚠ 不白耗电）
 *
 * ⚠ 终态集合含 `none`（★ 从未投递过解析）—— ★ 旧项目只判 done/error，
 * ★ 那会让"没有作业的项目"**永远轮询下去**。
 */
export function useProgress(
  projectRef?: string | null,
  opts: { enabled?: boolean; pollMs?: number } = {},
) {
  const { enabled = true, pollMs = 2000 } = opts
  return useQuery({
    queryKey: ['progress', projectRef],
    enabled: !!projectRef && enabled,
    queryFn: async (): Promise<ProgressData> =>
      unwrap(await apiGet<ProgressData>(
        `/api/projects/${encodeURIComponent(projectRef!)}/progress/`,
        'data',
      )),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'done' || status === 'error' || status === 'none') return false
      return document.hidden ? false : pollMs
    },
  })
}
