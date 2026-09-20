# Astrolabe · 文档索引

> ★ **本目录是 astrolabe 项目的权威文档位置。**
> 如果你（人或 AI）刚接手、或对话上下文已被压缩，**先读本文件**，再动手。
> ⚠ 本项目为**独立项目**（旧项目已封存，**不要再打开**）

---

## 一、先读什么（阅读顺序）

| 顺序 | 文档 | 什么时候读 |
|---|---|---|
| **1** | **本文件** | 永远第一个 |
| **2** | ★ **`ARCHITECTURE.md`** | **写任何代码之前** —— 分层边界与依赖纪律 |
| **3** | ★ **`PRODUCT-VERSIONS.md`** | 涉及**版本 / 许可 / 仓库边界 / 企业授权**时 |
| **4** | ★★ **`USERS-AND-AUTH.md`** | ★ **涉及登录 / 权限 / 配额 / 勋章 / "谁能做什么"时** —— 写认证与权限层之前必读 |
| **5** | `backend-strategy-plan.md` | 对外战略与授权（开源商业边界、时间戳证据链、署名保护） |
| **6** | `frontend-contract.md` | 写 API 时 —— ★ **§1–§13 是新后端要照实现的契约** |
| **7** | `backend-design.md` | 设计主文（⚠ 含已删除机制的章节，注意时效性标注） |
| **8** | `backend-decisions.md` | 查历史决策（**B1–B158**） |
| **9** | ★ **`GRAPH-STORAGE.md`** | **图存储 / 邻域查询 / 算法接口** —— 写解析器与读路径时必读 |
| **10** | ★ **`JOB-MODEL.md`** | **作业投递 / 排队 / 执行 / 进度** —— 写作业与 worker 时必读（含 `B115` 验收判据） |
| **11** | ★★ **`WEBAPKG-SPEC.md`** | **`.webapkg` 开放格式规范**（标准文档）—— 写导出/导入、做 AI 集成时必读 |
| **12** | ★★★ **`GRAPH-SCHEMA.md`** | **图数据字段 Schema**（节点/边/锚点/笔记）—— ★ **三条铁律在此**：标准潜力 · AI 友好 · 可下载重建 |

> ⚠★ **部署与交付**（Docker Compose）的文档**已从公开仓库移除**（含宿主机路径等基础设施信息）——
> ★ 完整记录见 `backend-decisions.md` 的 **`B158`**。★ 部署相关的设计结论仍保留在各决策条目中。

---

## 二、★ 时效性标注（重要）

> ⚠ 这批文档是从旧项目整体迁入的，**里面混着已经作废的设计**。实施前先看这一列。

### ✅ 现行依据（新写的，以它们为准）

| 文档 | 地位 |
|---|---|
| ★ `ARCHITECTURE.md` | **分层边界以它为准**（A3 依赖纪律） |
| ★ `PRODUCT-VERSIONS.md` | **版本 / 许可 / 仓库边界**以它为准 |
| ★ `USERS-AND-AUTH.md` | ★ **用户档次 / 职责 / 权限 / 认证 / 配额 / 勋章**以它为准 |
| ★ `GRAPH-STORAGE.md` | 图存储 · 邻域查询 · **算法接口（G6 = 换图库的唯一预留点）** |
| ★ `GRAPH-SCHEMA.md` | 图数据字段 Schema |
| ★ `JOB-MODEL.md` | 作业模型（`B115` 验收判据在此） |
| ★ `WEBAPKG-SPEC.md` | `.webapkg` 开放格式 |

### ⚠ 参考（⚠ 含已作废设计，读时看标注）

| 文档 | 时效性 |
|---|---|
| ⚠ `backend-design.md` | **参考** —— 主文，但含**已删除**的机制（写者租约 / 同步协商 / `file_rev` / `vid_op_rev`） |
| ⚠ `backend-modular-architecture.md` | **参考** —— 模块划分仍可用；⚠ 含已删的 `lease` 模块 |
| ⚠ `backend-authority-matrix.md` | ⚠ **大半已作废** —— 附录 A3（写者租约）/ A4（文件级版本向量）**整章已删** |
| ⚠ `backend-contract-detail.md` | **参考**（附录 D） |
| ⚠ `backend-tenancy-security.md` | **参考**（附录 B） |
| ⚠ `backend-ecosystem-refs.md` | **参考**（附录 C · 竞品对标） |
| ⚠ `backend-implementation-gates.md` | **参考**（附录 E） |
| ⚠ `backend-observability-dr.md` | **参考**（附录 F） |
| ⚠ `backend-data-lifecycle.md` | **参考**（附录 G） |
| ⚠ `backend-parse-flow-current.md` | ⚠ **旧网站**的现状描述 —— 仅作参考，**不描述新项目** |
| ⚠ `backend-redesign-notes.md` | ⚠ 同上（旧网站实测现场） |

### ★ 现行（但部分被覆盖）

| 文档 | 说明 |
|---|---|
| ★ `backend-strategy-plan.md` | **现行**（⚠ 例外：其 `S2.1` 第 10 项「部署脚本可开源」已被 `PRODUCT-VERSIONS.md` G 节改判为**不开源**） |
| ★ `frontend-contract.md` | **现行** —— §1–§13 前端契约；§14–§20 为目标契约（⚠ 含**已删机制**：租约 / 版本向量） |
| ★ `frontend-decisions.md` | **现行** —— 前端决策登记（D 表） |

**工具脚本**：`build-full-design.sh`（快照生成器，⚠ 可能依赖未迁入的文件，用前先试跑）、`check-forbidden.sh`、`finalize-full.py`、`make-social-preview.py` / `make-org-avatar.py`（★ 品牌资产生成，可用）。

---

## 三、写入纪律（必须遵守）

1. ★ **决策/改进先登记**：任何新决策或用户提出的改进，**先追加到登记表**，再同步其它文档，**最后才动代码**。
   - 前端：`frontend-decisions.md`（格式 `D<n>`）
   - 后端/项目级：`backend-decisions.md`（格式 `B<n>`）
   - ⚠ 顺序固定：**登记 → 同步文档 → 才动代码**
2. ★★ **对话不作数**：只存在于对话里的结论视为**未确认**，**必须落盘到本目录才生效**。
3. ★ **不落 `/tmp`**：测试脚本、联调记录、临时结论一律留在仓库内，避免被系统清理吞掉。
4. **架构边界优先**：⚠ 任何新增模块，**先对照 `ARCHITECTURE.md` 的 A3 依赖纪律**（四层谁能 import 谁）。
5. ★★ **静默失败禁止**（`B132`）：⚠ **能力缺失必须可见** —— 不要写 `except: pass`；<br>★ 判据：**一个功能"没生效"时，日志里必须能找到原因**。

---

## 四、当前阶段

**★★ 已开工，内核 + 认证 + 发布链路跑通**

| 层 | 状态 |
|---|---|
| **环境** | ✅ **Docker Compose 全容器化**（6 容器：`db` · `redis` · `web` · `worker` · `heat` · `nginx`）<br>⚠ **镜像纪律**：★ 只有 `web` 构建镜像，`worker`/`heat` 复用（`B132`）<br>★ 缓存/队列的**实现是 Valkey**（BSD-3-Clause），⚠ **服务名仍叫 `redis`**（`B159`） |
| **② 解析内核** | ✅ `codeparser/`：C / C++ / Python / Java（tree-sitter）+ 汇编（轻量符号提取）<br>✅ `scanner.py` 目录扫描 · ✅ `graph/writer.py` 图写入方（★ **图不可变**，`B155`） |
| **图** | ✅ 邻接表 + 双向索引 · ✅ **多跳遍历 1–10 跳**（逐层 BFS + 四道刹车）<br>✅ **邻域缓存**（`rev` 命名空间失效）· ✅ **访问热度** + 合并作业（`heat` 服务）<br>✅ **维护者手工修补**（`graph/curate.py` · ★ **项目创建者自己**在网页上改，`B157`） |
| **① Web 层** | ✅ 项目模型 / 权限 / 响应形态 / **33 个路由**（含 ★ **多跳邻域** · **图修补 `graph/edit/`**）<br>✅ ★★ **真端到端跑通**：API 建项目 → 投队列 → worker 解析 → 读图（240 节点 / 543 边） |
| **认证与用户** | ✅ **已实现**（`B143`–`B148`）：`core/oauth.py`（GitHub / Gitee）· `core/invites.py`（邀请制）· `core/quota.py`（上传限额）· `core/submission.py`（发布闸门 + 驳回原因）· `core/licensing.py`（许可核验）· `core/capabilities.py`<br>⚠ **真实 OAuth 全流程尚未在真实第三方上验证过** |
| **发布链路** | ✅ **服务端拉源码**：`core/fetch.py`（★ archive 快照方式，`B153`）· ✅ `core/storage.py`（用户存储空间，`B152`）· ✅ `core/publish.py`（发布编排） |
| **UGC** | ⏳ 未做（解释 / 阅读路径 / 提问）—— ⚠ **勋章体系依赖它**（`USERS-AND-AUTH.md` U7.7） |
| **前端** | ⏳ 界面已完成，⚠ **尚未联调**（`frontend/` 目录下暂无源码/产物） |

| | |
|---|---|
| ⏭ **下一步** | ★ **前端联调** —— 后端 33 条路由已就绪；⚠ 另需**真实 OAuth 联调**（需第三方应用凭据） |
| 📌 **对外状态** | ★★ **代码已发布**：`astrolabe-code/astrolabe`（公开仓库，含全部设计文档与决策日志）<br>★★ **已归档**：Zenodo（`10.5281/zenodo.22827012`）· Software Heritage |

### 为什么"第一批要发的代码"就是内核

> ★ **README 是"我说我要做"，代码是"我做了"。**
> 想法不受保护，但**实现（代码）是表达，受版权保护** —— 且能吸引真实的使用与贡献。
> 因此：**不分批等全部做完，内核一跑通就发第一批。**

---

## 五、★ 证据与溯源（★ 对外可核）

| 文件 | 作用 |
|---|---|
| ★★ [`../PROVENANCE.md`](../PROVENANCE.md) | **开发过程溯源** —— 权威决策记录在哪、如何独立核查、内容哈希链 |
| ★★ [`../LICENSE`](../LICENSE) | **权利声明** —— ★ **保留所有权利**（❌ 未采用开源许可证） |
| ★ [`../THIRD-PARTY-NOTICES.md`](../THIRD-PARTY-NOTICES.md) | **第三方组件声明** —— 依赖清单与其许可证 |
| ★ [`../CITATION.cff`](../CITATION.cff) | **引用格式** —— GitHub 据此显示 "Cite this repository" |

★★★ **决策日志本身是最重要的证据** —— ★ 每条含【时间戳 + 要求 + 结论 + 落实位置】，
构成「**要求 → 决定 → 实现**」的可追溯链条 ✅
