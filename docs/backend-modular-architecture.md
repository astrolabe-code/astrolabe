# 后端模块化架构(v28 · 12 模块 + 4 张 P0 表)

> **定位**:本文是**结构层**的权威文档 —— 回答"精简之后,各块怎么独立演化、独立失效、独立测试"。
> **依据**:用户第十轮评审建议《模块化设计:可以,而且应该做》(见 `backend-decisions.md` **B81**);与 `backend-design.md`(主文 v3.42 · 评审稿 v27)**同一批次**。
> **边界(必须先读)**:**模块化解决"耦合与维修",不解决"机制过多"** —— 机制过多由 v27 减法解决(见 `B79`/`B80`)。
> **顺序(写死)**:**先减法 → 再收敛状态 → 再模块化 → 最后扩展**。跳过前两步直接模块化 = 把冗余机制固化进接口。

---

## 1. 模块化原则(五条)

| # | 原则 | 含义 |
|---|---|---|
| 1 | **每个模块只暴露一个接口面** | 外部只能调接口;**不能读模块内部状态、不能直接操作模块的表** |
| 2 | **模块内部状态不可跨模块访问** | A 不能查 B 的表;A 要 B 的数据**走 B 的接口** → B 换实现/换表结构,A 不受影响 |
| 3 | **跨模块只通过接口或事件** | 同步写 = 接口调用;异步通知 = 事件(outbox / 消息);**禁止共享事务跨模块**(唯一例外见 §4.1) |
| 4 | **模块可独立失效** | 一个模块挂了,其他模块**降级或拒绝**,不是整站雪崩 |
| 5 | **模块可独立测试** | 每模块自带测试集,用 mock 接口,**不依赖其他模块的真实实现** |

---

## 2. 模块划分与依赖方向

```
接入层  HTTP API / WebSocket / 静态资源
   │
身份与权限(auth)  →  项目(project)
   │                      │
   ├──────────────────────┼── 同步(sync)
   │                      │
   ├── 图数据(graph) ─────┼── 搜索(search) ── 解析(parse)
   │                      │
   └── 审计(audit) ── 限流(ratelimit) ── 删除(deletion) ── 导出(export) ── 可观测(observability)
   │
基础设施层  PG / PG / OpenSearch / Redis / 磁盘  ·  Job(作业注册中心)  ·  AppSetting(配置中心)
```

**依赖方向**:`接入层 → 模块 → shared / infra`;模块之间**单向**、**无环**。

---

## 3. 模块清单(12)

> 每模块四要素:**职责 / 接口 / 边界 / 依赖**。接口签名是**契约**,实现可换。

### 3.1 身份与权限 `auth`

- **职责**:登录/登出/会话;**`can_view` / `can_edit`**;向上层提供 **`AuthCtx`**。★ **v28:`writer_token` / `DeviceSession` 已删除**(图不可变 ⇒ 无「写权身份」;登录身份由既有 session 承载,主文 §4.1.2)。
- **接口**:
  ```
  authenticate(request) -> AuthCtx | 401
  can_view(ctx, project_ref) -> bool
  can_edit(ctx, project_ref) -> bool
  ```
- **边界**:不操作图数据 / 项目元数据 / outbox。**依赖**:PG(`User` / 会话)。

### 3.2 项目 `project`

- **职责**:项目 CRUD;`project_ref` 生成与唯一性;元数据(`visibility` / `graph_rev` / `graph_sync_status ∈ {ok | degraded | deleting}`);**删除入口**(只触发删除作业);提供项目上下文。
- **接口**:
  ```
  create_project(user_id, name) -> project
  get_project(project_ref) -> project | 404
  update_project(project_ref, fields) -> project
  delete_project(project_ref) -> job_id
  resolve_project(project_ref) -> project | 404
  ```
- **边界**:不写图 / 不写 outbox / 不消费 outbox。**依赖**:PG(`Project`)· 删除模块。

### 3.3 ~~写者租约 `lease`~~(★ v28 已整体删除)

> ★ **v28 删除**:「图不可变」(主文 §2.3.12)⇒ **无客户端写者** ⇒ **本模块整体取消** —— `ProjectWriterLease` / `lease_epoch` / 抢租约 / 续租 / 接管 / 回收 / 校验 **均不再存在**。
>
> **替代**:服务端解析作业的串行由**现成 `Job.dedup_key(KIND_PARSE, "proj:<ref>")`** 承担(主文 §5.3)。**模块数 13 → 12**。

### 3.4 同步 `sync`

- **职责**:接收**图快照提交**(★ v28:**无租约、无 `base_graph_rev` 协商**);**`parse_hash` 幂等**(已存在 → 直接返回既有 `project_ref`);**分配 `graph_rev`(每项目单调)**;**同一 PG 事务**写图数据 + 写 outbox + 推进 `graph_rev`;outbox 消费调度。
- **接口**:
  ```
  sync_upload(project_ref, ctx, payload) -> result
  ```
- **边界**:**不直接写 PG / OpenSearch**(交 outbox 消费者);不判权限(用 `auth`)。
- **依赖**:PG(`graph_node` / `search_outbox` / `Project.graph_rev`)· 身份模块。

### 3.5 图数据 `graph`

- **职责**:图节点/边的**读写与邻域查询**(PG `graph_node`/`graph_edge`);**1–2 跳**走索引 + 递归 CTE(附录 D1.4);**>2 跳与图算法**转 `accelerator`(§4.5);软删除语义(`lifecycle`)。
- **接口**:`put_node(project_ref, uid, data)` / `put_edge(...)` / `delete_node(project_ref, uid)` / `delete_edge(...)` / `get_node` / `query_neighbors(project_ref, uid, hops, filters) -> nodes`。★ 本轮**删除 `vid_op_rev` 形参**（图不可变 ⇒ 无版本守卫语义）
- **边界**:不判权限(注入 `project_ref`);**不承担跨库同步**(图与元数据同库同事务);**不承担检索**(走 `search`)。
- **依赖**:PostgreSQL;(深分析) `accelerator`。

### 3.6 搜索 `search`

- **职责**:检索索引读写(**OpenSearch**,一期即部署);检索滥用防护。
- **接口**:`index_node` / `delete_node` / `search(project_ref, query, limit)` / `rebuild_index(project_ref) -> job_id`
- **边界**:不判权限(注入 `project_ref`);不操作图数据。**依赖**:OpenSearch / PG。

### 3.7 解析 `parse`

- **职责**:服务端解析管线(公开/协作/超大项目);**派生作业**(`CodeAnalysisDerived`)也归本模块;解析产物**经图数据模块写入**;作业调度。
- **接口**:`submit_parse(project_ref, source_path) -> job_id` / `get_parse_status(project_ref) -> status` / **`submit_derive(project_ref, graph_rev) -> job_id` / `get_derive_status(project_ref) -> status`**(v27:派生卷入本模块,见 §14.2)
- **边界**:不直接写 PG / OpenSearch;不判权限。**依赖**:图数据模块 · 搜索模块 · PG(`Job`)。

### 3.8 审计 `audit`

- **职责**:**单表 `AuditLog`**;访问控制;归档前匿名化;**安全事件保留完整语义**。
- **接口**:`audit(event_type, actor, target, detail)` / `query_audit(filter)` / `archive_audit(before_date) -> job_id`
- **边界**:不操作业务表;不参与权限判定。**依赖**:PG(`AuditLog`)。
- **⚠ 口径以权威为准**:"安全事件明细**永不抽样**、配额收紧时**优先拒绝非安全事件**"的容量口径见 `backend-tenancy-security.md` §B7(**唯一权威**)—— **本模块不自定"限流或不限流"**。

### 3.9 限流 `ratelimit`

- **职责**:**Redis 计数 + 本地内存降级 + 账号锁定**;统一 **`429 + Retry-After + rate_limited`**;IP 为主、`dev_id` 二级;**认证链路 fail-closed,读链路 fail-open**。
- **接口**:`check_rate(key, policy) -> allowed | 429` / `hit_rate(key, policy)`
- **边界**:不操作业务数据;不判权限。**依赖**:Redis · PG(账号锁定)。
- **⚠ v27 已知取舍**:Redis 与进程**同时**重启的窗口内,限流只剩本地内存 + 账号锁定(见 `B79`)。

### 3.10 删除 `deletion`

- **职责**:删除作业调度;**九步删除流程**;**`Job` 表记录进度**(`Job.state` + `Job.payload.step`);**中断可重入**。
- **接口**:`submit_deletion(project_ref) -> job_id` / `get_deletion_status(job_id) -> status`
- **边界**:**只调度** —— 不直接删图(调 `graph`)、不直接删索引(调 `search`)、不直接删元数据(调 `project`)。**依赖**:`Job` · 图数据 · 搜索 · 项目 · 审计。
- **⚠ 写死**:进度记录在 `Job` 行上,**该作业行不随项目删除**(必须把"删除作业自身"排除在"按项目删除"之外)。

### 3.11 可观测 `observability`

- **职责**:指标采集 / 告警 / 日志。
- **接口**:`emit_metric(name, value, tags)` / `emit_alert(level, name, detail)`
- **边界**:**只读其他模块的公开指标**;不介入业务逻辑。**依赖**:监控后端。

### 3.12 导出 `export`(模块 12 · 用户裁定独立)

- **职责**:项目**导出**(`.webapkg`)与**快照**生成/校验;导出授权判定;长任务、读密集、**独立失败域**。
- **接口**:
  ```
  submit_export(project_ref, scope, ctx) -> job_id
  get_export_status(job_id) -> status
  build_snapshot(project_ref, graph_rev) -> snapshot_ref
  ```
- **边界**:**只读** `graph` / `search` / `project` 的查询接口与元数据;**不写任何业务表**;唯一写 `Job(kind=export)`;不直读磁盘源码(经 `project.source_path` + 路径安全校验)。
- **依赖**:`graph` · `search` · `project` · `auth`(授权)· `audit`(记审计)· `Job`。
- **为什么独立**:与 `deletion`(清数据,要求"数据消失")**语义相反**,合并会让同一模块同时承担"保证数据完整"与"确保数据清除"两个冲突目标;**且导出是长任务**,挂掉不应影响写路径与删除(见 §12 降级矩阵、§14.1)。

---

### 3.13 加速器 `accelerator`(模块 13 · v28 新增)

- **职责**:承接 **>2 跳遍历与图算法**(环检测 / 度统计 / 将来的 Louvain / PageRank / 最短路)。**非权威、可随时重建**(丢了从 PG 重灌)。
- **鉴权(前置,第一步)**:`require_grant(user_id) -> bool` —— **管理员授权制**(主文 §4.5(a0));未授权 → `403 graph_analysis_not_authorized`,**不进队列、不导入**。
- **接口**:`request_analysis(project_ref, kind, args) -> job_id` · `get_analysis_status(job_id)` · `get_analysis_result(job_id)` · `ensure_subgraph(project_ref, graph_rev)` · `evict(project_ref)` · `release(project_ref)`。
- **调度**:项目亲和优先 → 版本不符重导 → 负载最低 → 内存水位先驱逐 → 心跳超时重排;**分片键 = `project_ref`**。
- **释放**:主动释放 / 心跳超时(180s)/ 空闲释放(15min)/ 硬上限(60min)。
- **授权存储**:`accelerator_grant`(用户维度授权 + 可选配额)
- **存储**:`accelerator_node`(池成员) · `accelerator_assignment`(项目亲和) · `graph_analysis_result`(结果缓存)。
- **边界**:**不判权限**(注入 `project_ref`);**不落业务数据**;结果一律写回 PG。
- **依赖**:PostgreSQL(子图来源 + 结果落位)、Redis(队列);Neo4j Community(算力)。

## 4. 跨模块契约(四条流程)

### 4.1 同步上传

```
接入层 → auth.authenticate
      → project.resolve_project
      → auth.can_edit
      → lease.verify_lease
      → sync.sync_upload
            ├─ 分配 graph_rev(每项目单调)
            ├─ 同一 PG 事务:写图数据 + 写 outbox + 推进 graph_rev
            └─ graph.put_node / put_edge
      → 返回结果
```

**关键**:**这是全系统唯一允许的跨模块共享事务**(`sync` × `graph`),且**必须显式声明**;其余任何跨模块写都禁止共享事务。

### 4.2 检索索引同步(`search_outbox`)

- **写侧**:图事务提交时**同事务**插入 `search_outbox`(`uid` / `op` / `graph_rev`)。
- **消费侧**:单消费者**串行**;`graph_rev` 版本守卫(跳过更旧);成功即删行;超 N 次 → `dead`(**不阻塞水位**) + 审计。
- **一致性**:最终一致;`index_lag`(版本差)见主文 §5.5;周期 `reconcile` + `rebuild_index(project_ref)` 兜底。

### 4.3 删除

```
project.delete_project → deletion.submit_deletion
   → project: 置 deleting
   → sync:    停消费
   → graph:   删图(PG 按 project_ref)
   → search:  删索引(OpenSearch 按 project_ref)
   → project: 删元数据(+ graph_node / search_outbox / Job)   ← ★ v28:租约表 / 同步状态表已删
   → 磁盘:    删源码(先 realpath 前缀断言)
   → audit:   脱敏 + 记审计
   → Job:     标记完成(删除作业行本身最后处理)
```

### 4.4 读路径

```
接入层 → auth.authenticate → project.resolve_project → auth.can_view
      → graph.query_nodes / query_edges
      → search.search
```

**关键**:`project_ref` 由身份/项目模块**注入**,`graph` / `search` **不判权限**;读路径**不返回** `lifecycle='deleted'`、**不阻塞** outbox、**不触发**恢复。

---

## 5. 边界规则

### 5.1 允许

| 跨模块行为 | 说明 |
|---|---|
| 接口调用 | A 调 B 的**公开接口** |
| 事件通知 | A 发事件,B 订阅(outbox / 消息) |
| `sync` × `graph` 共享 PG 事务 | **唯一例外,显式声明** |
| 读取他模块公开指标 | 只读 |

### 5.2 禁止

| 跨模块行为 | 说明 |
|---|---|
| 直接查他模块的表 | 必须走接口 |
| 直接改他模块的状态 | 必须走接口 |
| 跨模块共享事务(除 §4.1) | 避免隐式耦合 |
| 模块间循环依赖 | A 依赖 B,B 不能依赖 A |
| 共享可变全局状态 | 禁止 |

---

## 6. 模块化收益(验收方向)

1. **可独立替换**:`graph` 换图实现、`search` 换检索后端、`ratelimit` 换实现 → 上层无感。
2. **可独立失效**:`search` 挂 → 读路径降级到 PG,不影响同步;`ratelimit` 的 Redis 挂 → 认证 fail-closed 到本地、读 fail-open;`audit` 挂 → 业务不受影响 + 告警。
3. **可独立测试**:每模块自带测试集;单测用 mock 接口;集成测试**只测跨模块契约**。
4. **可独立演化**:`graph` 加查询不影响 `sync`;`audit` 改归档不影响业务;`parse` 加语言不影响他人。
5. **维修边界清晰**:先定位模块;模块内状态自洽;回滚只回滚单模块。

---

## 7. 共享内核(不可拆 · 五项)

> 这些**必须保持单一权威**,不能各模块各写一份。

| # | 共享项 | 纪律 |
|---|---|---|
| 1 | **VID 计算** | 两端 **bit-exact**;必须是**共享参考实现 + 测试向量**(`shared/vid.py`);固定 **`sha256_16`** |
| 2 | **图快照 + outbox 原子性** | `sync` × `graph` 的写**必须在同一 PG 事务**(唯一例外) |
| 3 | **权限注入** | `ctx.project_ref` 必须由 `auth` / `project` 注入;`graph` / `search` **必须接受注入,不得自行判定** |
| 4 | **软删除语义** | `lifecycle` 是图数据核心语义,**不能由上层模块自行实现**(★ 本轮删 `vid_op_rev`) |
| 5 | **审计格式** | `AuditLog` 字段统一,**不能各模块各写一套** |

---

## 8. 实施路径(写死顺序)

**阶段 0 · 先减法**(= v27 已定稿,见 `B79`/`B80`):
1. 删哈希迁移全链(固定 `sha256_16`)2. 删多标签页仲裁(`page_seq` / `PageSequence` / `PageAssignment`)3. 删 `AuthRateCounter` / `AuditSecurityDetail` / `ProjectDeletion` 4. 收敛状态(`graph_sync_status` 3 态、outbox 3 态)   ← ★ v28:fencing / 租约已删5. 固定 VID 算法。

**阶段 1 · 再模块化**(抽出顺序):
1. 先抽 `auth` / `project` → 2. 再抽 `graph`(**先用 PG 图表实现**)→ 3. 再抽 `sync` / `audit` / `ratelimit` → 4. 再抽 `deletion` / `observability` → 5. 最后抽 `search` / `parse` / **`export`(模块 12)**。

**⚠ 不必一次拆完**:**首批只落 `auth` / `project` / `graph` 三个模块**(见 §14.7);其余按需逐个抽出。

**阶段 2 · 扩展期**:规模调优(三存储 + 加速器**已在一期部署**);`graph` 的 PG 实现与 `search` 的 OpenSearch 实现自一期即启用,模块接口不变。

---

## 9. 目录结构与依赖纪律

```
src/
  modules/
    auth/          # 身份与权限
      api.py service.py models.py tests/
    project/       # 项目
    sync/          # 同步
    graph/
      interface.py pg_impl.py
    search/        # 搜索
    parse/         # 解析
    audit/         # 审计
    ratelimit/     # 限流
    deletion/      # 删除
    observability/ # 可观测
  shared/
    vid.py         # VID 共享参考实现 + 测试向量
    contract.py    # 跨模块契约类型
    errors.py      # 统一错误码
  infra/
    pg.py opensearch.py redis.py
```

**规则(CI 可 lint)**:
- `modules/*` **只能**依赖 `shared/*` 与 `infra/*`;
- `modules/*` 之间**只能通过接口**依赖;
- **禁止** `modules/a` 直接 `import modules/b/models.py`。

---

## 10. 表归属矩阵(P0-1)

> **v28 新增归属**:`graph_node` / `graph_edge` → 模块 **`graph`**(唯一写者 = `sync` 上传事务);`search_outbox` → 模块 **`search`**(写者 = `sync`,与图事务**同一事务**写入);`accelerator_node` / `accelerator_assignment` / `graph_analysis_result` → 模块 **`accelerator`**(写者 = 调度器与 worker)。

> **规则**:每张表**只有一个写者模块**;其他模块**只读**(或不读)。跨模块直查/直写 = 缺陷(见 §5.2)。
> **基础设施层两张共享表**:`Job`(作业注册中心)、`AppSetting`(配置中心)—— 归 **infra**,各模块只经接口访问。

| 表 | 唯一写者 | 只读模块 | 备注 |
|---|---|---|---|
| `User` / 会话 | `auth` | `project`(判归属) | — |
| `Project` | `project` | `sync` · `graph` · `search` · `parse` · `deletion` · `export` | ⚠ **唯一例外**:`graph_rev` 的推进由 `sync` 在 §4.1 的**共享事务**内写,属**显式声明**的例外 |
| `graph_node` / `graph_edge` | `sync` | `graph`(VID → 数据)、`parse` | **PG 图数据表**(权威);`graph_node.last_graph_rev` = **消费水位**(供恢复反查,附录 F2 步骤 3) |
| `search_outbox` | `sync` | `deletion`(只整体清空) · `observability`(只读指标) | 消费者**只经 `sync` 接口**推进 `state`/`attempts` |
| `edge_type_count` | `sync` | `graph` | 由 outbox 消费侧更新 |
| `CodeAnalysis` | `parse` | `graph` · `search` · 读路径 | **唯一写者 = 解析/派生管线** |
| `CodeAnalysisDerived` | `parse`(派生作业) | 读路径 | `based_on_graph_rev` |
| `Job` / `WorkerNode` | **infra 作业注册中心** | 全部模块(只经接口) | `kind` 取值:解析 / 派生 / 图同步消费 / 删除 / 导出 / 备份 / 恢复 / 归档 / 清理 / 回收 |
| `AppSetting` | **infra 配置中心** | 全部模块(只经 `get_setting`) | 如 `auto_publish_oss` / `third_party_publish` |
| `AuditLog` | `audit` | 运维(归档导出) | **单表**;归档前匿名化 |
| 项目权限 / 笔记 / 规划 | `project` | `auth`(只读判权) | 属"项目元数据域",随项目删除 |
| **PG 图** 顶点/边 | `graph` | `search`(无关) · 运维 | **图的存储与读权威**;**一期即部署**(无 PG 图过渡表) |
| **OpenSearch** 索引 | `search` | 读路径(检索) | **可重建、非权威**;**一期即部署** |
| **Redis** 键空间 | `ratelimit`(计数) · `sync`(门禁标志) | `observability`(只读指标) | **非权威、可重建**;不得承载唯一业务数据 |

---

## 11. 事件契约(P0-2)

> **v28 新增事件**:①`graph_analysis.completed`(`project_ref` / `graph_rev` / `kind` / `args_hash` / `job_id` / `result_ref`)—— **至少一次**、消费幂等(键 `(project_ref, graph_ref, kind, args_hash)`);②`search_outbox.drained`(检索索引追平,用于 UI 收起"索引整理中"提示)。

> **载体**:异步一律走 **`search_outbox`(图/检索变更)** 或 **`Job`(作业状态)**,不引入消息中间件。
> **投递语义**:**至少一次(at-least-once)** + **消费端幂等**;不做 exactly-once。

| 事件 | 产生模块 | 载体 | payload(关键字段) | 幂等键 | 失败处置 |
|---|---|---|---|---|---|
| **图/检索变更** | `sync` | `search_outbox` | `project_ref` · `graph_rev` · `uid` · `op` · `payload` | **`(project_ref, uid)` 唯一行**(单目标、无 `target` 列;★ v28 统一口径,主文 §4.1) | 指数退避重试,超 N 次(默认 8)→ `dead` + 人工(§A5.1);**`dead` 不阻塞派生** |
| **消费 ack / 水位推进** | `graph` · `search` 消费者 | 回写 `graph_node.last_graph_rev` | `project_ref` · `vid` · `last_graph_rev` | `(project_ref, vid)` | 回写失败 → 下次恢复按水位重放(幂等) |
| **项目删除** | `project` → `deletion` | `Job(kind=project_delete)` | `project_ref` · `step` · `step_at` | `Job` 主键 | 失败置 `failed` + **重入读 `payload.step` 续跑** |
| **解析完成** | `parse` | `Job(kind=parse)` | `project_ref` · `graph_rev` | `(project_ref, graph_rev)` 复用既有 `Job` 行 | 指数退避 + `attempts` 上限 |
| **派生完成** | `parse`(派生作业) | `Job(kind=derived)` | `project_ref` · `graph_rev` · `derived_kind` | **`dedup_key = (project_ref, graph_rev, derived_kind)`** | 同上;同一图版本重复触发**复用** |
| **导出完成** | `export` | `Job(kind=export)` | `project_ref` · `artifact_ref` | `(project_ref, job_id)` | 可重试(**导出幂等**) |
| **审计归档完成** | `audit` | `Job(kind=archive)` | `before_date` · `rows` | `(before_date)` | 重试 + 告警 |

**消费者幂等口径（★ 本轮重写）**：★ **原「`FETCH` 当前 `vid_op_rev` → `incoming > current` 才写」整体删除** —— 图不可变 ⇒ 同一 `(project_ref, uid)` **只写一次**，**不存在「陈旧写」**（也就没有 `outbox_stale_dropped` 这个事件）。
改为：**消费者幂等 = 写入语句本身幂等**（`INSERT … ON CONFLICT (project_ref, uid) DO NOTHING`）+ **`search_outbox` 成功即删行**（唯一约束 `UNIQUE(project_ref, uid)`）⇒ **重复消费天然安全**；**仍然禁止**用物理插入顺序 / 自增 id / 创建时间排序。

---

## 12. 降级矩阵(P0-3)

> 对应原则 4「可独立失效」:任一模不可用时,**明确"拒绝还是降级"**,不允许"整站雪崩"。

| 模块不可用 | 影响面 | 降级行为 | 阻塞写? | 告警 |
|---|---|---|---|---|
| `ratelimit`(Redis 不可用) | 认证 / 读 | **认证 fail-closed**(转本地内存 + 账号锁定);**读 fail-open** | 认证拒绝 | **P0** |
| `search`(OpenSearch) | 搜索 / 检索型读 | 读路径**降级到 PG**(`CodeAnalysis` / 项目图表);不重建索引 | 否 | P1 |
| `graph`(PG 侧不可用) | 图读 / 落库 | `sync` **仍可写 PG + 入 outbox**;读走 PG;项目转 **`degraded`** | 否(积压) | P1 |
| `graph`(PG 侧不可用) | 全部写 | **拒绝写**(`503` + `Retry-After`),读尽量 | **是** | **P0** |
| `lease` | 写权 | 拒绝获取/续租 → 客户端降为**只读** | **是** | P1 |
| `sync` | 上传 / 消费 | 拒绝上传;**outbox 停消费**(积压,不丢) | **是** | **P0** |
| `parse` | 服务端解析 | **客户端本地解析兜底**(离线路径不变);服务端作业积压 | 否 | P1 |
| `audit` | 审计写入 | **非安全事件被拒 / 降级**(普通访问日志);**安全事件明细继续全量写、永不抽样**;业务主链继续 | 否 | **P0** |
| `deletion` | 删除 | 拒绝**新**删除请求;进行中作业由 `Job` 重入 | 部分 | P1 |
| `export` | 导出 | 拒绝新导出请求(读路径不受影响) | 否 | P2 |
| `observability` | 指标/告警 | 业务继续 → **进入盲区**,须立即修复 | 否 | **P0** |
| `project` / `auth` | 全站 | **拒绝服务**(无鉴权不可降级) | **是** | **P0** |

---

## 13. 跨模块错误码契约(P0-4 · 摘要;权威 = 附录 B11)

> 每个码**只有一个抛出模块**;语义与既有错误码矩阵**交叉映射**(附录 B / 前端 §15)。

| 码 | 抛出模块 | 语义 | 触发条件 | 既有映射 |
|---|---|---|---|---|
| `401 unauthenticated` | `auth` | 无有效会话 | 未登录 / 会话过期 | §B11 |
| `403 forbidden` | `auth` | `can_view` / `can_edit` 为假 | 越权访问 | §B11 |
| `404 not_found` | `project` | 项目不存在**或无权**(不泄漏存在性) | `resolve_project` 失败 | §B / §G |
| `409 project_deleting` | `project` | 删除中,拒绝一切写 | `graph_sync_status = deleting` | §A5.3 规则 4 |
| **`409 contract_incompatible`** | 接入层 | 契约版本不支持 | `X-Contract-Version` 不匹配 | 前端 §16 |
| `429 rate_limited`(+`Retry-After`) | `ratelimit` | 超配额 | 策略命中 | §B11 / 前端 §15 |
| `503 paused` | 接入层(运维门禁) | F2 恢复期 / 运维暂停 | `paused` 标志 | §F2 |
| `503 graph_unavailable` | `graph` | 存储侧不可用 | PG/PG 故障 | §12 本表 |
| **已删(v27)** | — | 随哈希迁移链删除,任何文档/代码**不得再出现** | — | `409 hash_algo_unsupported` · `409 outbox_not_drained(_24h)` · `409 migrating_full_resync_required` · `409 migration_in_progress` |

---

## 14. 缺口归属与范围声明

### 14.1 模块 12:`export`(独立模块 · 用户裁定)

- **职责**:项目**导出**(`.webapkg`)与**快照**生成/校验/清理;导出授权判定。
- **接口**:
  ```
  submit_export(project_ref, scope, ctx) -> job_id
  get_export_status(job_id) -> status
  build_snapshot(project_ref, graph_rev) -> snapshot_ref     # 离线重放用(见 §G)
  ```
- **边界**:**只读** `graph` / `search` / `project` 的查询接口与元数据;**不写任何业务表**;唯一写 `Job(kind=export)`;**不直接读磁盘源码**(经 `project` 的 `source_path` + 路径安全校验)。
- **依赖**:`graph` · `search` · `project` · `auth`(授权)· `audit`(记审计)· `Job`。
- **为什么独立**:导出是**读密集 + 长任务 + 独立失败域**(挂掉不影响写路径与删除),且与删除**语义相反**(一个保数据、一个清数据)—— 合在一个模块会让"删除模块"同时承担"保证数据完整"的目标,互相牵制。

### 14.2 派生管线并入 `parse`

- `parse` 增接口:`submit_derive(project_ref, graph_rev) -> job_id` · `get_derive_status(project_ref) -> status`
- 作业幂等键:`dedup_key = (project_ref, graph_rev, derived_kind)`(同一图版本重复触发**复用既有 `Job` 行**)
- 写者权限:`CodeAnalysis` / `CodeAnalysisDerived` **唯一写者 = `parse`**

### 14.3 运维作业不建业务模块

`backup` / `restore` / `archive` / `cleanup` / `reap` = **运行手册(§F2)+ `Job` 类型**;作业载体归 infra 作业注册中心。恢复/备份**不进入**任何业务模块的接口面。

### 14.4 配置项归 infra 配置中心

`AppSetting` 归 **infra 配置中心**;各模块只经 **`get_setting(key)`** 访问,**禁止直查表**。

### 14.5 实时通道一期不做

WebSocket / 频道层仅在**接入层预留**,**一期不实现** —— 与 `cursor` 分片、`derived_stale` **同批后置**(见 `B79`/`B80`)。

### 14.6 前端三层映射(不在后端模块边界内)

| 前端层 | 对应后端 |
|---|---|
| **接口客户端(api client)** | 12 个模块的公开接口;契约以 `frontend-contract.md` 为准 |
| **本地存储层(local store)** | `sync` 的请求体契约(`local_pending` / `parse_cache` / `local_snapshot` / `local_conflict`) |
| **页面层(UI)** | 读路径:`graph.query_*` / `search.search`;写路径:`sync.sync_upload` |

### 14.7 两条范围声明

1. **不必一次拆完**:**首批只落 `auth` / `project` / `graph` 三个模块**,其余按需逐个抽出(顺序见 §8 阶段 1)—— 避免"先模块化再减法"的反弹。
2. **附录 E 为历史处置归档**:不做模块标注(其余附录 A–D / F / G 的一级标题均标 `[模块: xxx]`)。

---

## 15. 与 v27 减法的一致性核对

| 核对项 | 结论 |
|---|---|
| 删除进度用 `Job`、无 `ProjectDeletion` | ✅ 与 §G3 / §4.1 一致(含"删除作业自身排除") |
| 项目状态 3 态、outbox 3 态 | ✅ 与 §A5/A5.3 一致 |
| ★ **v28:无 `lease_epoch` / 无 `writer_token` / 无租约模块** | ✅ 与主文 §2.3.11 / §2.3.12 / §5.3 + 附录 A3·A4·D2·D4 **已删**一致 |
| 审计单表 + 归档匿名化 | ✅ 与 §B / §G 一致;**安全事件配额口径以 §B 审计防写爆为准** |
| 限流 = Redis + 本地 + 账号锁定 | ✅ 与 §B11 / §F 一致(含已知取舍) |
| VID 固定 `sha256_16`、两端 bit-exact | ✅ 与 §D1.5 一致 |
| 软删除只写 `lifecycle` | ✅ 与 §D1.3 / §A5.1 一致 |

**唯一待你确认**:模块 8「安全事件**不限流**、不抽样」与 `backend-tenancy-security.md` 的「审计防写爆(**分级限流**)** 表述不一致 —— 本文已改为"安全事件保留完整语义 + 配额口径以 §B 为准"。若你的意图是"安全事件**完全**不限流",需同步改 §B(那会影响防写爆)。
