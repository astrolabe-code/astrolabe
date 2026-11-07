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
  /** ★ 作者昵称（* 为空回落 owner）⚠ */
  owner_display?: string
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

/* ---------------------------------------------------------------- 解析配置 */

/* ---------------------------------------------------------------- 节点 */

/* ---------------------------------------------------------------- 搜索 */

/* ---------------------------------------------------------------- 分析 */

/* ---------------------------------------------------------------- spec 表单 */

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

/* ---------------------------------------------------------------- 邀请（U4.7） */

/**
 * ★ 一条邀请（`B171`）—— ★ 字段**逐个对照** `web/views/invites.py::_invite_json()`。
 *
 * ⚠★ `token` **是会返回的** —— ★ 这看似"泄露"，★ 实则不然：
 * ★★ **管理员本来就要把这个凭证发出去**（★ 那正是它的用途）⚠
 */

/**
 * ★★ `GET /api/invites/` → **①型**
 *
 * ★ `B172` 新增分页 —— ⚠★ 没有这四件套，前端就只能"猜还有没有下一页" ⚠
 * （★ 后端依据：`web/views/invites.py::collection()` 的 `ok({...})`）
 */

/* ------------------------------------------------------- 参数中心（U2.4 · B172） */

/**
 * ★ 一个可配置参数（`B172`）—— ★ 字段逐个对照 `web/views/admin.py::_setting_json()`。
 *
 * ⚠★★ **`label` / `note` 是"给人看"的** ——
 * ★ `core/appsettings.py` 的 `KeySpec` 文档写着「**没有说明的参数是灾难**」，
 * ★★ 所以那句说明**必须真的显示在管理页上**，❌ 而不是只躺在代码注释里 ⚠
 */

/* ---------------------------------------------------------------- 设置（B190 / 契约 §22.1） */

/* ---------------------------------------------------------------- 笔记（B187/B201/B210 / 契约 §22.2） */

/** ★ kind 固定 5 种（B201）——❌ 不是用户自定义字段 */
export type NoteKind = 'flash' | 'question' | 'confuse' | 'pitfall' | 'summary'

/**
 * ★★ 一个段落（`B235`：**现算的，不是数据库行**）⚠
 *
 * ``` 
 * 段 = 两个空行之间的内容（* 代码块内也一样）
 * 锚点 = fingerprint（* 原来的 `id` 已下线）⚠
 * ```
 */
export interface NoteBlock {
  ordinal: number
  text: string
  fingerprint: string
  comment_count: number
}

export interface Note {
  id: number
  /** ★ 对外标识（* URL / 接口都用它，⛔ 不暴露自增 pk）⚠ */
  ref: string
  /** ★ 作者昵称（* 为空回落 created_by）⚠ */
  created_by_display?: string
  node_id: number
  kind: NoteKind
  title: string
  /** ★★ 编号 = 该作者的第几篇（`D113`）；阅读页显示成 №001 ⚠ */
  seq: number
  /** ★★★ 锚点快照（`D125`）—— 阅读页左栏显示「挂在哪」⚠ */
  node_snapshot?: {
    vid: number
    name: string
    kind: string
    qname: string
    file_path: string
    line: number
    line_end: number
  }
  body: string
  /** ★ 全局卡片 id（`note:<项目>/<ref>`）；与数字主键 id 不是一回事 */
  card_id?: string
  /** ★ 深入自哪张卡 */
  parent?: string | null
  /** ★ 引用了哪些已写好的卡（双向可见） */
  links?: string[]
  /** ★ 从这张卡深入出去的子卡 id */
  children?: string[]
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

/** ★★ 全局笔记搜索命中项（* 带项目三件套，* 用于链回项目）⚠ */
/**
 * ★★ **搜索结果条目（瘦结构）**（2026-10-23）⚠
 *
 * > 「从 meilisearch 中取出的搜索结果条目就不要再去数据库里验证了……用户真正点击
 * >   某个条目，再查数据库。」
 *
 * ⛔ 不再包含 like_count / comment_count / body —— * 那些要回库，* 列表里也不显示 ⚠
 */

/* ---------------------------------------------------------------- 点赞（B203⑤/B205/D83 / 契约 §22.4） */

/* ---------------------------------------------------------------- 协作者（B202/B206/B207 / 契约 §22.5） */

/* ---------------------------------------------------------------- 管理处置（B208 / 契约 §22.6） */

/* ---------------------------------------------------------------- 点赞状态（B211③ / 契约 §22.4） */

/* ---------------------------------------------------------------- 已处置列表（B215 / 契约 §22.6） */

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
  /** ★★ 这一站已经写过「小结」了吗（`D123`）⚠ */
  has_summary?: boolean
}

/** GET /api/projects/<ref>/reading-path/ */
export interface ReadingPathData {
  total: number
  items: ReadingPathItem[]
  /** ★ `D107`：已不在项目图里的 vid（* 前端提示用户处理，* ⛔ 不自动删）*/
  stale: number[]
  /** ★★ 已写过「小结」的站数（`D123` 章节进度）⚠ */
  done?: number
}


/* ============================== 用户空间（2026-10-24）============================== */

interface SpaceItemBase {
  created_at: string
  updated_at: string
}

