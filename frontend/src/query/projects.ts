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
 * ★★★ `B169`：**「拉取代码」**（★ 端点原叫 `parse/` —— ⚠★ 而它当时带着一个 **「补投」** 语义，
 *   ★★ **那是 AI 自己加的，所有者从没要过**）：
 *
 * | 项目状态 | 行为 |
 * |---|---|
 * | ★ **未定版**（含**拉取失败 / 解析失败**） | ✅ **允许再发起**（★ 所有者裁定：失败可重试） |
 * | ★★ **已定版**（★ 代码已拉下**且**解析完成） | ★★ **409 `graph_immutable`** + 引导语 |
 *
 * ⚠★ **注意：这里【没有】"投递"这个动作** ——
 * ★ 前端只拿到 `authorize_url`，★ 然后**整页跳转**到 GitHub / Gitee；
 * ★★ 真正的「**归属校验 + 投递（拉取 + 解析）**」发生在 **OAuth 回调里**
 * （★ 因为**只有那一刻能拿到 `access_token`**，⚠ 而本平台**不保存它** —— `B148`）⚠
 *
 * ⇒ ★★ 所以调用方拿到 409 时**别当故障**：★ 后端消息里已经写清了出路
 *   （★ **要另一个版本 ⇒ 新建项目**；★ **想重来 ⇒ 删了重建**）✅
 */

/**
 * ★ 可见项目列表（公开 + 自己的；游客只见公开）
 *
 * ## ★★ `B173`：加了 `staleTime` 参数
 *
 * ⚠★ 为什么需要它：★ `Home`（首页）原本**自带** `staleTime: 60_000`，
 * ★★ 而直接换成 `useProjects()` 会**默默把它丢掉**（★ `useQuery` 默认 `0`）
 *   ⇒ ★ 首页每次挂载都重拉一遍全量列表 ⚠
 * ⇒ ★★ 所以把那个值**显式传进来** —— ★ 而不是悄悄改掉首页的节奏 ✅
 *
 * ## ⚠★ `mine` 必须进 `queryKey`
 * ★ 否则「工作区（只看我的）」会命中「首页（公开 + 我的）」的缓存 ⚠
 * （★ 这两份数据**本来就不同** —— ★ 见 `B172` 的 `?mine=1`）
 */
export function useProjects(opts: { mine?: boolean; staleTime?: number } = {}) {
  const mine = !!opts.mine
  return useQuery({
    // ⚠★ `mine` 必须进 key —— ★ 否则"工作区（只看我的）"会命中"首页（公开+我的）"的缓存 ⚠
    queryKey: ['projects', { mine }],
    queryFn: async (): Promise<ProjectSummary[]> => {
      const data = unwrap(
        await apiGet<ProjectListData>(`/api/projects/${mine ? '?mine=1' : ''}`, 'spread'),
      )
      return data.projects || []
    },
    // ⚠★ `staleTime` **刻意不进 `queryKey`** ——
    //   ★ 它不是"取哪一份数据"（那是 `mine`），★ 而是"多久算过期"（缓存策略）✅
    //   ⇒ ★ 把它塞进 key 反而会让同一个查询出现两份缓存 ⚠
    staleTime: opts.staleTime ?? 0,
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

/** ★ SPA 内部路径 ⇒ **浏览器可打开的路径**（★ 带上 `base`，即 `/app`） */
function spaPath(internal: string): string {
  const base = (import.meta.env.BASE_URL || '/app/').replace(/\/$/, '')
  return `${base}${internal.startsWith('/') ? internal : `/${internal}`}`
}

/**
 * ★★★ **发起「拉取代码」授权**（`B169`）—— ⚠★ **它不投递作业，只拿回一个授权 URL**。
 *
 * ## ★★ 为什么必须是两步（★ 这不是设计缺陷，是"不保存凭据"必然的代价）
 * ⚠★ 本平台**不保存 `access_token`**（`B148`）⇒ ★ 无法在"投递"那一刻替用户去问
 * GitHub「这个库是不是他的」⇒ ★★ **只能让用户当场授权一次** ✅
 * → ★ 与 `useCreateProject` 那条发布链**完全同构**（★ 真正的动作都在 OAuth 回调里）。
 *
 * ## ★ 调用方要做什么
 * ```ts
 * const r = await startFetch.mutateAsync({})
 * window.location.href = r.authorize_url      // ★ 跨域授权页 ⇒ 只能整页跳转
 * ```
 *
 * ⚠★ **`next_url` 必须带 `/app` 前缀**（★ 由 `spaPath` 负责）——
 * ★ 因为后端会把它**原样用作 302 的 Location**，★ 那是**浏览器跳转**、不经过 router 的 basename ⚠
 *
 * ## ★ 409 怎么办
 * ★ 已定版的项目会拿到 **409 `graph_immutable`** —— ★ 前端**不该给按钮**（★ 见 `ProjectCard`），
 * ★ 但**万一**拿到（★ 比如时间差），★ 把它**展示成引导语**即可，❌ 不是故障 ✅
 */
export function useStartFetch(projectRef: string, nextInternal = '/workspace') {
  return useMutation({
    mutationFn: async (): Promise<{ authorize_url: string; state: string; repo: string }> =>
      unwrap(
        await apiPost<{ authorize_url: string; state: string; repo: string }>(
          `/api/projects/${encodeURIComponent(projectRef)}/fetch/`,
          { next_url: spaPath(nextInternal) },
          'data',
        ),
      ),
    // ★ 刻意**不 invalidate 任何缓存**：★ 此刻还什么都没变
    //   （★ 真正开始拉取要等用户从 GitHub 授权回来 —— 那时页面已整页重载）✅
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
