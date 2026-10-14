import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import { resolveRef } from '../lib/resolveRef'
import type {
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
/** ★★ 作业的【终态】—— ★ 到了这些就**不该再轮询** ⚠ */
export const TERMINAL_JOB_STATES = ['done', 'failed', 'canceled', 'none'] as const

/**
 * ★ 作业**还在跑**吗（★ 只有这两种状态值得轮询）
 *
 * ⚠★★ 别再写 `'error'` —— ★ 作业状态里**根本没有那个值** ⚠
 *   ★ 真实取值见 `jobs/models.py::Job.STATE_CHOICES`：
 *   `queued` · `running` · `done` · ★★ **`failed`** · `canceled`
 *   ⇒ ★ 判错的后果：★ **失败的项目会永远轮询下去**（★ 白耗电、白打接口）⚠
 *   ★ 另有 `'none'` —— ★ 那是**列表端点**在"没有作业"时给的伪状态 ✅
 */
export function isJobActive(status?: string | null): boolean {
  return status === 'queued' || status === 'running'
}

export function useProjects(
  opts: { mine?: boolean; staleTime?: number; live?: boolean; pollMs?: number } = {},
) {
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
    /**
     * ★★★ 2026-10-13 新增：**在工作区里轮询**（★ 修"进度不走"）⚠
     *
     * ⚠★★ 修之前的现象（★ 所有者原话）：
     * > 「**你这解析进度显示不准确呀，不是实时变化的，开始一直是3%，
     * >  我还以为卡了，刷新了一下浏览器，就变成100%了**」
     *
     * ★★ 根因：★ 这个钩子**从不轮询** ——
     *   · ★ 卡片上的进度是**一次性**抓的 ⇒ ★ 停在打开页面那一刻的值 ⚠
     *   · ★ 而 `useProgress()` 那个轮询钩子**写了却没有任何地方用** ⚠
     *   ⇒ ★★ 于是"刷新一下就对了" —— ★ 因为刷新会重新抓一次 ⚠
     *
     * ★ 为什么轮询**列表**而不是给每张卡片各挂一个 `useProgress`：
     *   · ★ 列表**一次请求就够**（★ 卡片上要的进度它都有）✅
     *   · ★ 每张卡片各轮询一个端点 ⇒ ★★ N 张卡片 = N 倍请求 ⚠
     *
     * ⚠★ 两个"会自己停"的条件（★ 都不靠人记得关）：
     *   · ★ 列表里**没有** `queued` / `running` 的项目 ⇒ ★ 停 ✅
     *   · ★ 标签页在后台（`document.hidden`）⇒ ★ 停（★ 不白耗电）✅
     */
    refetchInterval: (query) => {
      if (!opts.live) return false
      const list = query.state.data ?? []
      if (!list.some((p) => isJobActive(p.status))) return false
      return document.hidden ? false : (opts.pollMs ?? 2000)
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
    /**
     * ★★ 必填 —— **`owner/repo`**（⚠★ **不是 URL**）⚠
     *
     * ★ 为什么是这个名字：★ `publish/start/` 收的是 `repo`（★ 它自己拼 `repo_url`）⚠
     * ★ 而 `createProjectModal` 那边收的是用户填的**完整 URL** ⇒
     *   ★★ 用 `repoFullOf()` 先转一道（★ 与 `resolveRef` 同一套口径）✅
     */
    repo: string
    /** ★★ 必填 —— `github` / `gitee` */
    provider: string
    /**
     * ★ 可选 —— **分支 / tag**（★ 前端叫它 `commit`，⚠ 但它其实是"版本"）⚠
     * ★ 缺省 = 默认分支；★ 它只作**留痕**（★ 真正定位版本的是 `sha`）✅
     */
    ref?: string
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
    /** ★ 前端那个「创建后立即公开」勾选框（★ 缺省 = 不公开）*/
    is_public?: boolean
  }

  /**
   * ★★ 「新建项目」的返回 —— ⚠★ 它**不只是建项目**了 ⚠
   *
   * ★★ 现在它同时**已经投出解析作业**（★ 或者**复用了现成基图**）⚠
   */
  export interface PublishedProject {
    project_ref: string
    /** ⚠★ `null` **不代表失败** —— ★ `reused` 时它是 `null`，★ 而那是**成功** ⚠ */
    job_id: number | null
    job_state: string
    /** ★★ 复用了现成基图（★ 与 `useStartFetch` 同一个判据）*/
    reused?: boolean
    /** ★ 对应哪一版 */
    sha?: string
    message?: string
    steps?: Record<string, unknown>
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
    /**
     * ★★★ 2026-10-13 改：**打的是 `publish/start/`**（❌ 不再是 `POST /api/projects/`）⚠
     *
     * ⚠★★ 为什么必须换端点（★ 这是一个**完全堵死**的 bug）：
     *
     * ```
     * ★ `POST /api/projects/` 只建项目 —— ★★ 它【跳过了整条提交流水】⚠
     *   ⇒ ★ 没有 `ProjectReview` 记录
     * ★★ 而解析作业里的【许可闸门】要求"有一条【已放行】的审核记录"才肯放行 ⚠
     *   ⇒ ★★★ **它永远等不到** ⇒ ★ **图永远建不出来** ⚠
     * ```
     * ★ 实测：★ 库里 58 个项目没有审核记录 ⇒ ★★ 它们**一个都建不出图** ⚠
     * ★（★ 而且**不分许可** —— ★ 连 MIT 也会卡住，★ 因为缺的是那条记录）⚠
     *
     * ★ `publish/start/` 才是后端**为此设计**的那一个：
     *   · ★ 建项目 + 走提交流水（★ 于是**有审核记录** ⇒ 闸门能过）✅
     *   · ★ 建项目 + **投递解析作业**（★ 不必再手点「拉取代码」）✅
     *   · ★★ 顺带：★ `B182` 那条"浏览器算好的 sha"**这时才真的用上** ✅
     *     （★ 以前它发给 `POST /api/projects/`，★ 而那个端点**根本不读 sha**）⚠
     */
    mutationFn: async (body: CreateProjectBody): Promise<PublishedProject> =>
      unwrap(await apiPost<PublishedProject>('/api/projects/publish/start/', body, 'data')),
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
      // ⚠★★ 用 `isJobActive()` 判 —— ❌ 别再手写状态名 ⚠
      //   ★ 这里原本写的是 `status === 'error'` —— ★★ 而作业状态里**没有 `error`** ⚠
      //     （★ 真实取值：queued / running / done / **failed** / canceled）⇒
      //     ★★ 失败的项目**会永远轮询下去** ⚠
      //   ★ 收敛成一个函数 ⇒ ★ 以后状态名只在**一处**出现 ✅
      if (!isJobActive(query.state.data?.status)) return false
      return document.hidden ? false : pollMs
    },
  })
}
