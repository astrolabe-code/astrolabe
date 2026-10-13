"""Astrolabe · 图：节点与边

★ 依据：
    GRAPH-STORAGE.md  G2（分层查询）· G3（邻接表 + 两个索引）· G3.5（标识体系）
    GRAPH-SCHEMA.md   S2（节点字段）· S3（边字段）

⚠ 一期**不上图数据库**：邻接表 + 递归 CTE 即可（G2）；
  全图算法归 ③ 计算层异步执行（G7）。

★★ 引用一律用【外键】（主键），❌ 不用 uid 字符串 —— 因为 uid 允许重复（B117）。
"""

from django.db import models

from core.models import TimeStampedModel, UidMixin
# ⚠★ `B179`：`ProjectRefMixin` **不再用于 `Node` / `Edge`** ——
#   ★ 它们的归属已经改成「**基图** or **本项目叠加层**」二选一（⚠ 见 `Node` 的类文档）

# ---- 节点 kind 枚举（GRAPH-SCHEMA.md S2；⚠ 完整枚举待定，见其 S11 #1）----
KIND_FILE = "file"
KIND_DIR = "dir"
KIND_FUNCTION = "function"
KIND_METHOD = "method"
KIND_TYPE = "type"
KIND_MACRO = "macro"
KIND_VARIABLE = "variable"
KIND_CONSTANT = "constant"
KIND_FIELD = "field"

# ---- 边 type 枚举（GRAPH-SCHEMA.md S3；⚠ 完整枚举待定）----
EDGE_CALLS = "calls"
EDGE_IMPORTS = "imports"
EDGE_INCLUDES = "includes"
EDGE_DEFINES = "defines"
EDGE_CONTAINS = "contains"
EDGE_OVERRIDES = "overrides"
EDGE_IMPLEMENTS = "implements"

ORIGIN_PARSED = "parsed"
ORIGIN_MANUAL = "manual"


class BaseGraph(TimeStampedModel):
    """★★★ **基图** —— 一份【具体源码版本】的解析产物（★ `B179` · 2026-10-13）。

    ★★★ 所有者原话（逐字）：

    > 「**解析出来的叫基图数据，存在服务器中，不属于任何一个用户。
    > 用户自己的空间记录的是对基图的修改。显示时，综合基图与修改**」

    ## ★★ 它的身份 = 【托管平台 + 仓库名 + commit sha】

    ★★ 所有者原话：「**基图的数据一定要锚定 github 上的版本，用 sha 之类的，
      也就是说点击基图上的节点，一定要能给出正确的函数位置链接，
      即便仓库作者已经版本迭代，重新提交好几次了**」⚠

    ⇒ ★★★ **三者任一不同 ⇒ 就是另一份基图** ⚠
      ★ 所以【**不能用分支名**】做身份 —— ★ 分支会动（⚠ 同一个分支名，今天和明天是两份不同的代码）⚠
      ★ 用户指定的分支 / tag 只是**输入**（`ref`），★ 它会被**解析成 `sha`** 才是身份 ✅

    ## ★ 寿命：永久保留

    ★★ 所有者原话：「**基图寿命，一直留着，不要做定期清理**」⚠
      ★（★ 理由见该条：图只是签名与调用关系，★ 而拉取频率本身就把量卡住了）

    ## ★ 许可结论存在这一层

    ★ 因为它是**源码版本的性质**（★ 同一个 sha，谁来看结论都一样）⇒
      ★★ 复用它时**不必重新核验** ✅
    """

    provider = models.CharField(max_length=16)
    repo_full_name = models.CharField(max_length=512)

    #: ★★★ **身份的核心** —— 具体到某一个 commit（★ 永久链接就靠它）
    sha = models.CharField(max_length=64)

    #: ★ 用户当时指定的分支 / tag（⚠ 空 ⇒ 用的是默认分支）—— ★ 只作留痕，❌ 不是身份
    ref = models.CharField(max_length=128, blank=True, default="")
    default_branch = models.CharField(max_length=128, blank=True, default="")

    # ---- ★ 许可结论（★ 在基图这一层定一次，复用它的项目不必重复核验）----
    license_decision = models.CharField(max_length=16, blank=True, default="")
    license_reason_code = models.CharField(max_length=32, blank=True, default="")
    license_reason_text = models.CharField(max_length=400, blank=True, default="")
    license_spdx = models.CharField(max_length=64, blank=True, default="")
    license_evidence = models.JSONField(default=dict, blank=True)

    #: ★★ `B176` ④：传染性许可（GPL 等）⇒ **只出节点、不自动生成调用关系** ⚠
    edges_generated = models.BooleanField(default=False)

    #: ★ 规模（★ 省得每次聚合；⚠ 以实际行数为准，这里只是缓存）
    node_count = models.IntegerField(default=0)
    edge_count = models.IntegerField(default=0)

    #: ★ 解析完成时刻（⚠ 空 ⇒ 只有行，还没解析完 —— 见 `built_at`）
    built_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # ★★★ 一份源码版本**只有一份基图** —— ★ 这就是"不重复解析"的落脚点 ✅
            models.UniqueConstraint(
                fields=["provider", "repo_full_name", "sha"], name="uniq_base_graph"
            )
        ]
        indexes = [
            # ★ 拉取前的复用查询：★ 按【仓库 + sha】找（⚠ 上面那个唯一约束已含索引，
            #   这条是给"只想按仓库列全部版本"的用途）
            models.Index(fields=["provider", "repo_full_name"]),
        ]
        verbose_name = "基图"

    def __str__(self) -> str:
        return f"{self.provider}:{self.repo_full_name}@{self.sha[:12]}"

    @property
    def blob_url(self) -> str:
        """★ 某个文件的**永久链接**前缀（★ 拼上路径与行号就能跳转）。

        ⚠★★ `B179`：**调试路径没有 sha**（★ 源码是容器里的一个目录）——
          ★ 那时 `sha` 是占位的 `"local"` ⚠
          ★★ 绝不能拿它拼一个 `…/blob/local/…` 的链接 —— ★ 那是个**点了就 404 的假链接** ⚠
        ⇒ ★★ 所以这里**先验一下 sha 像不像真的 commit**（★ 至少 7 位，⚠ GitHub 短sha 就是 7 位）✅
        """
        sha = (self.sha or "").strip()
        # ⚠ 真 sha：十六进制、≥7 位。★ 占位的 "local" 一律不给链接 ✅
        if len(sha) < 7 or any(ch not in "0123456789abcdefABCDEF" for ch in sha):
            return ""
        if self.provider == "github":
            return f"https://github.com/{self.repo_full_name}/blob/{sha}"
        if self.provider == "gitee":
            return f"https://gitee.com/{self.repo_full_name}/blob/{sha}"
        return ""


class Node(UidMixin, TimeStampedModel):
    """图节点。

    ★ `node_id`（自增主键）= `vid`（`B117`：唯一性由服务器发号保证）

    ## ★★★ `B179`（2026-10-13）：节点**只属于两种地方之一**

    | 归属 | 是什么 | 谁能改 |
    |---|---|---|
    | ★★ `base_graph` 有值 | ★ **基图**里的节点（★ 一份源码版本的解析产物 ⚠）| ⚠★ **谁都不能改**（★ 基图是共享的）|
    | ★★ `project_ref` 非空 | ★ **某个项目自己新增**的节点（★ 叠加层 ⚠）| ★ 该项目维护者 ✅ |

    ⚠★★ **两者【不能同时为空、也不能同时有值】** —— 由 `CheckConstraint` 保证 ⚠

    ⚠★ 对**基图节点**的「改 / 删」**不落在本表** —— ★★ 而是落 `GraphPatch` ⚠
      ★ 因为基图是**所有用户共享**的：★ A 直接改一下，★ B 看到的就变了（★ 那是串号，⚠ 不是修改）⚠
    """

    node_id = models.BigAutoField(primary_key=True)

    # ---- ★ 归属（★ 恰好一个有值，见类文档）----
    base_graph = models.ForeignKey(
        BaseGraph, null=True, blank=True, on_delete=models.CASCADE, related_name="nodes"
    )
    project_ref = models.CharField(max_length=64, blank=True, default="", db_index=True)

    kind = models.CharField(max_length=32)
    name = models.CharField(max_length=512)
    qname = models.CharField(max_length=512, blank=True, default="")

    file_path = models.CharField(max_length=1024)
    line = models.IntegerField()
    line_end = models.IntegerField(null=True, blank=True)

    lang = models.CharField(max_length=32)
    signature = models.CharField(max_length=512, blank=True, default="")
    # ⚠★★ `B176`（2026-10-12）：**本处曾有一个 `doc = TextField()`（注释 / 文档串）** ——
    #   ★★ 它是节点里**唯一逐字的代码内容**（★ 前导注释可能整段被抄下来）⚠
    #   ★ 所有者裁定：「**节点里只保存函数签名以及他所在的文件**，
    #      ★ 解析成功之后立刻删除（源码）」⇒ ★ **删掉这个字段** ✅
    #   ★ 于是节点只剩：【文件名 + 行号 + 签名 + 元数据】—— ★ **不含任何逐字代码** ✅
    #   ★ 依据：`docs/backend-decisions.md` `B176`

    # ⚠★ `B179`：**本处曾有一个 `origin` 列（parsed / manual）** —— ★ 现在它**不再建列** ⚠
    #   ★★ 因为归属已经决定了它：★ 基图行【必然】是 `parsed`、
    #     ★ 项目新增行【必然】是 `manual` ⇒ ★ 存一列就是存冗余 ⚠
    #   ★ 而**对外接口照旧给 `origin`**（★ 前端靠它做视觉标记）——
    #     ★★ 由 `graph/compose.py` 在读取时**算**出来 ✅

    # ★ 扩展位（GRAPH-SCHEMA.md S1 / S10：语言特有信息）
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        # ⚠ uid 【不加唯一约束】—— B117 明确允许偶发重复
        indexes = [
            # ★ 基图侧（★ 按 sha 命中的那份基图，★ 读它的节点）
            models.Index(fields=["base_graph", "file_path"]),
            models.Index(fields=["base_graph", "kind"]),
            models.Index(fields=["base_graph", "lang"]),
            # ★ 叠加层侧（★ 某个项目自己加的节点）
            models.Index(fields=["project_ref", "file_path"]),
            models.Index(fields=["project_ref", "kind"]),
        ]
        constraints = [
            # ★★★ 恰好属于一个地方（★ 见类文档）⚠
            models.CheckConstraint(
                condition=(
                    models.Q(base_graph__isnull=False, project_ref="")
                    | (models.Q(base_graph__isnull=True) & ~models.Q(project_ref=""))
                ),
                name="node_belongs_to_exactly_one",
            )
        ]

    def __str__(self) -> str:
        return self.uid


class Edge(TimeStampedModel):
    """图边。

    ★ 单向存一行（不存双向）—— 省一半空间；
    ⚠ 反向查询靠【反向索引】而不是反向行（GRAPH-STORAGE.md G3）。

    ★★ 归属与 `Node` **同一套规则**（★ `B179`）：★ 要么属于【基图】、要么属于【某项目的叠加层】⚠
    """

    from_node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="out_edges")
    to_node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="in_edges")

    # ---- ★ 归属（★ 恰好一个有值 —— 与 `Node` 同口径）----
    base_graph = models.ForeignKey(
        BaseGraph, null=True, blank=True, on_delete=models.CASCADE, related_name="edges"
    )
    project_ref = models.CharField(max_length=64, blank=True, default="", db_index=True)

    type = models.CharField(max_length=32)
    # ⚠★ `B179`：**本处曾有一个 `origin` 列** —— ★ 同 `Node`，归属已决定它，❌ 不再建列 ⚠

    line = models.IntegerField(null=True, blank=True)
    # ★ 语法级拿不到精确调用图时如实标注（GRAPH-SCHEMA.md S3）
    confidence = models.CharField(max_length=16, blank=True, default="")

    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            # ★★ 两个索引，一个都不能少（G3）
            models.Index(fields=["base_graph", "from_node", "type"]),  # 正向：我调用了谁
            models.Index(fields=["base_graph", "to_node", "type"]),    # ★ 反向：谁调用了我
            models.Index(fields=["project_ref", "from_node", "type"]),
            models.Index(fields=["project_ref", "to_node", "type"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(base_graph__isnull=False, project_ref="")
                    | (models.Q(base_graph__isnull=True) & ~models.Q(project_ref=""))
                ),
                name="edge_belongs_to_exactly_one",
            )
        ]


# ---- ★ 修改动作（★ 与 `graph/curate.py` 的六种动作**同一套字面值**）----
PATCH_ADD_NODE = "add_node"
PATCH_UPDATE_NODE = "update_node"
PATCH_REMOVE_NODE = "remove_node"
PATCH_ADD_EDGE = "add_edge"
PATCH_UPDATE_EDGE = "update_edge"
PATCH_REMOVE_EDGE = "remove_edge"

PATCH_ACTIONS = (
    PATCH_ADD_NODE,
    PATCH_UPDATE_NODE,
    PATCH_REMOVE_NODE,
    PATCH_ADD_EDGE,
    PATCH_UPDATE_EDGE,
    PATCH_REMOVE_EDGE,
)


class GraphPatch(TimeStampedModel):
    """★★ **用户对基图的修改**（★ `B179` · 2026-10-13）。

    ★★★ 所有者原话（逐字）：

    > 「**用户自己的空间记录的是对基图的修改。显示时，综合基图与修改**」

    ## ⚠★★ 为什么**不能**直接改基图行

    ★ 基图是**所有用户共享**的 ⚠ ——
      ★★ A 改一下，★ B 看到的就变了（★ 那是"**串号**"，⚠ 不是"修改"）⚠
    ⇒ ★★★ 所以修改**一律落在这里** ✅

    ## ★★★ 服务端**不负责**整合（★ 所有者 2026-10-13 裁定）

    ★★ 所有者原话（逐字）：

    > 「**基图与用户修改存在不同模型里，请求时，直接请求这两份数据，
    > 前端负责整合**，这就要求节点索引一定要设计好，能迅速对比出修改的部分，
    > **不是在服务器上整合了，再发出去**哦。」

    ⇒ ★★★ **接口发的是【两份数据】**：★ 基图一份 · ★ 本表一份 ⚠
      ★★ **合成发生在前端** —— ★ **服务端【绝不做】"基图 + 修改"的合并** ⚠

    ## ★★ 由此对索引的硬要求

    ★ 因为"比对"在前端做，★ **服务端必须让它便宜** ——
      ★★ 前端按【基图节点的 `vid`】去本表找改动 ⇒
        ★★★ 所以本表**必须能按 `(project_ref, target_node)` 直查**（★ 见 `Meta.indexes`）⚠

    ## ★ 六种动作分别落在哪

    | 动作 | 本表里的样子 | 内容在哪 |
    |---|---|---|
    | ★ `add_node` | ★ `target_node` 指向**一个新发的 `Node` 行**（★ 它带 `project_ref`）| ★ 就在那个 `Node` 行里（⚠ 不重复存）|
    | ★ `update_node` / `remove_node` | ★ `target_node` 指向**基图节点** + `payload` 覆盖内容 | ★ `payload` |
    | ★ `add_edge` / `update_edge` / `remove_edge` | ★ `target_edge`（改/删）或 `from_node`/`to_node`（增） | ★ `payload` |
    """

    project_ref = models.CharField(max_length=64, db_index=True)

    action = models.CharField(max_length=16, choices=[(a, a) for a in PATCH_ACTIONS])

    #: ★ 被改 / 被删的【基图】节点（⚠ `add_node` 不落这里 ⇒ 必为 NULL）
    target_node = models.ForeignKey(
        Node, null=True, blank=True, on_delete=models.CASCADE, related_name="patches"
    )
    #: ★ 被改 / 被删的【基图】边
    target_edge = models.ForeignKey(
        Edge, null=True, blank=True, on_delete=models.CASCADE, related_name="patches"
    )
    #: ★ 新增 / 改边时的两端（★ 可以是基图节点，也可以是本项目新增的节点）
    from_node = models.ForeignKey(
        Node, null=True, blank=True, on_delete=models.CASCADE, related_name="patch_out"
    )
    to_node = models.ForeignKey(
        Node, null=True, blank=True, on_delete=models.CASCADE, related_name="patch_in"
    )

    #: ★ 内容（★ 字段与 `graph/curate.py::_NODE_FIELDS` / `_EDGE_FIELDS` **同一口径**）
    payload = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=400, blank=True, default="")

    #: ★ 审计（`B103`：谁改的、什么时候 —— 出事时要能追到人）
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="graph_patches"
    )

    class Meta:
        indexes = [
            # ★★★ 前端比对的关键索引：★ 按【项目 + 目标节点】直查出改动 ⚠
            #   ★ 所有者原话：「**这就要求节点索引一定要设计好，能迅速对比出修改的部分**」
            models.Index(fields=["project_ref", "target_node"]),
            models.Index(fields=["project_ref", "target_edge"]),
            models.Index(fields=["project_ref", "action"]),
            models.Index(fields=["project_ref", "-created_at"]),
        ]
        verbose_name = "图修改"

    def __str__(self) -> str:
        return f"{self.project_ref}:{self.action}"


class ProjectBaseGraph(TimeStampedModel):
    """★★ **哪个项目用的是哪一份基图**（★ `B179` · 2026-10-13）。

    ★★ 所有者原话（逐字）：

    > 「**用户拉一个图就解析一次，太浪费算力，应该是，拉去之前，看看现有的图数据里
    > 有没有同样的，有同样的，就直接返回，不拉取，不解析，还快。**」

    ⇒ ★★ 这一行就是"**直接返回**"的落脚点：★ 项目建好之后**绑定**到一份基图 ⚠

    ## ⚠★★ 为什么单独一张表（❌ 不在 `core.Project` 上加外键）

    ★★ 依赖方向是 **`graph` → `core`** ——
      ⚠ 在 `core` 上挂 `graph` 的外键，会把这根箭头**绕成一个圈** ⚠
    ⇒ ★★ 所以"绑定关系"由 `graph` 这边记 ✅（★ 项目那边**一个字都不用改**）
    """

    project_ref = models.CharField(max_length=64, primary_key=True)
    base_graph = models.ForeignKey(
        BaseGraph, on_delete=models.CASCADE, related_name="projects"
    )
    #: ★ 用户当时指定的分支 / tag（★ 空 ⇒ 用的是默认分支）
    requested_ref = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["base_graph"])]
        verbose_name = "项目↔基图"

    def __str__(self) -> str:
        return f"{self.project_ref} → {self.base_graph_id}"


class GraphRevision(models.Model):
    """★ 图版本号 —— **邻域缓存的「命名空间代际」**（`GRAPH-STORAGE.md` G5）。

    ★★ 为什么它是「缓存失效」的正确解法：

    | 做法 | 评价 |
    |---|---|
    | ❌ 修补图后 `SCAN` 出所有邻域 key 逐个删 | Redis 全库遍历**会阻塞主线程**，键越多越慢 |
    | ✅ **把版本号写进 key** | 图一变 ⇒ `rev + 1` ⇒ ★ **旧代际的 key 立刻不可达**，由 TTL 自然消亡 |

    ⇒ ★ 代价 **O(1)**，**不需要任何删除操作**。

    ⚠ **权威方是数据库，不是 Redis**：
      Redis 重启会丢数据 —— 若 rev 存在 Redis，就可能出现「rev 回退 ⇒ 旧缓存被当成新的」。
      存在 DB 里则：① `bump` 与写图**在同一个事务**内（★ 不会有"图新了、rev 还旧"的窗口）；
      ② Redis 丢数据也**不会让 rev 回退**。

    ⚠ 图**几乎不变**（`B103`：图不可变）—— 唯一变化来源是**维护者手工修补**（G1）
      ⇒ rev 自增**极其罕见**。
    """

    project_ref = models.CharField(max_length=64, primary_key=True)
    rev = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "图版本号"

    def __str__(self) -> str:
        return f"{self.project_ref}@r{self.rev}"


class NodeHeat(models.Model):
    """★ 节点热度的**权威累计值**（`B128` 待办的落点）。

    ★★ 为什么一定要有这张表：Redis 里的计数是**热数据** ——
      ⚠ **Redis 重启就没了**。数据库才是权威累计值。

    | 层 | 角色 |
    |---|---|
    | Redis ZSET | **增量缓冲**（每请求一次 `ZINCRBY`，极轻） |
    | ★ 本表 | **权威累计**（由 `graph/heat.py` 定期合并） |

    ★ **按 `uid` 而不是 `vid`**（`B128`）：`vid` 是发号（`B117`），
      ⚠ **不保证跨次解析相同** —— 按 vid 存，重新解析一次热度就全废。
      ⚠ 代价：uid 允许重复 ⇒ **同名节点合并计数**（对"热度"这个用途可接受）。

    ⚠ 节点被删除后**本表不删**（历史热度仍有价值）；展示时与当前图 join 即可。
    """

    project_ref = models.CharField(max_length=64)
    #: ★ 指标（visit / notes / comments …）—— 多指标分列，最终热度由上层加权合成
    metric = models.CharField(max_length=32)
    uid = models.CharField(max_length=1024)
    value = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project_ref", "metric", "uid"], name="uniq_node_heat"
            )
        ]
        indexes = [
            # ★ 热力图查询：某项目某指标按热度倒序取 TOP N
            models.Index(fields=["project_ref", "metric", "-value"]),
        ]
        verbose_name = "节点热度"

    def __str__(self) -> str:
        return f"{self.uid}@{self.metric}={self.value}"


class HeatFlush(models.Model):
    """★ 热度合并的**幂等闸门** —— 同一批增量**只能被累加一次**。

    ⚠ 为什么必须有它：
      合并流程是「轮换 → 读 → 写库 → 删临时 key」。
      如果进程在**写库之后、删 key 之前**崩掉 ⇒ 下次重跑会捡回同一个批次
      ⇒ ⚠ **重复累加**（热度虚高，且越重启越离谱）。
      ★ 有了这张表：写库与"记录已处理"在**同一个事务**里，重跑直接跳过。

    ⚠ 代价如实记录：进程若在**写库之前**崩，那批计数会被重跑补上（正常）；
      真正的边界情况是「批次内有部分 uid 已写入」—— 因为写库与闸门同事务，不会发生。
    """

    #: ★ 批次标识 = Redis 里那个临时 key 的名字（天然唯一）
    flush_key = models.CharField(max_length=512, primary_key=True)
    project_ref = models.CharField(max_length=64)
    metric = models.CharField(max_length=32)
    rows = models.IntegerField(default=0)
    total = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["project_ref", "metric"])]
        verbose_name = "热度合并批次"

    def __str__(self) -> str:
        return self.flush_key
