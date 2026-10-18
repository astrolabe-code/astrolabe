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
   * ★★★ `B208`⑦ 新增：项目状态 —— `active` / `hidden`（`taken_down` = 已物理删除，
   * 行都没了 ⇒ 前端看不到也不需要处理）。
   *
   * ⚠★ `hidden` ⇒ **只有 owner 打得开**（协作者也不可）；前端拿到它时只可能是
   *   owner 本人 ⇒ **必须**渲染处置横幅（"已被管理员隐藏：理由"）⚠
   */
  state?: string
  /** ★ 最近一次处置的理由（`B196`：作者来问"为什么"必须答得出） */
  moderation_reason?: string
  /** ★★ `F2`（联调摸底）新增：**当前用户对这个项目能不能改** ⚠
   *
   * ⚠★ 为什么必须有它：没有这个字段，前端分不清"协作者"与"外人" ⇒
   *   · 给所有人渲染写入口 ⇒ 外人点击得 403（差体验）
   *   · 只给 owner 渲染 ⇒ 协作者被藏掉入口（更错——他们有权）
   * ★★ 后端 `projects.detail::_project_json` 现算现返（`can_edit` 判据）✅
   */
  can_edit?: boolean
  /** ★★ `F4` 预留：能不能管理协作者（owner/staff）—— 协作者管理页的入口显隐 ⚠ */
  can_manage?: boolean
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
  /** ★★ 节点主键（= 后端 `vid`）—— ★ 建笔记的 `node_id` 就是它 ⚠
   * ⚠★ `uid` 是**人类可读标识**（可能重复，只配看/搜）；挂东西一律用 `vid`（`B117`）✅ */
  vid: number
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

/* ---------------------------------------------------------------- 邀请（U4.7） */

/**
 * ★ 一条邀请（`B171`）—— ★ 字段**逐个对照** `web/views/invites.py::_invite_json()`。
 *
 * ⚠★ `token` **是会返回的** —— ★ 这看似"泄露"，★ 实则不然：
 * ★★ **管理员本来就要把这个凭证发出去**（★ 那正是它的用途）⚠
 */
export interface InviteInfo {
  /** ★ 凭证本体（★ 分享链接就是带着它） */
  token: string
  /** ★ 谁发的（★ 连带责任：`U4.7` 规则 3） */
  invited_by: string
  /** ★ 已用次数 */
  used: number
  /** ★ 最多可用几次（★ 默认 1 = 用一次即失效） */
  max_uses: number
  /** ★ 现在还能用吗（★ 未撤销 · 未过期 · 没用完 —— 三者都满足才为 `true`） */
  usable: boolean
  expires_at: string | null
  revoked: boolean
  note: string
  created_at: string | null
  /**
   * ⚠★ **后端拼的那条链接 —— 别直接用** ⚠
   *
   * ★ 它拼的是 `{ASTROLABE_SPA_URL}/invite/{token}`，★ 而**实测该配置是未填的默认值**
   * （`http://localhost:8080`）⇒ ★★ **那条链接打不开** ⚠
   * ⇒ ★★★ **请用 `AdminInvites.tsx` 里的 `shareUrl()` 自己拼**（★ 它用当前 origin）✅
   */
  url: string
}

/**
 * ★★ `GET /api/invites/` → **①型**
 *
 * ★ `B172` 新增分页 —— ⚠★ 没有这四件套，前端就只能"猜还有没有下一页" ⚠
 * （★ 后端依据：`web/views/invites.py::collection()` 的 `ok({...})`）
 */
export interface InviteListData {
  invites: InviteInfo[]
  /** ★ 已发出的**总数**（★ 前端据它算总页数） */
  total: number
  /** ★ 本页请求的条数上限（★ 后端钳过：1–200） */
  limit: number
  /** ★ 本页的起始偏移 */
  offset: number
  /** ★ 后面还有吗 */
  has_more: boolean
}

/* ------------------------------------------------------- 参数中心（U2.4 · B172） */

/**
 * ★ 一个可配置参数（`B172`）—— ★ 字段逐个对照 `web/views/admin.py::_setting_json()`。
 *
 * ⚠★★ **`label` / `note` 是"给人看"的** ——
 * ★ `core/appsettings.py` 的 `KeySpec` 文档写着「**没有说明的参数是灾难**」，
 * ★★ 所以那句说明**必须真的显示在管理页上**，❌ 而不是只躺在代码注释里 ⚠
 */
export interface AppSettingInfo {
  key: string
  value: boolean | number | string | Record<string, any>
  /** ★ 控件类型（★ 前端据它挑开关 / 数字框）—— ⚠ 不是 Python 类型名（那是实现细节） */
  type: 'bool' | 'int' | 'dict' | 'str'
  /** ★ 人类可读的名字 */
  label: string
  /** ★ 为什么存在 / 改它会怎样 */
  note: string
  /** ★★ **门禁类** —— ★ 影响全站可用性，⚠ 只有 `superuser` 能改 */
  gated: boolean
  /**
   * ★★ **当前用户能不能改它** —— ★ 由**后端算好**给前端。
   *
   * ⚠★ 为什么不让前端自己判：★ `auth.user_json()` **刻意不返回 `is_superuser`**
   * （★ 原文：「★ 前端用不到，而**多给一个字段就多一分泄露面**」）
   * ⇒ ★★ **前端根本猜不出来** ⚠ ⇒ ★ 所以这个字段**必须由后端给** ✅
   */
  editable: boolean
}

/** ★ `GET` / `POST /api/admin/settings/` → **①型** */
export interface AdminSettingsData {
  settings: AppSettingInfo[]
  /** ★ 当前用户够不够格改门禁类（★ 即 `is_superuser`） */
  can_edit_gated: boolean
}

/* ---------------------------------------------------------------- 设置（B190 / 契约 §22.1） */

/** 设置规格（给前端渲染控件用）——⚠ 每项带 source ⇒ 能显示「这一项为什么是这个值」 */
export interface SettingsSpec {
  key: string
  label: string
  note: string
  /** 后端 `type.__name__`：int / bool / str */
  type: string
  default: unknown
  value: unknown
  /** default / global / user / project */
  source: string
  /** ★ 门禁键：只有管理员能改（改 ⇒ 进 rejected ⇒ 整件 400 bad_setting） */
  gated: boolean
}

/** GET /api/me/settings/ 与 /api/projects/<ref>/settings/ 同形（② 型） */
export interface SettingsData {
  settings: Record<string, unknown>
  specs: SettingsSpec[]
}

/** PATCH 成功（② 型）——⚠ 请求体是【扁平】的 {键:值}，❌ 不是嵌套 settings */
export interface SettingsPatchResult {
  settings: Record<string, unknown>
  applied: Record<string, unknown>
}

/* ---------------------------------------------------------------- 笔记（B187/B201/B210 / 契约 §22.2） */

/** ★ kind 固定 5 种（B201）——❌ 不是用户自定义字段 */
export type NoteKind = 'flash' | 'question' | 'confuse' | 'pitfall' | 'summary'

export interface NoteBlock {
  id: number
  ordinal: number
  text: string
  fingerprint: string
  comment_count: number
}

export interface Note {
  id: number
  node_id: number
  kind: NoteKind
  title: string
  body: string
  card_skin: string
  is_public: boolean
  /** active / hidden（B208：管理员隐藏 ⇒ 只有作者可见） */
  state: string
  moderation_reason: string
  moderated_at: string
  /** B210：软删两列——非空即在回收站（正常笔记是空串） */
  deleted_at: string
  deleted_by: string
  like_count: number
  comment_count: number
  created_by: string
  created_at: string
  updated_at: string
}

/** 回收站列表项 = note + project_ref，且【无 body 字段】（D86①） */
export interface DeletedNote extends Omit<Note, 'body'> {
  project_ref: string
  /** ★ `B231`：项目维度三件套 ——* 回收站按项目分组就靠它 */
  project_name: string
  version_label: string
}

/** ★ `B231`：按项目分组后的一个卡片 */
export interface DeletedProjectGroup {
  project_ref: string
  project_name: string
  version_label: string
  notes: DeletedNote[]
}

/** ★ `B231`：导入结果 */
export interface ImportResult {
  restored_count: number
  unanchored_count: number
  restored: { note_id: number; file: string; title: string }[]
  unanchored: { note_id: number; file: string; title: string; unanchored?: boolean }[]
  manifest_project: string
  message: string
}

/** 列表（② 型） */
export interface NoteListData {
  total: number
  limit: number
  offset: number
  items: Note[]
}

/** 单篇读写（② 型）——⚠ PATCH 改了 body ⇒ blocks 会变，前端必须刷新段评锚点 */
export interface NoteDetailData {
  note: Note
  blocks: NoteBlock[]
}

/* ---------------------------------------------------------------- 评论（B201/B203④ / 契约 §22.3） */

export type AnchorKind = 'chapter' | 'paragraph'

/** ★★ 评论类型（`B214`：一列决定视觉；「回复谁」在正文的 @ 里） */
export type CommentKind = 'comment' | 'reply' | 'mention' | 'both'

export interface Comment {
  id: number
  note_id: number
  anchor_kind: AnchorKind
  block_id: number | null
  /** ★ 类型：comment 普通 / reply 回复头 / mention @高亮 / both 两者 */
  kind: CommentKind
  body: string
  /** 后端快照：段评 = 那一刻的原文 */
  quote: string
  /** 失锚标记（原段落已变更或已删除） */
  orphaned: boolean
  created_by: string
  created_at: string
}

export interface CommentListData {
  total: number
  limit: number
  offset: number
  items: Comment[]
}

/** POST 成功（① 型） */
export interface CommentCreateResult {
  comment: Comment
  note_comment_count: number
  block_comment_count: number | null
}

/* ---------------------------------------------------------------- 点赞（B203⑤/B205/D83 / 契约 §22.4） */

export interface LikeResult {
  liked: boolean
  like_count: number
  /** POST 时：本来就是赞过的；DELETE 时：本来就没赞过 */
  already?: boolean
  removed?: boolean
}

/* ---------------------------------------------------------------- 协作者（B202/B206/B207 / 契约 §22.5） */

export interface CollaboratorList {
  items: { username: string }[]
  total: number
}

export interface CollaboratorAddResult {
  added: boolean
  already: boolean
  username: string
}

export interface CollaboratorRemoveResult {
  removed: boolean
  username: string
}

/* ---------------------------------------------------------------- 管理处置（B208 / 契约 §22.6） */

export type ModerateAction = 'hide' | 'take_down' | 'restore'

export interface ModerateResult {
  action: ModerateAction
  /** hide / restore 有；take_down 没有（数据已物理删除） */
  state?: string
  reason: string
  /** hide / restore 有 */
  moderated_by?: string
  moderated_at?: string
  /** take_down 有 */
  deleted?: boolean
}

/* ---------------------------------------------------------------- 点赞状态（B211③ / 契约 §22.4） */

/** GET /api/notes/<id>/likes/?anchor_kind=&block_id= ⇒ ① 型 */
export interface LikeStatus {
  /** ★ 我赞过没有（每用户独立的状态；未登录 ⇒ false） */
  liked: boolean
  /** ★ 合并计数（聚合出来的，❌ 不是 UI 能本地 ±1 的数字） */
  like_count: number
}

/* ---------------------------------------------------------------- 已处置列表（B215 / 契约 §22.6） */

/** GET /api/admin/moderated/ 的项目项 */
export interface ModeratedProject {
  project_ref: string
  name: string
  owner: string
  is_public: boolean
  moderation_reason: string
  moderated_by: string
  moderated_at: string
}

/** GET /api/admin/moderated/ 的笔记项 */
export interface ModeratedNote {
  id: number
  title: string
  kind: string
  project_ref: string
  created_by: string
  moderation_reason: string
  moderated_by: string
  moderated_at: string
}

export interface ModeratedList {
  projects: ModeratedProject[]
  notes: ModeratedNote[]
}


/* ------------------------------------------------ 学习路径（B234 / D105） */

/** 路径里的一项（按数组顺序，`ordinal` = 第几个） */
export interface ReadingPathItem {
  ordinal: number
  vid: number
  name: string
  kind: string
  qname: string
  file_path: string
  line: number
  line_end: number
}

/** GET /api/projects/<ref>/reading-path/ */
export interface ReadingPathData {
  total: number
  items: ReadingPathItem[]
  /** ★ `D107`：已不在项目图里的 vid（* 前端提示用户处理，* ⛔ 不自动删）*/
  stale: number[]
}
