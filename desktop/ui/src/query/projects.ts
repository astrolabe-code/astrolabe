import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import { unwrap } from '../api/errors'
import { personalApi } from '../api/personal'
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
/**
 * ★★ 轮询间隔：**首查快、之后退避**（2026-11-02）⚠
 *
 * 所有者原话：
 * 「进度，我估计大多项目都不到 3 秒就解析完了，你觉得呢？」「首查快、之后退避就行」
 *
 * 实测（不含拉源码）：
 * ```
 * itsdangerous 159 节点  0.37s      linux 0.11 1291 节点 0.38s
 * Java 4499 节点 0.95s              C++ fmt 7124 节点   1.83s
 * ```
 * ⇒ 多数作业 2~4 秒就结束。**固定 2 秒轮询**的后果：
 *   · 小项目：用户盯着"0%"两秒，然后一下子跳到完成
 *   · 大项目：白白每 2 秒问一次
 *
 * 改法：第 1 次 600ms（快速确认是不是已经完成），之后 1.2s → 2.4s → 4s 封顶。
 * ⚠ 用 `dataUpdateCount` 推退避档位 —— 不另外存状态，刷新页面自动从第一档开始。
 */
const POLL_STEPS: readonly number[] = [600, 1200, 2400]
const POLL_CAP = 4000

/**
 * 取第 `step` 档的间隔。
 *
 * ⚠ 不用 `POLL_STEPS[step] ?? POLL_CAP` 那种"靠越界取 undefined 兜底"的写法：
 * ```
 * · 行为上它是安全的（JS 越界返回 undefined，不抛错，`??` 只兜 null/undefined）
 * · 但**意图不清**：读者要自己想"为什么越界是允许的"
 * · 而且一旦数组里出现 0，或有人把 `??` 改成 `||`，就会静默变味（不报错、值也不对）
 * ⇒ 显式判断"超出档位"，并把 NaN / 负数 / 小数一并规整
 * ```
 */
function pollDelay(step: number): number {
  const i = Number.isFinite(step) ? Math.max(0, Math.floor(step)) : 0
  return i < POLL_STEPS.length ? POLL_STEPS[i] : POLL_CAP
}

/**
 * 退避档位：成功次数 + **失败次数** 一起算。
 *
 * ⚠★ 只用 `dataUpdateCount` 的坑（真隐患，不是数组那个）：
 *   React Query 的 `dataUpdateCount` **只在请求成功时 +1**；
 *   请求一直失败时它不涨 ⇒ 每次都停在第 1 档 ⇒ **每 600ms 重试一次**，
 *   而"请求失败"往往正是因为服务端正忙 ⇒ 等于自己再加压。
 *   ⇒ 取 `max(成功次数, 失败次数)` 当档位，失败也会退避到 4 秒。
 */
function pollStep(q: { state: { dataUpdateCount: number; errorUpdateCount: number } }): number {
  return Math.max(q.state.dataUpdateCount, q.state.errorUpdateCount)
}

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

export function useProject(projectRef?: string | null) {
  return useQuery({
    queryKey: ['project', projectRef],
    enabled: !!projectRef,
    queryFn: async (): Promise<ProjectSummary> =>
      // ★ 个人版走本地边车
      personalApi.getProject(projectRef!) as unknown as Promise<ProjectSummary>,
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
