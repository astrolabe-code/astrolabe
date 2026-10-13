import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import { resolveRef } from '../lib/resolveRef'
import type {
  CreatedProject,
  ProgressData,
  ProjectListData,
  ProjectSummary,
  UpdatedProject,
} from '../api/types'

/**
 * ★★ 「拉取代码」的返回（★ `B179` 起有【三种结局】）⚠
 *
 * ⚠★ `job_id` 为 `null` **不代表失败** —— ★ `reused: true` 时它是 `null`，
 *   ★★ 而那是**成功**（★ 这份代码已经有人解析过了，★ 直接就能看）✅
 */
export interface StartedFetch {
  project_ref: string
  job_id: number | null
  job_state: string
  /** ★★ `B179`：★ 是否复用了现成基图（★ 前端据此给不同文案）*/
  reused?: boolean
  /** ★ 复用了哪一版（★ 前端可显示"对应 commit ea42736…"）*/
  sha?: string
  message?: string
  steps?: Record<string, unknown>
}

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
  /**
   * ★★ `B182`：**浏览器里已经算好的 commit sha** ⚠
   *
   * ★★ 所有者原话：「**这个过程应该发生在前端，不是用我服务器的IP地址查询的，
   *    只有拉源码，才是我服务器做的吧？**」
   *
   * · ★ 带上它 ⇒ ★★ 服务端【一次 GitHub API 都不发】✅
   *   （★ 未认证配额每 IP 每小时 60 次，★ 服务端扛 ⇒ 所有人一起被挡）⚠
   * · ★ 不带 ⇒ ★ 服务端自己解析（★ 兜底）✅
   */
  sha?: string
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
 * ★★★ **发起「拉取代码」**（★ `B176` ① 之后：**一步到底，不再跳转**）。
 *
 * ## ⚠★★ `B182`：**先在浏览器里把分支解析成 sha**
 *
 * ★★ 所有者原话（逐字）：
 *
 * > 「**不对呀，这个过程应该发生在前端，不是用我服务器的IP地址查询的，
 * > 只有拉源码，才是我服务器做的吧？**」
 *
 * ```
 * ★ 未认证 GitHub API 每 IP 每小时 60 次，★ 解析 sha 要 2 次
 * ★★ 服务端做 ⇒ 每小时约 30 次拉取撞限，★ 所有用户一起被挡 ⚠
 * ★★ 前端做   ⇒ 每个用户花自己的配额 ✅
 * ```
 *
 * ⚠★ **解析失败不影响功能** —— ★ 那时**不传 sha**，★ 服务端会自己解析（兜底）✅
 *   （★ 所以这里是"省配额"的优化，★ ❌ 不是功能前提）⚠
 *
 * ## ★★ 返回值有三种结局（★ `B179` 起）
 *
 * | 结局 | 长什么样 | 前端该做什么 |
 * |---|---|---|
 * | ★ 投出去了 | 有 `job_id` | ★ 照旧轮询进度 ✅ |
 * | ★★ **复用了** | `job_id: null` + `reused: true` | ★★ **这也是成功** ⇒ 直接就能看图 ⚠ |
 * | ★ 失败 | 4xx + `error.code` | ★ 如实展示原因 ✅ |
 *
 * ⚠★ `B176` ① 之前这里是**两步**（拿授权 URL ⇒ 整页跳走 ⇒ 回调里才真正拉取）——
 *   ★★ 那套已经**整个退役**了（★ 归属校验随 `B176` ① 一起删掉）⚠
 */
export function useStartFetch(projectRef: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: {
      provider: string
      repo_full: string
      ref?: string
    }): Promise<StartedFetch> => {
      // ---- ⓵ ★★ `B182`：浏览器里解析 sha（★ 失败就跳过，不阻断）----
      let sha = ''
      try {
        const v = await resolveRef(body.provider, body.repo_full, body.ref || '')
        if (v.ok) sha = v.sha
      } catch {
        // ⚠ 网络炸了也**照样提交** —— ★ 服务端会自己解析 ⚠
      }

      // ---- ⓶ 提交（★ 带上 sha ⇒ 服务端一次 API 都不发）----
      return unwrap(
        await apiPost<StartedFetch>(
          `/api/projects/${encodeURIComponent(projectRef)}/fetch/`,
          { sha },
          'data',
        ),
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', projectRef] })
      qc.invalidateQueries({ queryKey: ['progress', projectRef] })
    },
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
