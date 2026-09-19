# 前端对接契约(v3.36 · 评审稿 v28)

> 与 `frontend-decisions.md` 配套。本文是 React SPA 的 api client 归一与 TypeScript 类型定义的**唯一依据**。
>
> ⚠ **两条口径必须分清(不要混读)**:
> - **§1–§13 = 现状实测契约**(核对日期 **2026-09-09**,逐文件只读核对,未改动任何后端代码)—— **已实现**,可直接照此编码。
> - **§14–§19 = v3.33 目标契约**(随后端 8 份分册的「v3.33 · 评审稿 v19」)—— **尚未实现**;前端**可提前适配,但不得假定服务端已支持**。
>
> 现状章节**只加「⤴ 目标变更见 §NN」指针,不改写实测结论**(实现进度以代码为准)。
> 原则:**后端既有接口形态不动**,4 种混用 envelope 由前端 `src/api/client.ts` 集中归一;新增契约以 §14–§19 为准。
> 版本对齐:本轮同步的决策登记见 `frontend-decisions.md` **D60–D66**(2026-09-11);后端侧依据 = `backend-design.md`(主文)+ 附录 A–G,共 8 份。

---

## 1. 响应形态(envelope)与归一规则

后端现有 4 种响应形态,前端统一映射为 `{ok:true,data}` / `{ok:false,error:{code,message,status}}`:

| 形态 | 出现位置 | 归一规则 |
|---|---|---|
| ① `{ok:true, data:X}` | `edit`、`notes`、新 `authapi` | `data = X` |
| ② `{ok:true, 展开字段…}` | `graph/summary`、`graph/nodes`、`search`、`analysis`、`diagnostics`、`jobs`、`graph-rev`、`changes`、`parse-config` | `data = 除 ok 外的全部字段` |
| ③ `{"error":"文案"}` + HTTP status | 大量只读接口(404 / 403 / 400) | `error = {message: 文案, status}` |
| ④ `{ok:false, error:{code,message}}` + status | `edit.py` CAS 失败 | 直接映射,保留 `code` |

关键错误码处理:
- `unauthenticated`(401)→ 清 token、跳登录
- `stale_rev`(409,带 `data.graph_rev`)→ 前端重读图版本后自动重放一次
- `project_busy`(409)→ toast 提示稍后重试
- `too_many_changes`(400)→ 提示单次变更数超限,前端自动分批

> **⤴ 目标变更(v3.33,见 §15/§16/§17)**:新增 `rate_limited`(**429** + 响应头 `Retry-After` + **前端自动退避倒计时**,§15)、`contract_incompatible`(409,§16),以及 `project_deleting`(§17)。★ **v28 删除**:`stale_baseline` / `no_write_lease` / `stale_writer` 及迁移期全部错误码(租约 / 版本协商 / 迁移链已删)。上表 4 条为**现状已实现**口径,继续有效。

---

## 2. 主链端点清单(全部已注册于 `projects/urls.py`)

> **指针(不复制正文)**:`project_ref` 是项目的**唯一标识**(名称可重名,靠 `project_ref` 区分;`source_path` 才是路径权威)。规范见 **`backend-design.md` §0.0 / §4.4**。前端只需知道:①全部 URL 已统一走 `encodeURIComponent(project_ref)`;②**不得**从 `project_ref` 解析用户名/归属(`^proj_[0-9a-f]{32}$` 不嵌用户名);③**`project_ref` 不得作为授权凭证**;④删除后该 `project_ref` 一律 **404**(不重试);⑤**`project_ref` 不可变**,前端不得假设「改名会换 `project_ref`」;⑥**形态校验(v28 定稿)**:严格 `^proj_[0-9a-f]{32}$`(**固定 37 字符**),由**路由转换器与视图层直接校验**;**无存量数据 → 不存在「旧 key 兼容 / 宽放行」**;404 **只表示「项目不存在 / 无权」**;⑦**导入入口**:`.webapkg` 导入的 `project_ref` **一律由生成器重新分配**(不接受外部提供),前端无需做形态分支。**目录命名规则(`<项目名>_<project_ref 后 8 位>`)与改名联动属服务端内部实现,不进本契约。**

| 用途 | 方法与 URL | 关键响应字段 | 消费页面 |
|---|---|---|---|
| 登录 | `POST /api/auth/login/`(新增) | `data:{token,user:{id,username,is_staff,avatar},exp}` | Login |
| 登出 | `POST /api/auth/logout/`(新增) | `{ok:true}` | 全站 |
| 当前用户 | `GET /api/auth/me/`(新增) | `data:{user,exp}` | 启动校验 |
| 项目列表 | `GET /api/projects/` | `{projects:[{project_ref,name,icon,icon_lucide,category,desc,is_public,score,owner,mine,status,progress}]}` | Workspace |
| 新建项目 | `POST /api/projects/` | `{ok,project_ref,name,category}` | Workspace |
| 项目改/删 | `PUT/DELETE /api/projects/<project_ref>/` | — | ProjectHome |
| 上传 zip | `POST /api/projects/<project_ref>/upload/` | 立即返回,解析进 Job | Workspace |
| 重新解析 | `POST /api/projects/<project_ref>/reparse/` | — | ProjectHome |
| 解析进度 | `GET /api/projects/<project_ref>/progress/` | status/progress | 上传弹窗、ProjectHome |
| 项目概览 | `GET …/graph/summary/` | `parse{status,epoch,graph_rev,langs}`、`counts{by_kind,by_type,by_lang,nodes,edges}`、`analysis(stats)`、`lang_breakdown` | ProjectHome |
| 节点列表 | `GET …/graph/nodes/?kind=&q=&file=&lang=&origin=&is_dead=&is_entry=&cluster=&limit=≤500&offset=` | `{ok,total,limit,offset,items:[{uid,kind,name,qname,file_path,line,lang,origin,parent_uid}]}` | GraphPage(列表模式/种子)、分析清单 |
| 节点详情 | `GET …/graph/nodes/<path:uid>/` | `node`(`_node_json` 全集)、`parent`、`callers≤200`、`callees≤200`、`members≤300`、`other_edges≤100`、`caller_count`、`callee_count` | NodeDetail |
| **边(新增)** | `GET …/graph/edges/?level=file\|symbol&type=&origin=&dangling=&file=&limit=&offset=` | `{ok:true,data:{total,limit,offset,items:[{from_uid,to_uid,type,level,confidence,resolution,dangling,origin,site_count}]}}` | GraphPage 画布 |
| 图版本 | `GET …/graph-rev/` | `graph_rev`、`parse_status`、`parse_epoch`、`parse_hash_v` | GraphPage 轮询 |
| 增量(暂不用) | `GET …/changes/?since=N` | nodes/edges/deletions/truncated(P9 债:节点 delta 会漏报) | — |
| 搜索 | `GET …/search/?q=&kind=&limit=≤200` | `q`、`matched`(all/partial/fuzzy/none)、`total`、`took_ms`、`items[{uid,name,kind,file_path,dir_path,line,signature,cluster,is_entry,is_dead,metrics,score,terms}]` | SearchBox / 结果页 |
| 分析 | `GET …/analysis/` | `counts{entries,dead,clustered}`、`entry_points`、`processes`、`clusters`、`cycles`、`metrics_stats` | AnalysisSearch |
| 健康度 | `GET …/diagnostics/` | `diagnostics`(解析器原始键)、`counts{nodes,edges,entries,dead,clustered,cycles}` | AnalysisSearch |
| 解析配置 | `GET\|POST …/parse-config/` | `limits{key:{label,user,admin,effective,clamped}}`、`notices`、`exclude_names`、`exclude_suffix`、`header_dir_map`、`parse_parameters`、`sig_strict_defaults`、`incremental{v,files}` | ProjectHome 配置抽屉 |
| spec 元数据 | `GET …/spec-schema/?lang=` | `lang`、`spec`、`capabilities`、`schema{kinds,params_kind,visibility,subtypes,fields}` | SpecForm |
| planned 元数据 | `GET /api/spec/planned/schema/` | kind 标签 + 可用语言(恒含 generic) | SpecForm |
| 规划节点 CRUD | `POST/PUT/DELETE …/planned/nodes/` | `{ok,created,uid}` | NodeDetail |
| 规划边 | `POST/DELETE …/planned/edges/` | `{ok,created,edge}` | NodeDetail |
| derive 建议 | `POST …/planned/derive/` `{kind,file_path,lang}` | 建议头文件路径 + guard | SpecForm |
| 笔记 | `GET/PUT/DELETE …/notes/<path:uid>/` | `data{content,exists}` / `saved` | NodeDetail |
| 图写操作(**★ v28 目标改判**) | `POST …/edit/` `{base_graph_rev?,changes:[…]}` | `{ok,data:{graph_rev,applied}}` | ★ **仅项目维护者**(图修补,主文 §2.3.12);`base_graph_rev` **由必需降为可选**(缺省 = **LWW**,不做冲突协商) |
| 手动转正 | `POST …/promote/confirm/` `{uid,target_uid}` | `{ok,already,uid}` | NodeDetail |
| 迁移 dry-run | `POST …/migrate/plan/` `{ops:[…]}` | `{ok,dry_run,ops,msg}` | 后续 |
| 作业历史 | `GET …/jobs/` | `{jobs:[{id,kind,state,progress,message,created_at,finished_at,error?(本人)}]}` | ProjectHome |
| 作业详情 | `GET /api/jobs/<id>/` | `{job:{…}}` | 轮询 |
| 取消作业 | `POST /api/jobs/<id>/cancel/` | `{ok,canceled}`(只置标志) | ProjectHome |

---

## 3. 数据模型字段(`projects/models_graph.py`)

**CodeNode**
`uid`(项目内唯一)、`base_uid`(重载族)、`kind`、`subtype`、`name`、`qname`、`file_path`、`dir_path`、`line/col/end_line/end_col`、`parent_uid`、`lang`、`signature`、`return_type`、`params`(JSON)、`modifiers`、`annotations`、`visibility`(file/module/public)、`origin`(source/planned)、`lifecycle`(`""`/planned/drifted)、`spec`、`planned_sig`/`baseline_sig`/`actual_sig`/`sig_match`、`metrics`、`cluster`、`is_entry`、`is_dead`、`hidden`、`rev`、`extra`(overloaded/is_primary)、`parse_epoch`。

**CodeEdge**
`from_uid`、`to_uid`、`type`(CALLS/IMPORTS/EXTENDS/READS/WRITES/SAME_AS)、`level`(file/symbol)、`confidence`、`resolution`(exact 1.0 / qualified 0.9 / scope 0.8 / name 0.5 / heuristic 0.3 / planned 1.0)、`sites`(≤50)、`site_count`、`origin`、`dangling`、`rev`。
唯一:`(project, from_uid, to_uid, type, origin)`。

**节点详情返回的 `_node_json` 全集**
`uid, base_uid, kind, name, qname, file_path, dir_path, line, col, end_line, end_col, parent_uid, lang, visibility, return_type, params(≤20), param_count, signature(≤400), origin, overloaded, is_primary, rev`。

> **⤴ v3.33 目标增量(见 §17/§18)**:`lifecycle` 升级为**请求体必填字段**(节点 `active`\|`hidden`、边 `active`\|`deleted`;**常规期就必填**,不是迁移期新增);★ **v28**：请求体改为 **`snapshot{repo,commit,parser_v,parse_hash}`**（§17.1）；~~`writer_token` / `lease_epoch` / `files[].base_file_rev` / `files[].state` / `migration`~~ **已删除**；边在目标契约里用 `from_vid`/`to_vid` 口径表达;客户端本地模型(`local_node` / `local_edge` / `local_pending` / `local_project` / `parse_cache`)见 §19。

---

## 4. 写操作契约(CAS)

> ⚠ **v28 目标改判**:本节描述的是**现状实现**。目标口径见 §17.1 末注 —— `edit/` 仅用于**维护者图修补**,`base_graph_rev` **降为可选**(缺省 = **LWW**,主文 §2.3.12)。

```http
POST /api/projects/<project_ref>/edit/
{ "base_graph_rev": 12, "changes": [ {...}, {...} ] }   // ★ v28:目标口径下 base_graph_rev 为可选(缺省 = LWW)
```
- 成功:`{ok:true, data:{graph_rev:13, applied:[...]}}`
- `409 stale_rev`:版本已变化,响应体带最新 `graph_rev` → 前端重读后重放一次
- `409 project_busy`:项目正忙
- `400 too_many_changes`:单次变更数超限(`AppSetting.graph_max_changes_per_request`)→ 前端分批
- 权限:`permission_service.edit_err`(owner/协作者可写,分享链接只读)

---

## 5. 权限与游客语义

- 读:`permission_service.view_err(user, project, share)`;写:`edit_err(...)`。
- 公开项目可带 `?share=<token>` 只读/协作访问;前端需透传 share 参数。
- 未登录游客:读公开项目可用;所有写操作需前端 `RequireAuth` 前置拦截 + 后端校验双保险。

---

## 6. 新增端点实现约束(D7)

- 位置:`projects/views/graphdata.py` 新增 `graph_edges`;路由 `projects/urls.py` 注册 `api/projects/<str:project_ref>/graph/edges/`(视图已在 `projects/views/__init__.py` 导出)。
- 权限沿用 `_proj()`(内部 `view_err` 含 share 支持)。
- 过滤:`level`(仅 `file`/`symbol` 生效,其它值忽略)、`type`(逗号分隔,最多 10 个)、`origin`(仅 `source`/`planned`)、`dangling`(`1/true/yes` 与 `0/false/no`);分页 `limit`(默认 500,钳制到 1~5000)、`offset`;返回 `total`。
- **扩展 `file=<uid 前缀>`**(本次新增,支撑"点开文件再取 symbol 级边展开"):命中 `from_uid OR to_uid` 前缀的边,避免为展开一个文件而拉全量 symbol 边;前缀长度截断 200。
- 排序 `type, from_uid, to_uid`(固定顺序,保证分页稳定);只返回边字段,不 join 节点;前端自行与 `graph/nodes` 结果做 uid 关联。
- 不修改任何既有接口的响应结构。
- **⤴ v3.33 目标变更(见 §18)**:`graph/edges/` 与跳数查询改为 **`limit` 必填 + 服务端强制夹取(起步上限 2000)+ 不透明 `cursor` + `next_cursor` + `summary{node_count,edge_count,by_type}`**,**不再使用深分页 `offset`**;多跳默认只返回子图摘要,`summary_only` 按需展开。**两条线并列**:本节(默认 500 / 钳 1~5000 / `offset` / `total`,2026-09-10 冒烟验收)是**已实现**口径,§18 是目标口径。
- **采用统一新 envelope**:`{ok:true, data:{total,limit,offset,items}}` 或 `{ok:false, error:{code,message}}`(D17)。
- **冒烟记录(2026-09-10)**:合成 4 条边(1 file + 2 source symbol + 1 planned symbol,其中 1 条 dangling)后,`level=file`→1、`level=symbol`→3、`symbol&dangling=0`→2、`symbol&dangling=1`→1、`file=smoke/a.py`→4、`origin=planned&type=CALLS`→1、`limit=99999` 钳到 5000、`level=symbol&limit=1&offset=1` 分页稳定、envelope 为 `{ok,data}`、不存在项目→404;测试数据已清理(`manage.py check` 无 issue)。

---

## 7. 认证与 CSRF 精确边界(D11 / D12)

`BearerAuthMiddleware` 仅作用于 `/api/`,三态判定:

| 请求特征 | 行为 |
|---|---|
| `Authorization: Bearer <token>` 合法(未过期、未撤销) | 挂 `request.user`;置 `request._dont_enforce_csrf_checks=True`(免 CSRF) |
| **无 Authorization 头** | **原样放行** → 既有 session + CSRF 路径。旧模板 `base.js` 已自动补 `X-CSRFToken`,不会 403 |
| 有 Authorization 但无效/过期/撤销 | `401 {ok:false,error:{code:"unauthenticated"}}`,**不回退 session** |

- `/api/auth/login`、`/api/auth/logout` 显式 `csrf_exempt`。
- env `API_STRICT_BEARER=1` 时 `/api/` 无 Authorization 直接 401(本阶段默认 `0`,待旧模板迁移后启用)。
- 中间件顺序:`CorsAllowMiddleware` → `BearerAuthMiddleware` → … → `CsrfViewMiddleware`(Bearer 必须在 CSRF 之前)。
- **XSS 防护要求**(token 存 localStorage):后端发 CSP(`default-src 'self'`);富文本一律 DOMPurify 净化;禁止 `dangerouslySetInnerHTML` 直出;TTL 7/30 天 + 可撤销。

---

## 8. `/edit/` 写操作完整语义(D13,已存在)

```http
> ⚠ **v28 目标改判**(同 §4):下面是**现状**请求形态;目标 `base_graph_rev` 变为**可选**。

```http
POST /api/projects/<project_ref>/edit/
{ "base_graph_rev": 12, "changes": [ { "op": "update", "uid": "...", "rev": 7,   // ★ v28:同上,可选
                                       "patch": { "signature": "..." } } ] }
```

- **顶层 CAS**:`base_graph_rev` 与当前 `graph_rev` 不一致 → `409 {ok:false,error:{code:"stale_rev"},data:{graph_rev:当前值}}` → 前端重读后重放一次。　★ **v28 目标口径**:`edit/` 仅用于**维护者图修补**,`base_graph_rev` **降为可选**(缺省 = **LWW**,不做冲突协商,主文 §2.3.12)—— **本节以上为现状口径**。
- **单项 rev 校验**:`change.rev` 与行 `rev` 不一致 → `409 code="stale"` + `data.expected_rev`。
- **门禁错误**:`graph_not_ready`(409,带 `parse_status`)、`project_busy`(409)、`too_many_changes`(400,上限 `AppSetting.graph_max_changes_per_request` → 前端自动分批)。
- **`op` 清单**:

| op | 必需字段 | 约束 |
|---|---|---|
| `create` | `spec` | 走 `upsert_planned` |
| `update` | `uid`、`patch` | 仅 `origin="planned"`;patch 白名单 `spec/signature/annotations/flags/doc/hidden/params/return_type/visibility/modifiers/subtype`;改 `signature` 会同步 `baseline_sig/planned_sig` |
| `hide` | `uid` | 置 `hidden=True` |
| `delete` | `uid` | 先归档笔记(失败 → `orphan_archive` 500),写**软删除墓碑**(PG `lifecycle=deleted` + `graph_node.deleted`;v27 删 `GraphDeletion` 表) |
| `rename` | `uid`、`patch.name` | 仅 planned;重建 uid 并迁移两端边 |
| `edge_create` | `edge` | — |
| `edge_update` | `id`(或 `edge_id`)、`patch` | patch 仅允许 `note` |
| `edge_delete` | `id`(或 `edge_id`) | 写墓碑 |

- 成功:`{ok:true,data:{graph_rev,applied:[{kind,uid,nodes,updates,deletions,…}]}}`。

---

## 9. 分析面板数据映射(D14,不新增端点)

| 面板区块 | 数据源 | 字段 |
|---|---|---|
| 统计卡(入口/死代码/已聚类) | `GET …/analysis/` | `counts{entries,dead,clustered}` |
| 规模统计(复杂度/行数/节点/可调用/环) | `GET …/analysis/` | `metrics_stats{total_complexity,total_lines,nodes,callables,dead,entries,cycles}` |
| 入口点列表 | `GET …/analysis/` | `entry_points[]` |
| 聚类列表 | `GET …/analysis/` | `clusters[]` |
| 执行流 | `GET …/analysis/` | `processes[]` |
| 环 | `GET …/analysis/` | `cycles[]`(取自 `diagnostics.cycles`) |
| 健康度(闸门与转正诊断) | `GET …/diagnostics/` | `diagnostics`(解析器原始键)、`counts{nodes,edges,entries,dead,clustered,cycles}` |
| 死代码清单(可翻页) | `GET …/graph/nodes/?is_dead=1&limit=&offset=` | `items[]` |
| 入口点清单(可翻页) | `GET …/graph/nodes/?is_entry=1&limit=&offset=` | `items[]` |

---

## 10. 上传 client(D15)

- `GET/POST/PUT/DELETE` 走统一 JSON 归一;**上传独立实现** `upload(url, file, {onProgress})`。
- 用 **XMLHttpRequest**(fetch 无上传进度):`xhr.upload.onprogress` 计算百分比。
- `FormData` 追加文件字段;**不设置 `Content-Type`**,由浏览器生成 `multipart/form-data; boundary=…`。
- 上传响应不强制走归一(后端 `/upload/` 立即返回 + Job),前端按原样解析并对接 `/progress/` 轮询。

---

## 11. envelope 逐接口原始形态登记(D17)

| 端点 | 原始形态 | 归一 |
|---|---|---|
| `/api/auth/*`(新增) | ① `{ok,data}` | 新接口统一,直接映射 |
| `graph/edges/`(新增) | ① `{ok,data}` | 同上 |
| `graph/summary`、`graph/nodes`、`search`、`analysis`、`diagnostics`、`jobs`、`graph-rev`、`changes`、`parse-config`、`spec-schema` | ② `{ok:true, 展开字段}` | `data` = 除 `ok` 外全部 |
| 只读接口错误(404/403/400) | ③ `{"error":"文案"}` | `error={message,status}` |
| `edit` 成功 | ① `{ok,data}` | 直接映射 |
| `edit` 失败 | ④ `{ok:false,error:{code,message}}` | 保留 `code`,`data` 透传(如 `graph_rev`) |
| `notes` | ① `{ok,data}` | 直接映射 |
| `planned/*` | ② `{ok:true, created, uid/edge}` | `data` = 除 `ok` 外全部 |

**新接口约定**:本阶段新增的 `/api/auth/*` 与 `graph/edges/` 一律使用 `{ok:true,data}` / `{ok:false,error:{code,message}}`;既有接口保持不变以免破坏旧模板。

---

## 12. SPA 认证端点 `/api/auth/*`(新增,D2/D8/D11)

> ⚠★ **新项目（astrolabe）的口径变更（`B141` · `USERS-AND-AUTH.md` U4）**：
> ★ **一期不实现用户名 + 密码登录** —— ★ 登录走 **GitHub / Gitee OAuth**；
> ★★ **注册受邀请制约束**（★ `OAuth 首次登录 = 注册`，**必须过邀请校验**）；
> ★ 并有 `registration_open` / `login_open` / `paused` **三个开关**（管理员可控）。
> ⚠ **本节下面关于 `login_failed` / 密码的表述属旧站现状**，★ **新项目以 U4 为准。**

| 端点 | 方法 | 请求 | 成功 | 失败 |
|---|---|---|---|---|
| `/api/auth/login/` | POST | `{username,password,remember?}`(JSON) | `200 {ok:true,data:{token,user:{id,username,is_staff,avatar},exp}}` | `400 bad_json` / `400 missing_fields` / `401 login_failed` |
| `/api/auth/logout/` | POST | 需 Bearer | `200 {ok:true,data:{revoked:bool}}`(幂等) | — |
| `/api/auth/me/` | GET | 需 Bearer | `200 {ok:true,data:{user,exp}}` | `401 unauthenticated` |

**要点**
- **TTL**:`remember=true` → `API_TOKEN_TTL_HOURS_REMEMBER`(默认 720h/30 天);否则 `API_TOKEN_TTL_HOURS`(默认 168h/7 天)。**不自动续期**,过期即重新登录。
- **token 存储**:明文只返回一次;库中仅存 `blake2b(raw, digest_size=32)` 哈希。
- **登录校验复用**:`accounts.views.auth.login_validate(request, username, password, create_session=False)` —— 三桶限流(文案"尝试过于频繁,请 N 秒后再试")、待审/锁定("账号已锁定,请 N 分钟后再试")、弱密码拦截、失败计数与锁定、`AuditLog` 全部与模板登录页一致;**不创建 session**。
- **错误码语义**:`login_failed`(401)与 `unauthenticated`(401)必须区分 —— 前端只对 `unauthenticated` 清 token,登录失败不会误清。
- **⤴ v3.33 目标变更(见 §15/§16)**:被限流**不得再包成 401** —— 统一 **`429` + `Retry-After` + `error.code=rate_limited`**;`account_locked` / `weak_password` 改为**不在登录响应中返回**(仅登录后或邮件提示,**防账号枚举**);新增合约协商头 `X-Contract-Version`(请求)/ `X-Contract-Degraded`(响应)与 `409 contract_incompatible`。⚠ 本节上面的 `401 login_failed` 是 **2026-09-09 实测现状** —— 已核实:`accounts/views/auth.py:61` 的 `login_validate` 返回**中文文案**(`:72` 即限流文案),`authapi/views.py:54-57` 把该文案**无差别包成 `401 login_failed`**,故「密码错 / 限流 / 锁定 / 弱密码 / 待审」目前**前端无法区分**。
- **中间件**:`mysite.bearer.BearerAuthMiddleware`(三态,见 §7;位置在 `AuthenticationMiddleware` **之后**,避免 `request.user` 被冲掉)、`mysite.cors.CorsAllowMiddleware`(白名单 `DJANGO_CORS_ORIGINS`;**OPTIONS 预检只有白名单内 Origin 放行,白名单为空则一律 403**;无 Origin 头原样放行)。
- **清理/撤销命令**:`python manage.py cleanup_api_tokens [--days 7] [--revoke-user <username>]`(后者= 登出全部设备)。
- **冒烟记录(2026-09-10)**:`me(无token)=401`、`me(坏token)=401`、`login(缺字段)=400`、`login(错误密码)=401 login_failed`、`me(有效token)=200`、`logout=200 revoked:true`、`logout 后 me=401`、`预检(白名单外)=403`、旧 `/login/` 页 `200`;`manage.py check` 无 issue。

---

## 13. 验收工具与环境事实(2026-09-10)

**图谱读接口冒烟脚本(仓库内,不落 /tmp)**

```bash
cd /home/webapp/demo && sh -c 'set -a; . ./.env; set +a;
    ./venv/bin/python frontend/scripts/smoke_graph_api.py'
```

- 作用:临时插入 `smoke#` 前缀的合成节点/边/`CodeAnalysis`,**以游客身份**通过 HTTP 覆盖
  `graph/summary`、`graph/nodes`(kind/q 过滤)、`graph/edges`(level/type/dangling/`file=` 前缀)、
  `graph/nodes/<uid>/`、`analysis/`、`diagnostics/`、`search/`、`graph-rev/`,共 **29 项断言**;
- 收尾在 `finally` 里删除全部合成行并还原 `graph_rev/parse_langs/parse_status`(实测残留 0);
- 结论:2026-09-10 全绿。

**环境事实(影响联调口径)**:本机库内 6 个项目全部为旧解析管线产物 —— `CodeNode`/`CodeEdge` 表为空、
`parse_epoch=0`、`graph_rev=0`、无 `Job` 记录,即 v3.14 新图管线在本机从未真实跑过。因此
「图谱 / 节点详情 / 搜索 / 分析」四页目前只能用合成数据验收;真实数据联调需先跑一次新版解析。

**顺带加固的既有接口(D52,D53 与 SPA 顶栏头像相关)**

- `POST /api/user/avatar/`(旧站也在用):上传前 `≤2MB` 粗筛 → `accounts.avatar.normalize_avatar`
  归一化(**解码前**查单边 ≤10000px / ≤2500 万像素、`exif_transpose` 摆正并去 EXIF、
  压到 ≤320px、含透明存 PNG 否则 JPEG q85、动图仅首帧)→ 落盘,原图不入库;
- 成功响应在原有 `{ok, avatar}` 基础上**追加** `bytes / source_bytes / source_size / size`
  (旧前端只读 `ok` 与 `avatar`,向后兼容);
- 失败一律 `400 {error:"<中文文案>"}`:`仅支持 jpg/png/gif/webp 图片` /
  `头像图片不能超过 2MB,请压缩后再上传` / `图片尺寸过大(单边上限 10000px、总像素上限 25 百万像素),请先压缩再上传` /
  `文件内容不是有效图片`;
- 历史头像批处理:`manage.py compress_avatars [--apply]`(默认预览;扩展名变化时同步更新
  `UserProfile.avatar`);冒烟脚本 `scripts/smoke_avatar_compress.py`(**24 项全通过**)。

**SPA 访问入口(D50)**:`http://<主机>/app/`(Django 托管,方案 A);前端路由由 `mysite/spa.py::spa_app`
回退 `index.html`(`Cache-Control: no-store`),`/app/assets/*` 走 `static.serve` 协商缓存。

---

# 以下为 **v3.33 目标契约(未实现)**

> 来源 = 后端 8 份分册(主文 `backend-design.md`「v3.33 · 评审稿 v19」+ 附录 A–G)。
> **前端可据此提前适配,但不得假定服务端已支持**;实现进度一律以代码为准。
> 现状章节(§1–§13)与本节冲突时:现状章节描述**已实现**行为,本节描述**目标**行为 —— 二者**并列存在**,不互相覆盖。

## 14. API 版本化与弃用登记

> 主文 §7 要求:破坏性变更必须**新开版本路径**(`/api/v2/…`),旧路径保留期 = **至少 90 天且至少 2 个发布**(二者取长);**新开 / 弃用时间表逐版本记进本文件** —— 下表即该要求的落点。

**规则**

1. 对外 JSON **只增不改**:新增字段一律**可选**;旧字段**语义不变**。
2. 破坏性变更(删字段 / 改语义 / 改必填性 / 改响应码)**必须新开版本路径** `/api/v2/…`,旧路径在保留期内并存。
3. 保留期 = `max(90 天, 2 个发布)`;**禁止**"文档刚说弃用、代码当天就删"。
4. 每条弃用都要在本表登记:何时弃用、何时可删、替代方案、**前端迁移动作**。

**登记表**

| 版本 | 日期 | 变更 | 类型 | 替代 | 旧路径可删于 | 前端动作 |
|---|---|---|---|---|---|---|
| v3.14(基线) | 2026-09-09 | §1–§13 全部端点 | — | — | — | 无(已实现) |
| v3.33 · 评审稿 v19 | 2026-09-11 | `graph/edges/` 增 `cursor` / `next_cursor` / `summary` / `summary_only` / `depth` | **新增(非破坏)** | — | — | 可选适配,见 §18 |
| v3.33 · 评审稿 v19 | 2026-09-11 | `analysis/` 增 `derived_stale`(**v27 后置,一期不发**) | **新增(非破坏)** | — | — | 收到则显示"派生指标待更新",见 §18 |
| v3.33 · 评审稿 v19 | 2026-09-11 | 新增 `POST /api/projects/<project_ref>/graph/sync/`、`POST\|DELETE /api/projects/<project_ref>/hash-migration/`、`GET /api/version` | **新增端点(非破坏)** | — | — | 见 §16 / §17 |
| v3.33 · 评审稿 v19 | 2026-09-11 | 请求新增协商头 `X-Contract-Version`;新增 `409 contract_incompatible` | **新增(非破坏)** | — | — | 见 §16 |
| v3.33 · 评审稿 v19 | 2026-09-11 | 限流响应由「401 + 中文文案」改为 **`429` + `Retry-After` + `rate_limited`** | **破坏性(响应码变更)** | 新语义即正解 | **⏳ 未定(见下)** | 见 §15;过渡期需**同时识别**旧「401 + 限流文案」与新 `429` |
| v3.33 · 评审稿 v19 | 2026-09-11 | 登录链路 `account_locked` / `weak_password` **不再在响应中返回** | **破坏性(信息消失)** | 登录后提示 / 邮件 | **⏳ 未定(见下)** | 不得依赖这两个码做 UI 分支 |
| v3.35 · 评审稿 v27 | 2026-09-13 | **净减法**:删 `X-Contract-Degraded` / 宽限期降级 / 引导页兜底;删迁移期请求体与 `/hash-migration/` 端点;`cursor` 分片与 `derived_stale` **后置**;`writer_epoch` + `lease_seq` → **`lease_epoch`**;`graph_rev` 改**每项目**发号;`parse_cache` 降为**文件级** | **破坏性(需适配)** | 见 D72 |

> ⚠ **两条破坏性变更尚未定终点(P1,需评审裁决)**:上表最后两行在 M5 意义上属破坏性变更,但后端文档**没有给出**"是否新开 `/api/v2/…`"与"旧路径保留到何时"的结论 → 本表**按规则记账并显式留空**,裁决前**不得实施**。建议方向(供评审):①限流改 `429` 属**响应码纠正**、不改 JSON 结构 → 可不新开路径,但必须给**过渡期**(前端在一段时间内两种形态都识别);②`account_locked` / `weak_password` **保留码值、仅约定"永不返回"** 即可,无需新开路径。

---

## 15. 限流统一契约(对应主文 §8.1 + 附录 B11)

⚠ **背景**:同一件"被限流"目前有 **5 种表现、3 套计数器**(`core/ratelimit.py` 登录三桶 / `projects/services/ratelimit.py` 通用滑窗 / `core/captcha.py` 失败计数),且 `authapi` 把限流**包成 401**。**本节是唯一口径。**

### 15.1 响应契约(所有限流点必须一致)

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 37

{ "ok": false, "error": { "code": "rate_limited", "message": "操作过于频繁，请 37 秒后可重试" } }
```

- **必须**是 `429` + **响应头 `Retry-After`(秒)** + `error.code = rate_limited`
- **不得**只返回中文文案;**禁止**把限流包成 `401` 或其它码
- **前端动作**:按 `Retry-After` **自动退避并显示倒计时**;`rate_limited` **不等于** `unauthenticated` —— **不要清 token**

### 15.2 键设计与后端(服务端,前端只读)

键 = `ip | dev_id`(IP 为主键、`dev_id` 为二级维度;无合法 `dev_id` → 退化为 `ip|none`);全键设 TTL;键数有上限(超限先清桶再淘汰最旧);**被限流请求不计数**(靠 TTL 自然过期)。后端 = **Redis**(多实例严格一致)。

### 15.3 故障降级(必须分链路,不能一刀切)

| 链路 | 策略 | 后果 |
|---|---|---|
| **认证链路**(登录 / 注册) | **fail-closed** —— 后端不可用时降级为**本地内存限流 + 账号锁定**,**不放行** | 否则"DoS 掉限流后端"就成了**暴力破解的绕过手段** |
| **读路径 / 普通操作** | **fail-open** + 告警 | 不能因缓存故障锁死全站 |

### 15.4 登录链路错误码(前端契约)

| 原因 | HTTP | `error.code` | 可重试 | 额外信息 | 前端动作 |
|---|---|---|---|---|---|
| **被限流** | **429** | `rate_limited` | ✅ | **`Retry-After`(秒)** | 退避 + 倒计时,不清 token |
| 账号锁定 | **不返回**(仅登录后 / 邮件) | ~~`account_locked`~~ | — | — | **不得依赖**(防账号枚举) |
| 默认 / 弱密码 | **不返回**(仅登录后 / 邮件) | ~~`weak_password`~~ | — | — | **不得依赖**(防账号枚举) |
| 验证码要求 / 失败 | 400 | `captcha_required` | ✅ | — | 展示验证码 |
| 凭据错误 | 401 | `login_failed` | ✅ | — | 提示"用户名或密码错误" |
| 未登录 / token 失效 | 401 | `unauthenticated` | — | — | **清 token → 跳登录** |

### 15.5 同步上传遇限流**不丢数据**

`/graph/sync/`(§17)收到 `429` → **进本地 outbox 排队**(带 `Retry-After` 退避重试),**不退化为失败**;**禁止**丢弃未上传的变更集。

### 15.6 已知现状缺陷(代码未改,勿按本节编码上线)

- `authapi/views.py:54-57` 把 `login_validate` 返回的文案**无差别包成 `401 login_failed`** → 「密码错 / 限流 / 锁定 / 弱密码 / 待审」**前端目前无法区分**;
- `accounts/views/auth.py:61` 的 `login_validate` **返回中文文案而非错误码**(`:72` 即限流文案)。
- 后端设计的改造(改为返回 `(user, error_code, detail)` + 按码映射状态码)**留待评审通过后另起一轮**;在此之前前端按 §1 / §12 的现状口径编码。

### 15.7 ~~两条「设备身份线」必须分家~~(★ v28 已删除)

> ★ **v28 删除**:`writer_token` 与 `DeviceSession` **整体删除** —— 图不可变 ⇒ **无「写权身份」**(主文 §4.1.2),故本节**整体作废**。
> **保留的只有一条线**:限流侧**只用 `dev_id`**(浏览器 Cookie:不可信、**永不落库**、非法值退化为 `ip|none`,由 IP 桶 + 账号锁定兜底)。
> ⚠ **「两条身份线混用」的风险已随机制删除而消失** —— 现在**只剩一条线**(限流维度)。

---

## 16. 前端合约协商(对应主文 §7)

### 16.1 握手方式

- **请求头**:前端所有 `/api/` 请求带 **`X-Contract-Version: <前端契约版本>`**
- **服务端三态**:

| 情形 | 服务端行为 | 前端动作 |
|---|---|---|
| 版本**受支持** | 正常响应 | 无 |

### 16.2 为什么是 409 而不是 426

`426 Upgrade Required` 语义是「协议升级」、**不是应用层错误**;且会形成「**刷新后仍是旧代码**」的**死锁**(旧代码永远过不了 426,却又不肯换新代码)→ 弃用 `426`,改用 **`409 contract_incompatible`**。

### 16.3 前端必须做的 4 件事

1. **统一注入** `X-Contract-Version` —— 只在 `src/api/client.ts` 一处注入,避免各调用点漏加。
2. 归一响应时**区分"key 缺失"与"值为 `null`"**:**key 缺失 = 服务端版本低、该字段被降级**,不得当作 `null` 渲染或写入表单。
3. 识别 **`409 contract_incompatible`** → 提示「应用已更新，请关闭标签页重新打开」(v27:宽限期降级与引导页兜底已移除)
4. **静态资源必须版本化**:`index.html` 不长缓存、资源名带 hash —— 否则"刷新"无效(现状 D50 已满足:`/app/` 返回 `index.html` 且 `Cache-Control: no-store`,`/app/assets/*` 走哈希文件名)。

### 16.5 新增端点 `GET /api/version`

返回**最新契约版本**(用于 409 后的提示与诊断)。**状态:v3.33 目标契约,尚未实现。**

- 响应形态(目标,与新增接口约定一致):`{ ok: true, data: { contract_version, api_version, min_supported } }`

---

## 17. 写路径契约(浏览器本地解析 → 上传)

> **权威源 = 主文 §5.4**(`backend-design.md` 第 484–553 行);附录 D7.1 只是 F3 脚本的**提取清单**(引用不复制);两者不一致时**以 §5.4 为准**。
> **端点复用既有路由**:`POST /api/projects/<project_ref>/graph/sync/`(**不新开路由**);**v27:只有一种请求体** —— 迁移期契约与 `hash_algo` 分支校验已删除。

### 17.1 常规期请求体(前端 TS 类型以此为准)

```jsonc
POST /api/projects/<project_ref>/graph/sync/
{
  "project_ref": "proj_xxx",         // 取值 = Project.project_ref；**VID 公式的唯一输入**
  "snapshot": {                      // ★ v28：快照标识（幂等的唯一依据）
    "repo": "https://github.com/x/y", "commit": "abc123…",
    "parser_v": "ts-parser-1.4.0", "parse_hash": "…"
  },
  "files": [                         // 仅完整性清单（★ v28：无版本协商）
    { "path": "src/a.c", "sha1": "…" },
    { "path": "src/b.c", "sha1": "…" }
  ],
  "upserts": {
    "nodes": [ { "uid": "...", "kind": "function", "name": "...", "qname": "...",
                 "file_path": "src/a.c", "line": 42, "signature": "...",
                 "is_entry": false, "is_dead": false, "cluster": "src",
                 "lifecycle": "active" } ],       // ★ 常规期必填(见 17.3)
    "edges": [ { "from_uid": "...", "to_uid": "...", "type": "CALLS",
                 "confidence": 0.7, "resolution": "syntactic",
                 "site_count": 3, "level": "symbol", "origin": "source",
                 "lifecycle": "active" } ]        // ★ 常规期必填(见 17.3)
  },
  "deletes": {
    "nodes": [ { "uid": "uid…" } ],
    "edges": [ { "from_uid": "…", "to_uid": "…", "type": "CALLS" } ]
  },
  "analysis": { "stats": { }, "diagnostics": { },
                "entry_points": [], "processes": [], "clusters": [] }
}
```

**字段口径(前端必须遵守)**

| 项 | 规定 |
|---|---|
| **一律传 `uid`,不传 VID** | VID 由两端各自算:`HASH(project_ref + "\0" + uid, out_len=16)` → **32 位小写 hex**(`HASH` = **固定 `sha256_16`**(v27:算法不可变));两侧结果必须一致(有测试向量) |
| `lifecycle` | **常规期必填**(枚举见 17.3) |
| `files[].path` | 必须过路径安全:禁 `\0` 与控制字符、禁 `..` 段、禁绝对路径/盘符;允许空格与非 ASCII;**先 NFKC 归一化**;长度 ≤ **4096** |
| `analysis` 落位 | **按位置**:`local`(未发布)→ **客户端是唯一写者,必须传**;服务端解析 / 公开 / `collab` → **服务端是唯一写者,客户端值被忽略**(可不传) |
| 幂等键 | 节点 = `(project_ref, vid)`;边 = `(project_ref, vid_from, vid_to, type)` |
| 传输编码 | **CBOR + gzip**;按 **1 万节点/片**分片提交,失败可重放 |
| 删除 | `deletes.nodes = [uid…]`、`deletes.edges = [{from_uid,to_uid,type}]`;服务端算完 VID 后**按 VID 删**;**删除走软删除**,不是物理 `DELETE`(见 17.5) |
| 版本语义(★ v28) | **客户端不再持有 `base_graph_rev`**;一致性由 **`parse_hash` 幂等**保证(主文 §5.3);`graph_rev` 由服务端**用 `Project.next_graph_rev`(每项目)发号**,与 outbox 行插入**同一 PG 事务**(v25 P0-13:此前只说"+1"、**序列未登记**);**outbox 每消费一步不 +1**(否则客户端 CAS 会连环 `stale_rev`) |

> **VID 输入唯一 = `project_ref`**（v27：不再有"数字主键"）：客户端只持有 `project_ref`、用**单一函数** `computeVid(projectRef, uid)` 算 VID；同步入口由服务端用 `project_ref` 解析并**重算校验** → **"用错值"在结构上不可能**（§0.0）。

### 17.3 `lifecycle` 为什么是必填(易被误当成"迁移期新增")

- 它是**常规期就有的请求体字段**:D1.3 的 `CREATE TAG` 有它、PG 顶点属性有它、§3.3 的 `local_node` 有它 —— **唯独契约层此前缺失**;后果是**用户手动标记的 `hidden` 在常规同步里就已经丢了**(不只是迁移期)。
- 枚举:**节点 `active` | `hidden`**;**边 `active` | `deleted`**。
- **`deleted` 例外**:走**软删除路径**,**不出现在 `upserts`**(见 17.5)。
- **迁移期 `lifecycle` 由客户端显式上送**,**服务端不得用解析产物覆盖**(用户手动标记的 `hidden` 不是解析产物);客户端**必须保留本地旧图的 `lifecycle`**,重传时随新 VID 一起带上。

### 17.5 软删除语义(前端必须按 `lifecycle` 过滤)

- 删除走**软删除**(写墓碑),**不是物理 `DELETE`**;删除后节点 / 边以 `lifecycle = 'deleted'` 存在。
- **前端必须按 `lifecycle` 过滤**;**⚠ 不得依赖 `dangling`** —— `dangling` 只是"边指向未解析目标"的属性,**不是删除标记**。
- ⚠ **读接口的删除可见性口径在 8 份后端分册中未明确规定**(附录 D5.2 只定义了**写入侧**墓碑)→ **列为待裁决项**;在裁决前,**以"服务端读接口返回什么就渲染什么 + 本地按 `lifecycle` 兜底过滤"**为准。

### 17.6 `graph_sync_status`:项目卡片与徽章文案

| 状态 | 前端展示 |
|---|---|
| `ok` | 正常 |
| `degraded` | 图同步滞后(可提示"索引更新中") |
| `deleting` | 删除中(一切写被拒) |

> ⚠ **v27：项目状态只有 3 态** —— `ok` / `degraded` / `deleting`。`paused` 是**运维门禁标志**(不进状态机;写操作 `503` + `Retry-After`);原 `pending_repair` → **outbox `dead` + 卡片提示「待修复(等本设备上线重传)」**;原 `inconsistent` → **作业失败 + 告警**;`migrating` 已随迁移链删除。

- **优先级全序**(多个同时成立时取高者):**`deleting > degraded > ok`**(v27:仅 3 态;`paused` 为运维门禁标志、不进全序)
- UI **必须显示"原因 + 下一步动作"**,**不能只显示一个状态码**
- ★ **v28:本行删除** —— 图不可变 ⇒ **不存在「无租约的只读设备」**;快照内容**永不陈旧**(锚定不可变 commit,主文 §2.3.12)

---

### 17.7 深分析(加速器)契约(v28 新增)

**边界(前端只需记住这一条)**:**1–2 跳走现有读路径**(可加 `hops` 参数,本地图优先);**>2 跳或图算法走加速器** —— 是**异步作业 + 排队**,不是即时查询。

| 动作 | 端点 | 请求 / 响应 |
|---|---|---|
| 申请 | `POST /api/projects/<project_ref>/graph-analysis/` | `{kind, args, hops?}` → `202 {job_id, state:"queued", queue_position, est_wait_s}` |
| 查询 | `GET /api/projects/<project_ref>/graph-analysis/<job_id>/` | `{state:"queued\|running\|done\|failed\|capacity", progress?, result?, error?}` |
| 心跳 | `POST …/graph-analysis/heartbeat` | 每 **60s** 一次(**续期占用**,否则 180s 后被释放) |
| 释放 | `POST …/graph-analysis/release` | 关闭项目页 / 切换项目 / 登出 / 点"结束分析"时调用 → `204` |

**前端义务**

- **无权限表现(默认)**:未获管理员开通的用户,「深度分析」入口**置灰 + 文案「该功能需管理员开通」**;服务端返回 `403 graph_analysis_not_authorized` 时按此文案处理(**不做自动申请**)。
- **不受影响**:1–2 跳邻域展示与本地图**照常可用**(授权只影响加速器深分析)。
- **本地图优先**:1–2 跳先在 `local_node` / `local_edge` 上算,缺数据再回服务端(**不要为 1 跳走加速器**)。
- **排队可见**:`queue_position` / `est_wait_s` 必须展示;预计等待 > 20s 时提示"深度分析排队中,可先看本地 1–2 跳"。
- **结果缓存**:同 `(project_ref, graph_rev, kind, args)` 重复申请**直接命中缓存**(秒回),不必提示"重新排队"。
- **可读错误**:`graph_analysis_capacity`(池满/超限)、`analysis_session_expired`(占用超 60min)→ 中文文案 + 重试入口。
- **不要**在前端假设"图数据库一直握着我的项目" —— 空闲 15min 就会被释放,**重新申请即可**(结果已缓存)。

### 17.8 发布与冲突决策契约（v28 新增）

| 动作 | 端点 | 说明 |
|---|---|---|
| 发布 / 更新发布 | `POST /api/projects/<project_ref>/publish/` | body:`{visibility, content:{code, graph, notes, meta}}` —— **content 逐项勾选**（`code` 默认 `false`） |
| 取消发布 | `DELETE /api/projects/<project_ref>/publish/` | 服务端**彻底删除**该项目公开内容（源码 / 笔记 / 图 / 索引）；审计只留**匿名化 ref** |
| 状态 | `GET /api/projects/<project_ref>/sync-state/` | `{state: not_published \| in_sync}`（★ v28 删 `local_ahead` / `server_ahead` / `diverged`） |

**硬要求**

- ★ **v28**：**无 `diverged`、无冲突弹窗** —— 图不可变 ⇒ **不存在「两端都改过」**(主文 §5.6)；重解析产出**新快照**,旧快照与其上的解释原样保留（**版本对照视图**呈现,§2.3.13）。
- **前端不得实现任何自动合并 / 自动择优 / 后台静默同步** —— 同步只发生在用户显式操作时。
- 发布页必须逐项显示「将上传什么」(源码 / 图谱 / 笔记 / 元数据),**源码默认不勾**。

## 18. 读路径契约(分片 + 派生就绪)

### 18.3 「契约零改动」清单(前端**不需要**改的部分)

以下是后端设计里**明确声明契约不变 / 响应结构不变**之处 —— 前端**无需适配**:

| 项 | 说明 |
|---|---|
| `GET /api/projects/`、项目 CRUD、`upload/`、`reparse/`、`copy/`、`progress/`、`jobs/`、`parse-config/` | 契约与字段不变(数据来源仍在 PG) |
| 节点详情 / 笔记 / 规划 / `spec-schema` | **零改动**(前端读 PG 结果) |
| `search/` | **零改动**(底层可切 OpenSearch,对外形态不变) |
| `analysis/` / `diagnostics/` | **响应结构不变**(服务端内部合并两表) |
| 旧站模板(`projects.html`、`analysis_page.js` 等)与 SPA 的**只读部分** | 对外 JSON 结构保持 → **零改动** |
| `graph/nodes/` 的 `limit` / `offset` / `total` | 按后端文档,**D8.2 只把 `graph/edges/` 与跳数查询纳入 `cursor` 化** → `graph/nodes/` 现状**继续有效**(若评审认为它也要 `cursor` 化,属新增裁决) |

---

## 19. 客户端义务(本地模型 / 校验上限 / 文案,易漏项集中登记)

### 19.1 本地 store(IndexedDB)字段 —— 前端 TS 类型来源

| 模型 | 字段 |
|---|---|
| `local_project` | `project_ref` / **`hosted`(bool)** / `src_root_ref` / **`snapshot{repo,commit,parser_v,parse_hash}`** / `files[{path,sha1}]` |
| `local_node` | `vid` / `uid` / `kind` / `name` / `qname` / `file_path` / `line` / `signature` / `is_entry` / `is_dead` / `cluster` / `project_ref` / `graph_rev` / `lifecycle`(**`active` \| `hidden` \| `deleted`**) |
| `local_edge` | `vid_from` / `vid_to` / `type` / `confidence` / `resolution` / `site_count` / `level` / `origin` / `project_ref` / `graph_rev` / `lifecycle`(**`active` \| `deleted`**) |
| `parse_cache` | `user_id` / **`project_ref`** / `key` / `file_sha256` / `parser_v` / `payload` / `created_at` / `hit_count` |
| **`local_annotation`**（★ 本轮新增） | `project_ref` / `anchor_id` / `kind`(**`annotation` \| `question` \| `answer`**) / `body_md` / `author_user_id` / `source` / `created_at` / `updated_at` / `rev` —— **私有项目的本地解释 / 提问**（主文 §3.3 / H5） |
| **`local_path`**（★ 本轮新增） | `project_ref` / `path_id` / `base_snapshot_ref` / `title` / `intro` / `target_reader` / `steps[]` / `author_user_id` / `rev` —— **私有项目的本地阅读路径**（主文 §3.3 / H5） |
| 不上传（仅本地） | `local_snapshot` / `local_annotation` / `local_path`（★ v28：~~`local_pending`~~ / ~~`local_conflict`~~ 已删） |

**硬要求**

- **命名空间隔离**:本地 store 按 **`user_id + project_ref`** 命名;`parse_cache` 的 key **必须含 `project_ref`**(否则跨项目串味)
- **删除 / 登出必须清本地**(含 `parse_cache`)—— 服务端**无法远程删除浏览器本地数据**
- **删除 / 导出页面必须提示"请在浏览器端清理"**;`.webapkg` 快照在**用户本地、服务端不可控**,导出页必须**明确告知**

### 19.2 客户端校验上限(本地就该拦,别等服务端拒)

| 类别 | 字段 | 规则(与附录 B9.1 一致) |
|---|---|---|
| 枚举类 | `kind` / `lang` / `origin` / `lifecycle` / 边 `type` / `level` / `resolution` | **严格白名单**,不在集合内**直接拒**(不"清洗") |
| 标识类 `uid` | 字符集 **`[A-Za-z0-9_:.\-#@/]`**,长度 ≤ **1024** | ⚠ C++ 的**析构函数 / `operator` / 模板签名**会产生 `~` / `<` / `>` / 空格 → 后端已有「**uid 规范化 + 转义规则**」,**前端必须用同一套规则**(跨端共享实现 + 测试向量),**不得直接拒绝合法的 C++ 符号** |
| 标识类 `vid` | **严格 `^[0-9a-f]{32}$`** | 用严格正则,不用宽松字符集 |
| 路径类 `file_path` | 禁 `\0` 与控制字符、禁 `..` 段、禁绝对路径与盘符;**先 NFKC 归一化**;≤ **4096** | 允许空格与非 ASCII |
| 展示类 `name` / `qname` / `cluster`(≤1KB)、`signature`(≤**512**) | **只做长度 + 控制字符检查,保留原值** | **转义责任在渲染层** |
| 富文本类(笔记正文等) | 服务端**白名单标签净化** | 前端**不得** `dangerouslySetInnerHTML` 直出;一律 DOMPurify 净化 |
| 请求体大小 | 单请求 **≤10MB**(超出 **413**) | 客户端先自查,别发上去被拒 |
| 自洽性 | `node_count` / `edge_count` 必须与数组长度自洽 | "声称 10 万节点只传 3 条" → **400** |
| 引用完整性 | `edges[].from_uid` / `.to_uid` 必须存在于本批次或项目已有节点 | 否则服务端**拒绝该边** |

> ⚠ **渲染层必须转义(前端强制义务)**:后端把「展示类字段保留原值」的**转义责任显式写进了前端契约** —— 服务端**不会**帮你转义 `name` / `qname` / `signature`,前端**不得假设上游已净化**。

### 19.3 错误上报与信息泄露

- 前端错误上报**不得携带项目标识**（`local` 项目零上行：不带 `project_ref` / `file_path` / `uid`；`hosted` 项目按 §0.0 口径）,**不带 `uid` / `file_path` 明文**
- 服务端返回的错误**不回显** `uid` / `file_path` 明细;**越权统一 `404`** —— 前端不要把 404 解读成其它含义

### 19.4 解析图「来源与置信度」必须标注

- UI 必须标注图来源与置信度档:「**本地 / 语法级**」vs「**服务端 / 语义级**」,**避免用户误信**
- 浏览器侧(语法级)**可做**:定义 / 引用 / 类 / 函数 / 变量提取、语法级调用关系(启发式)、include / import / 继承(可见部分)
- 浏览器侧**不可做**:精确调用图(重载决议 / 模板实例化 / 虚函数派发)、宏展开、跨编译单元、系统头
- 置信度口径:浏览器侧 `confidence` **0.6–0.8**、`resolution = syntactic`;服务端 **1.0**、`qualified` / `semantic`
- **C++ 分两档**:一期只做 **C / Python** 的语法级;C++ 只产出**高置信子集**,语义级留给服务端

### 19.5 实时功能(WebSocket / 频道层)

- LSP / 终端等实时功能走 **WebSocket**(后端 v19 把频道层从 InMemory 切到 **Redis**)—— 切 Redis 本身是**修 bug**:此前多进程 / 多实例下 **WS 广播失效**。
- 频道层故障 → 广播失效,**列为功能性告警** → **前端必须实现 WS 重连 / 重试**,并**保留轮询回退**路径。
- ⚠ **订阅契约缺失**:8 份后端分册**未给出**频道名 / 订阅键规则、消息结构、鉴权方式 → **前端不得假定消息结构稳定**,按"可能变化"设计。

### 19.6 导出 / 删除(GDPR,M8)

| 项 | 契约 |
|---|---|
| 导出格式 | **`.webapkg`**(`MANIFEST.json` + 逐文件 sha256);内容 = 项目元数据 + 图数据 + `CodeAnalysis` + 笔记 + 规划 + 完整性清单 |
| 导出执行 | 大项目是重操作 → **异步作业 + 限流** → 前端**轮询进度**、拿结果链接 |
| 导出范围 | 仅 `ctx` 权限内;**全账号导出需二次确认 + 记审计** |
| 删除前 | 可选"**先导出快照**"(前端需提供该选项) |
| 删除中 | 项目置 `deleting`,**拒绝上传 / 编辑(409)** |
| 删除后 | 换 project_ref 访问 → **404** |
| ⚠ 提示义务 | **`.webapkg` 快照在用户本地、服务端不可控** + **服务端无法删除浏览器本地数据** → 导出 / 删除页**必须写明**,并提示"请在浏览器端清理" |

---

### 19.7 本地文件访问契约（**只读实现**；写接口占位）

**会话工作区（不持久化）**

```
projects/<project_ref>/   ← 仅当前会话有效（内存优先；大项目可临时 OPFS），关闭 / 刷新即弃
├─ src/          ← 解压出的源码树（会话内可浏览；不落盘保证）
├─ .meta/        ← 文件指纹、parser_v、graph_rev（会话内）
└─ graph/        ← 图数据（会话内）
```
> **FSA 模式下** `src/` 指向用户选的目录（**仅会话内使用**，可能需重新授权）；**不做**多版本快照（`snapshots/` 已随持久化移除）。

```
projects/<project_ref>/
├─ src/          ← 解压出的源码树（原样保留 → 支持增量重解析 / 换解析器版本重算）
├─ .meta/        ← 文件指纹 (path, sha1)、parser_v、uid_rule_v、graph_rev
├─ graph/        ← 图数据分片（大项目列式缓冲）
```
> **FSA 模式下只有 `src/` 换位置**（指向用户选的目录）；`.meta/` `graph/` 仍随**会话工作区**（不持久化）。

| 接口 | 本期 | 说明 |
|---|---|---|
| `listDir(path)` · `readFile(path, {range?})` · `statFile(path)` | ✅ **实现（只读）** | 文件树 + 点开看内容；**大文件流式 / 分块**，超过预览上限（默认 2 MB）只显示头部 + 提示 |
| `writeFile` · `rename` · `deleteFile` · `watch(path, cb)` | ⏸ **仅占位（不实现、不承诺语义）** | 标注「**与语言服务器（LSP）设计一并定稿**」（主文 §6.0） |

**硬要求**

- **只读浏览跨浏览器可用**：文件树与内容查看走 OPFS/IndexedDB，**不依赖 FSA**；FSA 只影响「在系统文件管理器里能否看到 `src/`」。
- **会话态与导出**：**不做持久化**（不调用 `persist()`、不监控配额、不做快照）；**每次上传压缩包提示一次**（§6.0 ①），另有常驻导出入口与**非模态**状态提示。
- **路径安全**：解压与读取一律做「禁 `../` / 禁绝对路径 / NFKC 归一化」；**符号链接条目拒绝**。
- **LSP 阶段待定**（本契约预留）：文档版本（`didOpen` / `didChange`）、`file_path:line` ↔ `uid` 映射、浏览器内 WASM LSP vs 桌面原生 LSP。

## 20. 读懂体验契约(阅读路径 / 解释 / 进度 / 发布审批 / 嵌入 / **媒体整合 / 发现层 / 创作者认证**)（v28 新增）

> **权威源** = 主文 **§2.3**(解释层与阅读路径)+ **§6.0**(发布许可门槛与审批)。本节只给**对外契约**,不重复机制。
> ⚠ **适用范围**:**只对公开(`hosted` + `public`)项目开放** —— 私有(`local`)项目下这些端点一律 **404**(主文 §6.0(a2))。

### 20.1 端点清单

| 用途 | 方法与 URL | 关键响应字段 | 消费页面 |
|---|---|---|---|
| 锚点(读) | `GET …/anchors/?uid=&path=&commit=` | `{items:[{anchor_id,kind,uid,path,line_start,line_end,commit,state}]}` | 代码视图 / 节点侧栏 |
| 锚点(写) | `POST …/anchors/` | `{ok,anchor_id}` | 编辑器 |
| 解释(读) | `GET …/annotations/?anchor_id=&sort=adopted\|top\|new` | `{items:[{id,kind,author,body_md,source,depth,upvotes,adopted,rev}]}` | 节点侧栏 / 密度热力图 |
| 解释(写) | `POST/PUT/DELETE …/annotations/<id>/` | `{ok,id,rev}` | 编辑器 |
| 提问 / 回答 | `POST …/annotations/`(`kind=question\|answer`) | 同上 | 锚定问答 |
| **采纳**(答案 → 解释) | `POST …/annotations/<id>/adopt/` | `{ok,adopted_by}` | 项目 owner / 管理员 |
| 阅读路径(列表) | `GET …/reading-paths/` | `{items:[{id,title,target_reader,author,step_count}]}`(**★ v28:删 `health`** —— 图不可变 ⇒ **无「路径健康度」概念**,主文 §2.3.3) | 导读页 |
| 阅读路径(单条) | `GET …/reading-paths/<id>/` | `{path:{…,steps:[{order,anchor,title,body_md,why_now,what_to_notice,check,next}]}}` | 导读页 |
| 阅读路径(写) | `POST/PUT/DELETE …/reading-paths/<id>/` | `{ok,id,rev}`(★ v28:删 `health`) | 编辑器 |
| **Fork** 路径 | `POST …/reading-paths/<id>/fork/` | `{ok,new_id}` | 导读页 |
| 生成初稿 | `POST …/reading-paths/draft/` `{from:entry_points\|processes}` | `{ok,path_id}`(`why_now` 留空的半成品) | 导读页 |
| 进度(读) | `GET …/read-progress/` | `{path_id,step,read_uids,updated_at}` | 导读页 |
| 进度(写) | `PUT …/read-progress/` | `{ok}` | 导读页 |
| 解释密度热力图 | `GET …/explanation-density/?level=file\|symbol` | `{items:[{uid,path,annotations,questions,path_refs,density}]}` | 代码视图 / 图谱 |
| **嵌入**(公开只读) | `GET /api/embed/annotations/?anchor_id=` | 同「解释(读)」+ **强制字段** `license,author,source_repo,commit` | 第三方页面 |

> **写入权限与并发(对应主文 §2.3.11,权限轴与并发轴分离)**
>
> | 端点 | 谁可写 | 并发控制 |
> |---|---|---|
> | `POST …/anchors/` | 任何登录用户(且 `can_view`) | — |
> | `POST/PUT/DELETE …/annotations/<id>/` | **任何登录用户** —— **不要求 `can_edit`、不要求写者租约** | 编辑**必带 `rev`**;不匹配 → `409 stale_rev` |
> | `…/annotations/<id>/adopt/` | **项目 owner / 网站管理员** | — |
> | `POST/PUT/DELETE …/reading-paths/<id>/` | 任何登录用户可**新建**;编辑**仅限本人创建** | `rev` CAS + `owner_user_id` |
> | `…/reading-paths/<id>/fork/` | 任何登录用户 | — |
> | `PUT …/read-progress/` | **仅本人** | — |
> | **删除**解释 / 阅读路径 | **作者本人** / **项目 owner** / **网站管理员**;软删除 + `AuditLog` + 可申诉 | — |
> | `graph/sync`（**服务端解析作业唯一写入**）· `edit/`（**仅维护者图修补**） | ★ v28：**无租约**；`edit/` 限**项目维护者** | 无并发控制（图修补 **LWW + 全量审计**，主文 §2.3.12） |
>
> ★ **UGC 端点不得接入任何图写入锁** —— 图**用户不可写**（仅维护者修补）⇒ UGC 与图通道**不存在共享锁**（主文 §2.3.12 硬约束）。
>
> ⚠ **不得原地编辑他人内容**:UI **不提供**「编辑他人解释」,替代 = **并列新增**或「提议修订」(保留署名与可追责)。

### 20.2 硬约束(前端必须遵守)

| 项 | 规定 |
|---|---|
| **正文禁止内嵌大段源码** | 编辑器粘贴的代码块**超过 20 行一律拒绝**(`400` + 中文文案);展示代码一律走**锚点渲染**(主文 §2.3.1 硬约束 ②) |
| ~~**锚状态必须可见**~~ | ★ **v28 删除** —— 图不可变 ⇒ 锚**永久稳定**,`CodeAnchor` **无 `state` 字段**,不存在「可能已过时」徽章(主文 §2.3.1 硬约束 ①) |
| **`why_now` 必填** | 提交路径步骤时缺失 → `400`;`check` 选填 |
| **`source` 必须可见** | `source=ai_draft` 必须显示「**AI 草稿,未经人工确认**」 |
| **私有项目一律 404** | 上述端点对 `local` 项目**一律 404**(与「不存在」不可区分);前端**不得**为其渲染入口 |
| **嵌入必须带许可** | embed 响应**必须**含 `license` / `author` / `source_repo` / `commit`,前端**不得隐藏**这四项 |
| **UGC 写权不依赖 `can_edit`** | 解释 / 提问 / 笔记 / 阅读路径的**写入口对任何登录用户渲染**(公开项目);**不得**因「非协作者」而隐藏(主文 §2.3.11 通道②③) |
| ★ **私有项目也渲染 UGC 入口（本轮新增）** | **`local`（私有）项目同样渲染**解释 / 提问 / 阅读路径的写入口 —— 产物**只落本地**（`local_annotation` / `local_path`），**写路径必须零网络请求**（H5；抓包断言）。⚠ **引导文案**：「**你写的解释只存在本机；想让大家看到，需要一个已公开的项目**」—— **不得**说「私有项目不能写」 |
| **`rev` 必带** | 编辑**自己的**条目必须回传 `rev`;收到 `409 stale_rev` → 提示「**已被他人修改,请刷新后合并**」,**不得静默重试覆盖** |
| **不得原地编辑他人内容** | UI **不提供**「编辑他人解释」;替代 = **并列新增** 或「提议修订」(保全署名与可追责) |
| **删除入口可见性** | 删除按钮**仅对作者本人 / 项目 owner / 网站管理员**渲染;删除为**软删除 + 可申诉** |
| **游客只读** | 未登录用户**不渲染任何写入口**;写请求 → `401` |
| **UGC 限流必须可读** | UGC 写被限流 → `429` + `Retry-After`(§8.1 统一口径)+ 「操作过于频繁,请 N 秒后重试」 |

### 20.3 发布审批契约(对应主文 §6.0(a1))

> **默认是「自动放行」** —— 三车道:**A 自动放行**(秒级,不用人工)/ **B 自动拒绝**(秒级,可申诉)/ **C 人工**(**只兜不确定**,预期 ≤5%)。

| 动作 | 端点 | 说明 |
|---|---|---|
| ★ **请求建立快照（本轮语义变更）** | `POST /api/projects/<project_ref>/publish/` | body `{declare_rights: true, provider, source_repo, commit, license_spdx?}` —— ★ **provider + source_repo + commit 为必填**（公开 = 请求服务端**去托管平台拉取**，H6）；provider 枚举 = github / gitee；`declare_rights` 不为 `true` → **400**（权利人声明，Gate 1）；★ **不接受任何「上传源码」字段**（H6） |
| 查询状态 | `GET …/publish/status/` | `{state: local \| public \| rejected \| pending_review \| taken_down, lane?: "A"\|"B"\|"C", reason?, license_spdx?, sla_until?, queue_position?, reviewed_at?}` |
| 撤回申请 | `DELETE …/publish/request/` | 仅 `pending_review` 可撤 → 回 `local` |
| 申诉 | `POST …/publish/appeal/` `{reason}` | 仅 `rejected` 可申诉 → 转人工(C 车道) |
| 举报侵权 | `POST /api/report/` `{project_ref, anchor_id?, reason}` | 每页提供入口;处理走同一状态机 → `taken_down` |

**前端义务**

- **A 车道必须「无感」**:自动放行是**秒级**结果 —— `public` 直接生效,**不得**再显示「审核中」或进度条(否则用户会以为在排队);
- **B 车道必须可读**:`rejected` 必须显示**具体原因**(如「未在仓库根找到许可证文件」)+ **申诉入口**;
- **C 车道必须可见且有预期**:显示「**待管理员审核**」+ **`sla_until` 倒计时** + **队列位置** + **撤回申请**;
- **过闸不阻塞学习**:提交公开申请后,本地解析 / 图 / 解释 / 阅读路径**照常可用**,仅对外不可见;
- **后续同步不显示审核态**:同一项目 `LICENSE` 未变更时,**同步不得再触发 `pending_review` UI**;
- **`taken_down` 与 `rejected`** 一律不得展示公开内容,前端必须立即清除本地缓存视图;
- ⚠ **`local`(私有)项目不提供任何公开入口**(主文 §6.0 H2)—— 现有 `is_public` 开关对 `local` 项目**必须隐藏**。

### 20.4 客户端义务补充(并入 §19)

| 项 | 规定 |
|---|---|
| ★ **UGC 的两种落点（本轮重写）** | **公开项目** → 写入口渲染，产物落**服务端**（条目级 `rev` CAS）；**私有项目** → 写入口**同样渲染**，产物**只落本地**（`local_annotation` / `local_path`，IndexedDB / OPFS，**零网络**）。⚠ **两者的入口 UI 必须可区分**（服务端 / 本机），避免用户误以为「已经发布了」 |
| **私有项目 UGC 的持久化** | **落本地即持久**（关闭浏览器不丢，H5）—— 不再显示「仅本次会话」；⚠ **但登出 / 删除项目必须清本地**（§19.1 硬要求）⇒ **登出前必须提示导出**（见下条） |
| ★ **登出 / 删项目前的数据保全（本轮新增）** | 若存在**未导出的本地 UGC**（解释 / 提问 / 阅读路径），**必须在登出 / 删除前弹出确认**：「你有 N 条本地笔记，退出后将**无法恢复**。建议先**导出 `.webapkg`**」→ 用户可选「先导出」/「仍要退出」。⚠ **不得静默清除**（那是「用户白写」的真实来源） |
| **会话态引导(三选一)** | 文案统一为「① 学习**公开项目** ② 导出 `.webapkg` ③ 等待**桌面客户端**」(主文 §3.3 / §6.0) |
| **客户端等待名单** | 提供留邮箱入口(主文 §3.4) |

### 20.5 媒体卡片契约(外部整合;对应主文 §2.3.14)

> ★★ **新项目补充（`B137` / `B140` · `USERS-AND-AUTH.md` U9.7 / U9.9 ⑤）**：
> ★★ **付费项目里的媒体卡片必须单独成「附录」，且对所有人免费** ——
> ★ 且**必须标注该链接的收费状态**（`免费` / `需要付费` / `需要登录`）。
> ⚠ 这是「**锁讲解、❌ 不锁外部内容**」原则的落地；★ **本节已有的六条硬要求继续有效，无需改动。**

> ★ **定位**:内容在外部平台,**本平台只存指针与署名** ⇒ **默认行为是「跳转」**。
> ⚠ **一期不实现站内播放**(`embed_allowed` **恒 `false`**;主文 §2.3.14:**理由不是带宽,而是法律与共赢**)。

| 动作 | 端点 | 说明 |
|---|---|---|
| 媒体(读) | `GET …/media/?anchor_id=` | `{items:[{id,kind,provider,url,t_start,t_end,title,note,cover,embed_allowed,license_status,state,rev,attribution{source_platform,author,source_url}}]}` |
| 媒体(写) | `POST/PUT/DELETE …/media/<id>/` | **任何登录用户**(§2.3.11 通道③);条目级 `rev` CAS;**署名三字段缺一 → `400`** |
| 报告失效 | `POST …/media/<id>/report_dead/` | → `state=dead` + 记审计 |
| **卡片分享 / embed** | `GET /api/embed/media/?anchor_id=` | 同「媒体(读)」+ **强制字段** `license,source_platform,author,source_url` |

**硬要求(前端必须遵守)**

| 项 | 规定 |
|---|---|
| **默认跳转,不内嵌** | `embed_allowed=false`(**一期恒此**)→ **只渲染跳转卡**;**不得**自行 iframe 内嵌(M1) |
| **署名三项必须可见** | `source_platform` / `author` / `source_url` **必须显示且可点击**,**不得隐藏、不得折叠**(M2) |
| **跳转带回流标识** | 跳转 URL **必须**附加**匿名**来源标识(如 `?from=<本站域名>`);⚠ **不得带任何用户标识**(PIPL / GDPR) |
| **不复制正文** | 文章类**只显示 `note`(作者自写一句话)**;**不得**拉取 / 展示原文摘要或正文(M3 / M7) |
| **失效必须显式** | `state=dead` → 「**原内容已失效**」;⚠ **解释正文与代码锚点照常渲染**(M5) |
| **时间戳可能失准** | 显示「**该时间点可能已失准,请确认**」;**不得静默当作准确** |
| **封面(★ v28 定稿)** | **只有两档**:`generated`(**系统生成**,默认)/ `none`(占位卡);⚠ **禁止用户上传封面、禁止自动抓取对方封面、禁止使用对方官方 logo 图片**;**来源标识只用文字平台名**(M10) |
| ★ **平台不托管任何用户上传媒体** | ⚠ 前端**不得**提供"上传视频 / 图片 / 音频"的入口 —— 视频 / 文章 / 示意图**一律只填外部链接**(M10);封面**由系统按 `anchor` 哈希确定性生成** |
| **`kind` 决定模板** | `video` → 封面 + 时长 + `▶ mm:ss`;`article` → 标题 + `note` + 作者;`diagram` → 图 + 说明 |
| **平台定性必须可见** | 媒体卡片区**必须**显示「**内容托管于第三方平台,本平台仅提供锚定与跳转**」(M9 第 ① 条) |
| **署名未核实声明** | 未认证创作者**必须**显示「**署名由提交者填写,平台未做核实**」(避风港关键) |
| **举报入口** | 每张卡片提供**报告**(①侵权 ②**署名错误 / 冒名** ③**已失效**)三个理由 |
| **不做广告** | ⚠ **外部引用卡片周边不得投放广告**(M9 第 ④ 条 —— 否则**丧失避风港**) |

### 20.6 发现层与创作者契约(对应主文 §2.3.15)

| 动作 | 端点 | 说明 |
|---|---|---|
| 发现流 | `GET /discover/?cursor=&limit=` | `{items:[CodeCard], next_cursor}`;⚠ **有边界**(`limit` 服务端夹取),**不得做成无限流** |
| 关注 / 取关 | `POST/DELETE /api/follows/` body `{target_kind,target_id}` | `target_kind ∈ {user, project, path}` |
| 我的关注流 | `GET /api/follows/feed/` | 关注对象的**新解释 / 新阅读路径** |
| 创作者面板 | `GET /api/creator/stats/` | `{adopted, readers, questions, media_refs, attribution_clicks}` |
| 认领媒体 | `POST …/media/<id>/claim/` | 凭**来源账号验证**认领署名 → `claimer_user_id` + 显示「**已认证创作者**」 |
| 卡片分享 | `GET /api/share/card/?anchor_id=` | 只读卡片;⚠ **必须带 `license` / 作者 / 来源仓库**(与 §20.2 同规) |

**硬要求(前端必须遵守)**

| 项 | 规定 |
|---|---|
| **`path_ref` 必填** | 发现流里**每张卡片必须能跳进某条阅读路径**;**不得出现「无归属的卡片」**(防碎片化焦虑) |
| **不按停留时长排序** | 推荐主信号 = **被路径采纳 + 完成率**;**不得**把停留时长当正向信号(代码场景中"卡住"是**负向**信号) |
| **「提问数」是正向信号** | 困惑度 = 价值;可用于渲染「**这里很多人问过**」提示 |
| **卡片必带署名与许可** | 分享卡片**不得隐藏** `license` / 作者 / 来源仓库 |
| **不渲染站内播放** | 卡片里的媒体一律**跳转卡**;**不得**渲染播放器 |

### 20.7 第三方身份与归属验证契约(对应主文 §6.0(a1) **Gate 0** / §2.3.14)

| 动作 | 端点 | 说明 |
|---|---|---|
| 发起绑定 | `GET /api/creator/oauth/<provider>/start/?next=` | 302 → 平台授权页;**最小权限 scope** |
| 回调 | `GET /api/creator/oauth/<provider>/callback/` | `{ok, provider, provider_login, verified_at}` |
| 我的绑定 | `GET /api/creator/identities/` | `{items:[{provider,provider_login,verified_at,scopes}]}` |
| 解绑 | `DELETE /api/creator/identities/<provider>/` | ⚠ 解绑后 **Gate 0 失效** → 撤销「已认证」标记(**不自动下架**已有公开内容) |
| 归属校验 | `POST /api/creator/verify-ownership/` `{provider, repo}` | `{verified: bool, fork: bool, parent?: "owner/repo"}` |
| 认领媒体 | `POST …/media/<id>/claim/` | **必须 Gate 0 通过** |
| 创作者主页 | `GET /api/creator/<user_id>/` | 聚合该身份的**全部内容**(repo / 视频 / 文章)+ 回报面板 |

**硬要求(前端必须遵守)**

| 项 | 规定 |
|---|---|
| **最小权限** | ⚠ 前端**不得**请求超出 `read:user` 的权限;**不得**提供「读取私有仓库」的绑定入口 |
| **不阻塞创作** | ⚠ **写解释 / 提问 / 阅读路径一律不得要求绑定** —— 绑定入口**只出现在「发布源码 / 图谱」与「认领署名」两个流程中** |
| **未绑定必须标注** | 未绑定 → **必须显示**「**署名由提交者填写,平台未做核实**」 |
| **Fork 必须标注** | `fork=true` → 卡片 / 项目页**必须**显示「**Fork 自 `owner/repo`**」;**不得按原创展示** |
| **文案不得夸大** | ⚠ **不得**写「已验证版权」—— 只能写「**已验证账号归属**」(**归属 ≠ 版权**) |
| **B 站绑定不用于放行** | ⚠ **不得**因「已绑定 B 站」而开放「发布源码 / 图谱」入口(UP 主可能是**转载者**) |
| **外部卡片页零商业化** | ⚠ 外部媒体卡片页**不得**放广告 / 会员入口 / 推广位 / 导流分成(保避风港) |

## 21. 本轮同步的未决项(需评审裁决,勿自行拍板)

| # | 未决项 | 现状与依据 | 影响 |
|---|---|---|---|
| 1 | **两条破坏性变更的终点未定**:限流 `401 → 429`、`account_locked` / `weak_password` 不再返回 | 后端文档给了**新语义**,**没给**"是否新开 `/api/v2/…`"与"旧路径保留到何时"(M5 要求 ≥90 天且 ≥2 个发布) | 见 §14 登记表末两行;**裁决前不得实施** |
| 2 | **软删除后读接口的可见性**:删除的节点 / 边是否仍出现在 `graph/nodes` / `graph/edges`,`dangling` 口径如何 | 附录 D5.2 只定义了**写入侧**墓碑(§17.5 已标注) | 前端过滤策略;裁决前按"服务端返回什么就渲染什么 + 本地 `lifecycle` 兜底" |
| 3 | **WebSocket 频道层订阅契约缺失**:频道名 / 订阅键规则 / 消息结构 / 鉴权 | 主文 §8.2 只说了 `ch:` 前缀与"LSP/终端消费端",**无对外订阅契约** | 实时功能无法按契约编码(§19.5) |
| 4 | **`graph/edges/` 由 `offset` 改为 `cursor` 的兼容期** | 目标(§18.1)不再用深分页 offset;`cursor` 属新增参数,但**旧的 `offset` 何时可删未定** | 属 §14 登记表的弃用时间表缺口 |
| 5 | **`graph/nodes/` 是否也要 `cursor` 化** | D8.2 只覆盖 `graph/edges/` 与跳数查询 | 影响列表页分页实现(§18.3 最后一行为当前口径) |
