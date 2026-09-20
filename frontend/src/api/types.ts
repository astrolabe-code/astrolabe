/** 接口类型定义(与 docs/frontend-contract.md 一一对应) */

export type EnvelopeKind = 'data' | 'spread' | 'legacy-error' | 'coded-error'

export interface ApiError {
  code?: string
  message: string
  status: number
  /** ④ 形态可能带 data(如 stale_rev 携带最新 graph_rev) */
  data?: any
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError }

/* ---------------------------------------------------------------- 身份 */

/** GET /api/whoami/ → ② 展开形态 */
export interface WhoAmI {
  authenticated: boolean
  username?: string
  is_staff?: boolean
  is_superuser?: boolean
  is_coadmin?: boolean
  avatar?: string | null
  admin_msg_unread?: number
  inbox_unread?: number
}

/* ---------------------------------------------------------------- 项目 */

/** ★ GET /api/projects/ → ② 展开形态 `{ok,projects:[…]}`
 *
 * ⚠★ 与旧项目的差别（`B164` 对账）—— **字段名与字段集都变了**：
 * - ★★★ 主键叫 **`project_ref`**（❌ 不是 `key`）
 * - ⚠ **没有** `icon` / `icon_lucide` / `category` / `score`（★ 新后端不做图标/分类/评分）
 * - ✅ **新增** `provider` / `repo_url` / `commit` / `graph_rev` / `node_count` / `edge_count` / `created_at`
 *
 * 依据：`app/web/views/projects.py::_project_json()`
 */
export interface ProjectSummary {
  project_ref: string
  name: string
  desc?: string
  is_public?: boolean
  /** github / gitee —— ★ B109：源码只能服务端拉取，所以托管平台是必填项 */
  provider?: string
  repo_url?: string
  commit?: string
  owner?: string
  /** ★ 前端靠它决定是否渲染「设置 / 解析」入口 */
  mine?: boolean
  /** none / queued / running / done / error */
  status?: string
  /** 0–100 */
  progress?: number
  graph_rev?: number
  node_count?: number
  edge_count?: number
  /**
   * ★★★ `B169` 新增：**是否已定版**（★ 代码已拉下**且**解析完成）。
   *
   * ★ 前端靠它决定「**拉取代码**」按钮的显隐：
   * - ★ `true` ⇒ **不给按钮**（点了必然 409 `graph_immutable`）
   * - ★ `false` / 缺省 ⇒ **给按钮** —— ★★ 注意**包含"拉取失败 / 解析失败"**
   *   （★ 所有者裁定：**失败还允许再发起**）⚠
   *
   * ⚠★ 为什么不用 `status` 判断：`status` 是**作业状态**（`Job.state`），
   * ★ 而"定版"是 **`Project.is_graph_built`** —— ★ 两者不是一回事 ⚠
   */
  graph_built?: boolean
  created_at?: string
}

export interface ProjectListData {
  projects: ProjectSummary[]
}

/** ★ POST /api/projects/ → **①型** `{ok,data:{project_ref,name}}`（★ status 201）
 *
 * ⚠★★ 入参与旧项目**完全不同** —— 见 `views/projects.py::_create()`：
 * - ★★ **`repo_url` 与 `provider` 都是必填**（⚠ 缺则 400 `missing_fields` / `invalid_provider`）
 * - 可选：`commit`（默认 HEAD）· `desc` · `is_public`
 * - ❌ 没有 `category` / `icon`
 */
export interface CreatedProject {
  project_ref: string
  name: string
}

/** ★ PATCH /api/projects/&lt;project_ref&gt;/ → ①型（⚠ 是 **PATCH**，❌ 不是 PUT） */
export interface UpdatedProject {
  project_ref: string
  name: string
  desc?: string
  is_public?: boolean
}

/** ★ GET /api/projects/&lt;project_ref&gt;/progress/ → **①型** `{ok,data:{…}}`
 *
 * 依据 `views/projects.py::progress()` —— ⚠ 字段与旧项目不同：
 * ★ 新增 `stage` / `job_id` / `queue_position` / `graph_rev`；❌ **没有** `graph_ready`
 */
export interface ProgressData {
  /** none / queued / running / done / error */
  status: string
  /** 0–100 */
  progress: number
  stage?: string
  job_id?: number | null
  queue_position?: number | null
  /** ⚠ 只有本人 / 管理员才拿得到（后端按权限裁剪） */
  error?: string
  graph_rev?: number
}

/* ---------------------------------------------------------------- 图谱 */

export interface GraphCounts {
  nodes: number
  edges: number
  by_kind: Record<string, number>
  by_type: Record<string, number>
  by_lang: Record<string, number>
}

/** GET …/graph/summary/ → ② 展开形态 */
export interface GraphSummary {
  project: { key: string; name: string }
  parse: { status: string; epoch: number; graph_rev: number; langs: string[] }
  counts: GraphCounts
  analysis: Record<string, any> | null
  lang_breakdown: Record<string, any>
}

/** GET …/graph-rev/ → ② 轮询心跳 */
export interface GraphRev {
  graph_rev: number
  parse_status: string
  parse_epoch: number
  parse_hash_v?: number | null
}

/** GET …/graph/nodes/ → ② 列表项 */
export interface CodeNodeBrief {
  uid: string
  kind: string
  name: string
  qname: string
  file_path: string
  line: number
  lang: string
  origin: string
  parent_uid: string
}

export interface GraphNodesPage {
  total: number
  limit: number
  offset: number
  items: CodeNodeBrief[]
}

/** GET …/graph/edges/ → ① {ok,data:{total,limit,offset,items}} */
export interface CodeEdgeBrief {
  from_uid: string
  to_uid: string
  type: string
  level: string
  confidence: number
  resolution: string
  dangling: boolean
  origin: string
  site_count: number
}

export interface GraphEdgesPage {
  total: number
  limit: number
  offset: number
  items: CodeEdgeBrief[]
}

/* ---------------------------------------------------------------- 作业 */

export interface Job {
  id: number
  kind: string
  /** queued / running / done / failed / canceled */
  state: string
  progress: number
  message: string
  created_at: string
  finished_at: string | null
  /** 仅本人/staff 可见 */
  error?: string
}

export interface JobsData {
  jobs: Job[]
}

export interface JobDetailData {
  job: Job
}

/* ---------------------------------------------------------------- 解析配置 */

export interface LimitItem {
  label: string
  user: number
  admin: number
  effective: number
  clamped: boolean
}

export interface HeaderDirMapItem {
  from: string
  to: string
}

/** GET/POST …/parse-config/ → ② 展开形态 */
export interface ParseConfig {
  limits: Record<string, LimitItem>
  notices: string[]
  exclude_names: string[]
  exclude_suffix: string[]
  header_dir_map: HeaderDirMapItem[]
  parse_parameters: boolean
  sig_strict_defaults: boolean
  incremental: { v: number | null; files: number }
}

/** POST 只提交传入键(可部分) */
export interface ParseConfigPatch {
  limits?: Record<string, number>
  exclude_names?: string[]
  exclude_suffix?: string[]
  header_dir_map?: HeaderDirMapItem[]
  parse_parameters?: boolean
  sig_strict_defaults?: boolean
}

/* ---------------------------------------------------------------- 节点 */

/** 邻居/引用的精简节点(后端 name_of) */
export interface NodeRef {
  uid: string
  kind: string
  name: string
  qname: string
  file_path: string
  line: number
}

/** GET …/graph/nodes/<uid>/ → 完整节点(_node_json) */
export interface CodeNodeDetail extends NodeRef {
  base_uid: string
  dir_path: string
  col: number
  end_line: number
  end_col: number
  parent_uid: string
  lang: string
  visibility: string
  return_type: string
  params: any[]
  param_count: number
  signature: string
  origin: string
  overloaded: boolean
  is_primary: boolean
  rev: number
}

/** 完整边(_edge_json,详情用,带 sites) */
export interface CodeEdgeDetail {
  from_uid: string
  to_uid: string
  type: string
  level: string
  resolution: string
  confidence: number
  site_count: number
  sites?: Array<Record<string, any>>
}

export interface NodeMemberRef {
  uid: string
  kind: string
  name: string
  qname: string
  file_path: string
  line: number
}

export interface NodeDetailData {
  node: CodeNodeDetail
  parent: NodeRef | null
  callers: Array<{ edge: CodeEdgeDetail; node: NodeRef }>
  callees: Array<{ edge: CodeEdgeDetail; node: NodeRef }>
  members: NodeMemberRef[]
  other_edges: Array<{ edge: CodeEdgeDetail; other: NodeRef }>
  caller_count: number
  callee_count: number
}

/** GET …/notes/<uid>/ → {ok:true,data:{uid,content,exists}} */
export interface NodeNote {
  uid: string
  content: string
  exists: boolean
}

/* ---------------------------------------------------------------- 搜索 */

export interface SearchItem {
  uid: string
  name: string
  kind: string
  file_path: string
  line: number
  dir_path?: string
  signature?: string
  cluster?: string
  is_entry?: boolean
  is_dead?: boolean
  metrics?: Record<string, any>
  score: number
  /** 命中的查询词项 */
  terms?: string[]
}

/** GET …/search/ → ② 展开形态(matched: all/partial/fuzzy/none) */
export interface SearchData {
  q: string
  matched: string
  total: number
  took_ms: number
  items: SearchItem[]
}

/* ---------------------------------------------------------------- 分析 */

export interface AnalysisOverview {
  counts: { entries: number; dead: number; clustered: number }
  entry_points: any[]
  processes: any[]
  clusters: any[]
  cycles: any[]
  metrics_stats: Record<string, number>
}

/* ---------------------------------------------------------------- spec 表单 */

export interface SpecFieldMeta {
  name: string
  type: string
}

/** GET …/spec-schema/ → 规划表单元数据 */
export interface SpecSchema {
  lang: string
  spec: Record<string, any> | null
  capabilities: Record<string, boolean>
  schema: {
    kinds: string[]
    params_kind: string[]
    visibility: string[]
    subtypes: Record<string, string[]>
    fields: SpecFieldMeta[]
  }
}

export interface Diagnostics {
  diagnostics: Record<string, any>
  counts: {
    nodes: number
    edges: number
    entries: number
    dead: number
    clustered: number
    cycles: number
  }
}

/* ---------------------------------------------------------------- 认证（U4） */

/**
 * ★ 认证相关类型（`B170` · ★ 用户名 + 密码）
 *
 * ⚠★ 字段**逐个对照后端**写，❌ 不照抄旧项目：
 * | 端点 | 后端依据 |
 * |---|---|
 * | `GET /api/auth/providers/` | `views/auth.py::providers()` + `invites.RegistrationGate.to_dict()` |
 * | `POST /api/auth/login/` | `views/auth.py::login()`（★ 契约 §12 定形）|
 * | `POST /api/auth/register/` | `views/auth.py::register()` |
 */

/** ★ 一种可用的登录方式（⚠★ 只有"真的配好了"的 OAuth provider 才在这里） */
export interface AuthProviderInfo {
  /** ★ `github` / `gitee` */
  key: string
  /** ★ 展示名（★ 用它，⚠ 前端不写死） */
  label: string
}

/**
 * ★★ **注册门禁**（`U4.6` 的开关组合 —— ★ 语义由 `B170` 重新定义）
 *
 * ⚠★★ **两个字段含义不同，别混用**：
 *
 * | 字段 | 它说的是 |
 * |---|---|
 * | ★★ **`registration_open`** | 【**注册入口是否对所有人可见**】← ★ 前端**只看这个**来决定显不显示注册按钮 |
 * | ★ `allowed` | 【**后端是否放行注册**】 |
 *
 * ⚠★ `registration_open === false` 时，`allowed` **仍然是 `true`** ——
 * ★★ 因为「**入口隐藏**」≠「注册被禁止」：★ **持邀请码者仍可注册** ✅（`B170`）
 */
export interface RegistrationGate {
  allowed: boolean
  invite_required: boolean
  /** ⚠★ 整站停服 —— ★ 优先级**高于一切**（连授权都不该发起） */
  paused: boolean
  /** ★★ 注册入口是否**对所有人可见**（★ 隐藏时，只有拿到邀请链接的人才看得到注册页） */
  registration_open: boolean
  /** ★ 给用户看的原因（★ 后端文案优先，⚠ 前端不做二次改写） */
  message: string
}

/** ★ `GET /api/auth/providers/` → **①型** */
export interface AuthProvidersData {
  providers: AuthProviderInfo[]
  registration: RegistrationGate
}

/**
 * ★ 后端返回的用户投影 —— ⚠★★ **只有这五个字段**。
 *
 * ⚠★ `auth.user_json()` **刻意不返回** `email` / `is_superuser` ——
 * ★ 理由（原文）：「★ 前端用不到，而**多给一个字段就多一分泄露面**」⚠
 * ⇒ ★★ **不要凭空声明 `is_superuser`**（★ 那是旧站 `whoami/` 的字段，★ 新后端**没有 `whoami/`**）⚠
 */
export interface AuthUser {
  id: number
  username: string
  is_staff: boolean
  /** ★ 第三方头像 URL —— ⚠ 密码注册的用户是**空串** */
  avatar: string
  /** ★ 有可用密码吗（★ `B170` 之后注册的用户都是 `true`）*/
  has_password: boolean
}

/** ★ 登录 / 注册的响应（★ `B170`）—— ★ 契约 §12：`data:{token, user, exp}` */
export interface AuthTokenData {
  token: string
  exp: string
  user: AuthUser
}
