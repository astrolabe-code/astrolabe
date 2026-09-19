# 附录 D · 数据契约细则(随主文 v27 · 初版 v3 · P0 实施门槛)

> **对应第三轮审阅**:P0-1(128 位 VID 物理编码)、P0-3(`CodeAnalysis` 写入路径矛盾)。★ **v28:P0-2(`file_rev` 归属)与 P0-4(写权锁语义)已随「图不可变」整体删除**(原 D2 / D4 两章)。
> **定位**:本附录是**实施前必须拍板的硬门槛**。主文 §4/§5 的字段级定义与本节对齐后,才允许进入阶段 0 之后的图存储改造。
> **纪律**:本附录出现的字段名、类型、DDL、幂等键,是**唯一口径**;主文与附录 A/B/C 若与此不一致,以本附录为准。

---

## D1 128 位 VID 的物理编码(P0-1) | [模块: 共享内核]

### D1.1 候选方案与取舍

| 方案 | 表达 | 问题 | 结论 |
|---|---|---|---|
| 两个 int64 分列 | `vid_hi` + `vid_lo` | **不可行**:`vid` 必须是**单值**;SQL 无 `a*2^64+b` 这类组合表达(且会溢出),也没有"复合主键当一个标识用"的等价语义 | ❌ 否决 |
| INT64 拼接 | 64 位 hash | 回到碰撞问题(**全库累计**,亿级即 `1e-4`) | ❌ 否决(即 v1 方案) |
| **`char(32)` 小写 hex** | `encode(uid_hash_128,'hex')`,32 字符 | 宽度 32B(比 `bytea(16)` 大 1 倍),索引内存上升 | ✅ **采纳** |

**采纳理由**:①可打印、可日志、可跨库比对(PG/OpenSearch/浏览器/AuditLog 都能直接存字符串);②无溢出、无复合键、无碰撞歧义;③`char(32)` 是**定长**,不额外存长度,索引开销可控;④节点规模量级小(单项目 ≤5 万节点边、全库百万级),32B 完全可接受。

### D1.2 关键实施约束(**列类型在建表时定死**)

> ⚠ **`vid` 的列类型是"事实上的定稿"** —— PG 下改列类型 = **全表重写 + 索引重建**(`ALTER TABLE … ALTER COLUMN … TYPE …`),且 `vid` 被 `graph_edge` 的 `from_uid` / `to_uid` 间接引用。数据量大时不可接受。
> 因此 `char(32)` 必须在**首次建表**(阶段 1)就定下来,并进部署工件。

| 项 | 值 | 说明 |
|---|---|---|
| `graph_node.vid` | **`char(32)`** | 与 `encode(uid_hash_128,'hex')` 严格对应,**禁止大写 / 变长** |
| 编码 | **`sha256_16(project_ref + "\0" + uid)`** → 16 字节 → **小写 hex(32 字符)**;`HASH` = **固定 `sha256_16`**(v28:算法**全库固定、不可变、无备选**) | 三端必须同一实现,并用**固定测试向量**锁定(`sha256_16` **一组**,见 D1.5);算法取值**以固定 `sha256_16` 为唯一来源**(P0-2) |
| 存储 | ★ **PG 只存 `vid char(32)`** —— `uid_hash_128` 是**计算中间量,不落库**;需要反查时用 `decode(vid,'hex')` | 避免"一份标识两种落库形态";`(project_ref, uid)` 为节点主键,`vid` 为内容寻址派生列 |
| 浏览器侧 | `vid: string`(32 位 hex) | 与 §5.2 一致;浏览器侧本地存储也按字符串处理 |

### D1.3 PG DDL 片段(阶段 1 直接可用)

```sql
CREATE TABLE graph_node (
  project_ref uuid   NOT NULL,
  uid         varchar(512) NOT NULL,              -- 项目内唯一(内容寻址);长度上限防超长字符串
  vid         char(32) NOT NULL,                  -- sha256_16(project_ref ‖ "\0" ‖ uid)
  kind varchar(32), name varchar(200), qname varchar(500),
  file_path varchar(1024), line int,
  signature varchar(512), is_entry bool, is_dead bool, cluster varchar(200),
  lifecycle   text   NOT NULL DEFAULT 'active',   -- active | hidden | deleted
  graph_rev   bigint NOT NULL,                    -- ★ 本轮删 vid_op_rev(图不可变 ⇒ 无乱序防护对象,见 D5)
  last_graph_rev bigint,                          -- ★ 消费水位:outbox 消费成功时回写;NULL = 从未消费(附录 F2 步骤 3 靠它反查)
  PRIMARY KEY (project_ref, uid)
);

CREATE TABLE graph_edge (
  project_ref uuid NOT NULL,
  from_uid varchar(512) NOT NULL, to_uid varchar(512) NOT NULL, type varchar(32) NOT NULL,
  confidence real, resolution varchar(16), site_count int, level varchar(16),
  origin varchar(16) NOT NULL,                    -- ★ parsed | manual(人工修补边必须能与解析边共存)
  dangling bool,
  lifecycle text NOT NULL DEFAULT 'active',       -- active | deleted
  graph_rev bigint NOT NULL,
  PRIMARY KEY (project_ref, from_uid, to_uid, type, origin)   -- ★ v28:含 origin(与前端契约/实测一致;人工修补边不与解析边冲突)
);

CREATE INDEX idx_edge_out  ON graph_edge (project_ref, from_uid, type);
CREATE INDEX idx_edge_in   ON graph_edge (project_ref, to_uid,   type);
CREATE INDEX idx_node_kind ON graph_node (project_ref, kind) WHERE lifecycle = 'active';
```

> **v28**:图与元数据**同库** → 无独立图库、无 space / TAG / EDGE 概念;`project_ref` 用 `uuid`(16 B,见 §0.0 编码规则)。
> ★ **两处约束说明**:①`uid` / 展示类字段用 `varchar(N)` 而非 `text` —— **DB 层兜住超长字符串**(`.webapkg` 可能含超长值,附录 B9 净化只是应用层);②**边主键含 `origin`** —— 人工修补(`origin=manual`)与解析产物(`origin=parsed`)**必须能共存于同一 `(from_uid, to_uid, type)`**,否则维护者修补会**覆盖解析结果**(§2.3.12)。

### D1.4 读写样例(DAO 模板;1–2 跳用递归 CTE)

```sql
-- 写入(★ 本轮重写:图不可变 ⇒ 已存在即忽略;幂等由 parse_hash 在更上层保证,主文 §5.3)
INSERT INTO graph_node (project_ref, uid, vid, kind, name, graph_rev)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (project_ref, uid) DO NOTHING;

-- 一跳(出边邻居)
SELECT n.uid, n.kind, n.name, e.type
FROM graph_edge e JOIN graph_node n
  ON n.project_ref = e.project_ref AND n.uid = e.to_uid
WHERE e.project_ref = $1 AND e.from_uid = $2
  AND e.lifecycle = 'active' AND n.lifecycle = 'active'
LIMIT 200;

-- 二跳(UNION 自动去环;跳数与行数由服务端夹取)
WITH RECURSIVE hop AS (
  SELECT e.to_uid AS uid, 1 AS depth FROM graph_edge e
   WHERE e.project_ref = $1 AND e.from_uid = $2 AND e.lifecycle = 'active'
  UNION
  SELECT e.to_uid, h.depth + 1 FROM hop h JOIN graph_edge e
    ON e.project_ref = $1 AND e.from_uid = h.uid AND e.lifecycle = 'active'
   WHERE h.depth < LEAST($3, 2)
)
SELECT n.uid, n.kind, n.name, MIN(hop.depth) AS depth
FROM hop JOIN graph_node n ON n.project_ref = $1 AND n.uid = hop.uid
WHERE n.lifecycle = 'active'
GROUP BY n.uid, n.kind, n.name
LIMIT 2000;
```

> **>2 跳与图算法**:**不走 PG** → 提交 `Job(kind=graph_analysis)` 给加速器池(主文 §4.5),结果落 `graph_analysis_result`。

### D1.5 哈希选型:为何弃用 xxhash(S-P0-1 · 安全底线)

VID 是**跨库主键**,且**客户端参与计算** —— 它不是内部索引,而是**外部可构造、可观察的值**。原 `xxhash128` 选型把性能换成了不可接受的安全风险:

| 风险 | `xxhash128`(v3) | **加密哈希**:**固定 `sha256_16`**(v27:算法不可变、无备选) |
|---|---|---|
| 抗碰撞(构造恶意 uid 使其 hash 撞上已知 VID → **冒用他人 VID 写入**) | ❌ 碰撞阻力远低于加密哈希 | ✅ |
| 抗原像(拿到公开项目 VID 后暴力枚举 uid 空间 → 信息泄露) | ❌ 极快(GB/s 级) | ✅ |
| 审计可解释性 | ⚠ 无雪崩效应 | ✅ |
| 性能 | 更快 | 浏览器端仍 GB/s 级,**可接受** |

**裁定(v5 修订,P0-1)**:哈希算法**取消"运行时降级"**,改为**项目级、服务端决定、不可变**:

| 项 | 规则 |
|---|---|
| 算法取值(v27) | **固定 `sha256_16`** —— **不可变 / 不可切换**(固定 `sha256_16` 已删除,哈希迁移链整体移除) |
| **取值(必读)** | **固定 `sha256_16`**(SHA-256 截 16 字节;**WebCrypto 零依赖、全浏览器可用**);**无备选、无能力探测**(v27) |
| **禁止静默降级** | 浏览器缺本项目所需算法实现时 → **绝不用另一种算法顶替**(否则同 uid 双 VID);按下方「设备能力降级语义」处理 |
| **设备能力降级语义(P0-2)** | 见下方专节:**不支持 = 只读浏览,不是整个项目不可用,也不是强迫上传源码** |
| 算法标识 | **不加 VID 前缀**(见下方说明) |
| 测试向量 | 由参考实现生成后固化进仓库(**`sha256_16` 一组**),三端 CI 分别比对 |
| 性能验证 | 三端各跑 100 万次哈希,记录耗时,结果回写本附录 |

**关于"VID 前缀 `b3:` / `s2:`"(评审建议 2:部分不采纳,理由如下)**:

前缀的价值是**"同一 VID 空间内混用算法时能判别"**。本方案中:①★ **算法全库固定 `sha256_16`(不可变、无备选)** ②VID 已含 `project_ref` → **跨算法歧义在结构上不可能出现**。而加前缀需要把 `vid` 从 `char(32)` 拉到 `char(40)`,**全部主键与索引重建**,收益为零。故**不采纳**,改为**等价的元数据断言**。

> ★ **v28:本条已无实际争议** —— "混用算法"的场景**不存在**(算法固定不可变),前缀方案与"首次建表前拍板"的要求**一并作废**。

## D2（★ v28 已整体删除）

> ★ **v28 删除声明**：「`file_rev` 的归属」**整体删除** —— 图不可变后**没有「文件版本协商」**；`files[]` 只保留 `{path, sha1}` 作为**完整性清单**（主文 §5.4），`file_rev` / `base_file_rev` / `writer_token` 字段**均不再存在**。

---

## D3 `CodeAnalysis` 的唯一写者(P0-3) | [模块: parse]

### D3.1 结论：唯一写者（★ 本轮重写）

> ★ **本轮定稿**：`CodeAnalysis` 的来源**不再"按模式分档"** —— 只剩**两种互不相交**的情形。

| 场景 | `CodeAnalysis` 唯一写者 | 服务端是否重算 | 客户端 `analysis` 是否接收 |
|---|---|---|---|
| **`local`（私有）** | **浏览器** | —（服务端**没有**这份数据） | ❌ **不上行**（H1 / H5） |
| **`hosted`（公开）** | ★ **服务端解析管线** | ★ **是** —— 源码由服务端**从 GitHub / Gitee 拉取**（H6） | ★ **一律忽略客户端值** |

> **为什么原「按模式分档」被删除**：原表有一行 **`hosted`（客户端解析）→ 浏览器为唯一写者、服务端只读不重算**。
> 这一行**正是「图可伪造 / 锚坐标系可被污染」的来源** —— 服务端"只整行存储、不重算"，等于**无条件信任客户端产出的图与指标**。
> H6（公开项目只能由服务端拉取源码）之后，**这条路径不存在** ⇒ 公开项目的图与 `CodeAnalysis` **永远是服务端自己算的** ⇒ **矛盾与风险同时消失**。

### D3.2 物理隔离仍然保留（但意义改变）

`CodeAnalysis`（**解析期产物**）与 `CodeAnalysisDerived`（**基于图的派生指标**）**仍然分表**，但理由从"防双写互相覆盖"变为：

1. **写者不同**：`CodeAnalysis` 由**解析作业**写（每快照一次，**不可变**）；`CodeAnalysisDerived` 由**派生作业**写（可随 `graph_rev` 重算）；
2. **生命周期不同**：解析产物**永久不可变**；派生指标**可重算** —— `based_on_graph_rev < 当前 graph_rev` ⇒ 响应带 **`derived_stale: true`**，**照常展示、读路径永不阻塞等待派生**，并给出 `index_lag`（主文 §5.5）；
3. 主字段 `writer`（`client` | `server`）**降级为诊断字段**（一期**恒为 `server`**）—— ⚠ **不得**再用于「客户端为唯一写者」的判定。

### D3.3 验收

- **公开项目**：提交任何客户端 `analysis` ⇒ ①**被忽略** ②`CodeAnalysis` **不被改写**（用例断言）③`AuditLog` 记 `project_ref` / `batch_size` / `graph_rev` + 标记"客户端 analysis 被忽略"，**不记内容**（避免审计库被大 JSON 灌爆，且符合 B10 脱敏要求）；
- **私有项目**：`CodeAnalysis` **只存在于客户端本地**，服务端**不存在对应行**（用例断言）；
- 前端合并结果与旧契约字段一致（SPA 只读页零改动）。

### D3.4 同步请求里 `analysis` 字段的落位（A-P1-1）

| 场景 | 落位 |
|---|---|
| **`local`（私有）** | **只落客户端本地**（不上行；H1 / H5） |
| **`hosted`（公开）** | ★ **忽略客户端的 `analysis`**（服务端管线为唯一写者）；审计留痕 = `AuditLog`，**不记内容**（B10 脱敏） |

> ★ **净化仍然必做**：客户端提交的 `analysis` / `nodes` / `edges` **仍必须过 JSON Schema + XSS 净化 + 大小上限**（附录 B9）—— 因为**请求仍会到达服务端**（随后被忽略）；防的是**恶意载荷**，不是数据真伪。

---

## D4（★ v28 已整体删除）

> ★ **v28 删除声明**：「写权锁：两把锁 + fencing」**整体删除** —— 图不可变后**无客户端写者**，故**无锁可争**；服务端解析作业的串行由现成 `Job.dedup_key` 承担（主文 §5.3 / §8）。原「两把锁 / 全局锁顺序 / 状态转移表 / 作业优先抢占 / `lease_epoch`」**均不再存在**。

---

## D5 `vid_op_rev`（★ 本轮整体删除） | [模块: graph]

> ★ **删除声明**：`vid_op_rev` **整列删除**，原「语义 / 生成 / PG 落地」（D5.1 / D5.2）**全部作废**。
>
> **为什么它失去了存在意义**：它的唯一职责是「**同一 VID 内的乱序防护**」—— 即"同一节点被多次变更时只接受更新的那次"（原结论 `vid_op_rev = graph_rev`）。
> 「图不可变」（主文 §2.3.12）之后，这条职责**没有对象了**：
> ①**同一 `(project_ref, uid)` 只会被写一次**（首次解析 = 一个事务）⇒ **不存在"多次变更"**；
> ②写入退化为 `INSERT … ON CONFLICT (project_ref, uid) DO NOTHING` ⇒ 原 `WHERE vid_op_rev < EXCLUDED.vid_op_rev` **永不为真**（`DO UPDATE` 分支成为**死代码**）；
> ③**维护者修补**走 `UPDATE`（**LWW + 全量审计**，主文 §2.3.12）—— **不走版本守卫**。
>
> **保留与替代（唯一口径）**
>
> | 项 | 结论 |
> |---|---|
> | `graph_rev` | ★ **保留** —— 语义 = **「快照内的写入序号」**（服务 `index_lag` 水位、`based_on_graph_rev` 派生校验、**修补后 +1**） |
> | **幂等** | ★ 由 **`parse_hash`** 在**更上层**保证（主文 §5.3）—— **不是**由列级版本守卫保证 |
> | `search_outbox` 唯一约束 | **`UNIQUE(project_ref, uid)`**（唯一权威见主文 §4.1；模块化 §11 事件契约同步）。⚠ 原作废口径 = `UNIQUE(project_ref, graph_rev, vid, target)`（v25 引入）—— ①图落 PG 后 outbox **单目标**（无 `target` 列）；②图不可变 ⇒ 同一 `(project_ref, uid)` **只入队一次** |
>
> ⚠ **不可再实现的场景（前提已消失）**：乱序投递防护 /「墓碑 + 重放」用例 / 每 VID FIFO / `FETCH → 比较 → INSERT` —— 这些场景都依赖「**同一 VID 多次变更**」，而**它已不存在**。

### D5.3 `node_ref` 字段已删除(P1-4)

v6 设想的 `node_ref = vid` 是**纯冗余**:①`id(n)` 本身就是 VID,查得到 ②每顶点白多 32 字节 ③多一个字段就多一处可能不一致(写错即 `node_ref != vid`)。**v7 删除该字段**;需要"PG 侧指针"时直接用 `id(n)` 查,不另立字段。

---

## D6 `CodeAnalysis` 与 `CodeAnalysisDerived` 的字段级合并(P0-6) | [模块: parse]

D3 只写了"物理隔离 + 读取时合并",没说**哪些字段归谁、冲突怎么办**。本节给出字段归属表(唯一口径)与合并规则。

### D6.1 字段归属表

| 字段 | 客户端算(语法级) | 服务端算(语义级) | 归属 | 合并规则 |
|---|---|---|---|---|
| `stats.node_count` / `edge_count` | ✅ | ✅ | **按模式** | ★ 本轮：`local`（私有）→ **客户端值**；`hosted`（公开）→ **服务端值**（唯一写者，D3.1） |
| `stats.by_kind` / `by_lang` | ✅ | ✅ | **按模式** | 同上 |
| `stats.by_type` | ⚠ 语法级粗 | ✅ 精确 | **Derived** | **恒用服务端**;客户端值仅作 fallback |
| `entry_points` | ✅ 语法级 | ✅ 语义级 | **按模式 + 标注 `resolution`** | 私有 → 客户端值;公开 → 服务端值;**两边都有时展示服务端,并标注"语法级另有 N 个"** |
| `diagnostics` | ✅(限制/跳过统计) | ⚠ 部分 | **`CodeAnalysis`(客户端)** | 服务端**不覆盖**(它是解析器自述的限制) |
| `processes`(执行流) | ❌ | ✅ | **Derived** | 服务端;为空 → 前端显示"暂无(需语义级)" |
| `clusters` | ❌(浏览器不做) | ✅ | **Derived** | 服务端;为空 → "暂无" |
| 影响面 / 环 | ❌ | ✅ | **Derived** | 服务端 |

### D6.2 合并与不一致处理

1. **读取合并点**:服务端在 `analysis/`、`diagnostics/` 出口处合并两表,**响应结构与旧契约完全一致**(前端零改动)
2. **优先级**:逐字段按 D6.1;整体上是 **`CodeAnalysis`(权威主字段)+ `CodeAnalysisDerived`(派生补充)** —— **不是"谁新用谁"**
3. **不一致**:同一字段两边都有值且不同 → **按 D6.1 取权威方**,并在响应里带可选字段 `analysis_conflicts: [{field, client, server}]`(旧前端忽略);前端可在"技术详情"展示差异,**不阻塞展示**
4. **两种"缺失"必须分开(v20 P0-7 定稿)**:⚠ v19 的"**字段留空**"与主文 §7 的"**缺失字段不出现在响应里(JSON 无该 key)**"是**两套互斥语义**,前端**无法同时满足**。定稿:
   - **契约降级(版本不兼容)** → 字段**在 JSON 里不存在该 key**:语义 = "本次服务端不提供该能力",前端按"**功能不可用**"处理(权威定义在**主文 §7**);
   - **业务空值(未算 / 无数据)** → **必须显式返回 `null`(标量)或空数组(集合)**:`CodeAnalysisDerived` 缺失(未跑语义级)属此类,前端显示"**暂无(需语义级解析)**",**不得用 0 冒充**;
   - **前端判定规则(可依赖)**:`key` **不存在** = 契约降级;`key` **存在但值为 `null` / 空数组** = 业务空值。**两者不得混用**,也不得用 `null` 表达契约降级。
5. **`based_on_graph_rev` 落后**:响应带 `derived_stale: true`,前端显示"派生指标待更新",**照常展示**


## D7 请求体字段清单(v27:D7.1 转为**人工 review 清单**;原 F3 脚本已删除) | [模块: sync]

> **权威源 = 主文 §5.4**(v19 P1-10 去重):本附录只是**人工核对索引**;**若与 §5.4 不一致,以 §5.4 为准**且按文档缺陷处理。

⚠ **为什么单独立一节(v27)**:原 F3 的"协议字段检查"若**在附录 D 全篇做动态提取**,会把 **SQL DDL 的属性**(`name`/`kind`/`lifecycle`)、**PG 列**(`uid_sha256` 等)、**本地存储字段**(`local_pending` 等)一并捞出来 → **大量误报、无法验证是否遗漏**。故**只从本节提取**(脚本规则唯一、可验证)。

> **D7.1 的完整性由谁保证(v27 改写)**:F3 脚本已删除 → **改由人工 review 清单保证**:①**契约权威 = 主文 §5.4**;**D7.1 = 人工逐字段核对用的索引**;②新增/删除任何请求体字段时,**§5.4 与 D7.1 必须在同一批次内同时修改**;③**D7.1 不得由脚本自动生成**(自动提取必然捞进非请求体字段 → 误报);④**服务端分配、非请求体的字段**(如 `graph_rev`、索引水位 `indexed_graph_rev`)不进 D7.1

### D7.1 请求体字段清单(只含真正走 HTTP 的字段)

**常规期**(v27:无迁移期,只有一种请求体):

- 顶层:**`project_ref`**(值 = `Project.project_ref`)、**`snapshot`**(`repo` / `commit` / `parser_v` / `parse_hash`)、`files[]`(`path` / `sha1`)、`upserts`、`deletes`、`analysis`
  - ★ **v28 变更**:删 `base_graph_rev` / `writer_token` / `lease_epoch` / `files[].base_file_rev` / `files[].state` —— **请求体是「提交一份图快照」,不是「协商两端变更」**(主文 §5.4 为唯一权威)
- `upserts.nodes[]`:`uid`、`kind`、`name`、`qname`、`file_path`、`line`、`signature`、`is_entry`、`is_dead`、`cluster`、**`lifecycle`**(P0-1:枚举 `active` / `hidden`;**常规期即必填**;`deleted` 走软删除路径、不出现在 `upserts`)
- `upserts.edges[]`:`from_uid`、`to_uid`、`type`、`confidence`、`resolution`、`site_count`、`level`、`origin`、**`lifecycle`**(P0-1:`active` / `deleted`)
- `deletes.nodes[]`:`uid`;`deletes.edges[]`:`from_uid`、`to_uid`、`type`

**迁移期新增**(顶层 `migration` 必需;其余"**服务端权威、客户端可选对账**"):

- 顶层:**`migration`**(常规期**禁含**)
- 顶点:`old_vid`、`new_vid`
- 边:`old_vid_from`、`old_vid_to`、`new_vid_from`、`new_vid_to`

> ⚠ **`lifecycle` 不属于"迁移期新增"** —— 它是**常规期就有的请求体字段**(P0-1);v15 的"迁移期 `lifecycle` 保留"只是把它**暴露出来**。

### D7.2 非请求体字段(说明性,不参与请求体核对)

- **⚠ v27 删除**:原「日志列」(`vid_old` / `vid_new` / `prev_lifecycle` / `applied` / `batch_id` / `migration_ended_at`)随 `graph_migration_log` 一并删除;唯一保留 **`edge_type`** —— 它是边身份 `(vid_from, vid_to, edge_type)` 的组成部分,不是迁移字段
- **本地存储字段(§3.3)**:`local_pending`、`local_conflict`、`local_snapshot` 等
- **PG 属性(D1.3)**:`kind` / `name` / `epoch` 等(其中 `lifecycle` **同时**是请求体字段,见 D7.1);★ 本轮删 `vid_op_rev`

> **为什么必须拆开(P2-2)**:v15 曾把 `edge_type` 混进"迁移期新增的请求体字段" → **F3 会把它当请求体字段去 §5.4 里找,必然失败**(它不是 HTTP 字段,只是日志列)。D7.1 是**唯一提取源**,D7.2 只是注解。

**核对规则(v27 人工)**:①**D7.1 列出的每个请求体字段**都必须出现在 **§5.4**;②**`lifecycle`(节点与边)必须在 D7.1 与 §5.4 同时出现**;③请求体里出现、D7.1 里没有的字段 = **缺陷**

## D8 读路径统一契约(v18 新增;优先级 P2) | [模块: graph+search]

### D8.1 统一入口 `graph_query(req, ctx)`

- 所有图 / 检索查询经 **`graph_repo` 的唯一函数 `graph_query(req, ctx)`** 出口,内部按 `req.kind` 路由到 **PG**(边 / 跳数 / 影响面 / 环 / 聚类 / 执行流)/ **OpenSearch**(节点检索与聚合)/ **PG**(详情 / 笔记 / 分析合并)
- **强制**由 `ctx` 注入 `project_ref`(附录 B3);**DAO 出口断言**:`req` 里出现的任何 `project_ref` **一律忽略并告警**
- **前端与未来 AI 智能体走同一路径** —— 避免"两套逻辑漂移"(这是归一化的全部意义)

### D8.2 `graph/edges/` 与跳数查询:必须分片

| 参数 | 语义 | 约束 |
|---|---|---|
| `limit` | 本次返回的边数上限 | **必填**;**服务端强制夹取**(起步上限 **2000**;超出**按上限返回,不报错**) |
| `cursor` | 续取游标 | **不透明字符串**(客户端**不得**解析成 offset);为空 = 从头;服务端内部编码"上次位置",**不使用深分页 offset** |
| `depth` | 跳数(一跳 / 多跳) | 多跳**必须同时给 `limit`**;默认**只返回子图摘要** |
| `summary_only` | 只取摘要 | 默认 `false`;前端"按需展开"时用 |

**响应结构(分片与摘要共用)**

```jsonc
{
  "items": [ /* 边:from_vid / to_vid / type / confidence / resolution / site_count / level / origin */ ],
  "next_cursor": "…",            // null = 无更多
  "summary": { "node_count": 128, "edge_count": 342, "by_type": { "CALLS": 300, "IMPORTS": 42 } }
}
```

⚠ **为什么必须分片**:大项目一次性返回全部边会让**前端内存爆炸**;因此"**摘要先行 + 按需展开**"是**默认交互**,而流式/分片返回是 **P2** 优化项(见附录 E18 第 7 项)。

### D8.3 `analysis/` 的「派生就绪」语义

- **就绪**:派生计算作业(见主文 §3.x 的"`outbox` 全 `acked` → 触发派生计算")完成后,`CodeAnalysisDerived.based_on_graph_rev` **等于当前 `graph_rev`** → 响应**不带** `derived_stale`
- **未就绪**:`based_on_graph_rev < graph_rev`(或该 `graph_rev` 尚无派生结果)→ 响应带 **`derived_stale: true`**,前端显示"派生指标待更新",**照常展示**(与 **D6.2** 口径一致)
- **语义边界**:`analysis/` **永不阻塞**等待派生计算 —— 读路径**只读已落库结果**;"零等待"指的是**把等待移到了写路径之后**(预计算),**不是**在读路径加锁

## D9 派生预计算契约(v18 新增;优先级 P1) | [模块: parse]

**① 触发(唯一口径;主文 §5.5.1 ① 与本处**逐字一致**)**:**该项目 `search_outbox` 中**无处于 `pending` 的行** → 视为**图已落库追平** → 触发**派生计算作业**(**`dead` 行不阻塞**,§5.5 单目标 3 态)。**不在逐行消费时触发**(避免 N 次重算)。

> ⚠ **本条修正历史**:v18–v19 曾写"`outbox` 全部 `acked`(即 `index_lag == 0`)",**两处都错** —— ①**`dead` ≠ `acked`** → 一行进 `dead` 即**永久冻结派生**;②`index_lag` 是**版本差**且排除 `dead`,与"全部 acked"**不等价**(主文 §5.5.1 在 v19 已专门修过这一处,本条为**同步补齐**)。权威源 = **主文 §5.5.1**,本处只引用不另立口径。

**② 幂等键**:`(project_ref, graph_rev, derived_kind)`;`derived_kind ∈ {cluster, process, cycle, impact}`;重复触发**复用 `Job` 去重**(不新建行)。

**③ 确定性**:Leiden / Process 使用**确定性种子**(`project_ref` 哈希或固定常量)→ **同一 `graph_rev` 必须可复现**;这是 `based_on_graph_rev` 校验成立的前提。

**④ 互斥(★ v28)**:**无租约可回收**(租约 / 两把锁已整体删除,原附录 A3 / D4);派生作业**只读图 + 只写 `CodeAnalysisDerived`**,**不写 `CodeAnalysis`**(唯一写者见 D3.2),与解析作业的串行由**现成 `Job.dedup_key`** 承担(主文 §5.3)。

**⑤ 失败语义**:耗尽重试后**不阻塞读路径** —— 前端拿到上一版结果 + `derived_stale: true`(D8.3);**不因派生失败而拒绝图查询**。

**⑥ 观测**:见附录 F1(派生作业时长、失败重试计数、`derived` 覆盖率)。
