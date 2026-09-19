"""Astrolabe · 图：节点与边

★ 依据：
    GRAPH-STORAGE.md  G2（分层查询）· G3（邻接表 + 两个索引）· G3.5（标识体系）
    GRAPH-SCHEMA.md   S2（节点字段）· S3（边字段）

⚠ 一期**不上图数据库**：邻接表 + 递归 CTE 即可（G2）；
  全图算法归 ③ 计算层异步执行（G7）。

★★ 引用一律用【外键】（主键），❌ 不用 uid 字符串 —— 因为 uid 允许重复（B117）。
"""

from django.db import models

from core.models import ProjectRefMixin, TimeStampedModel, UidMixin

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


class Node(ProjectRefMixin, UidMixin, TimeStampedModel):
    """图节点。

    ★ `node_id`（自增主键）= `vid`（`B117`：唯一性由服务器发号保证）
    """

    node_id = models.BigAutoField(primary_key=True)

    kind = models.CharField(max_length=32)
    name = models.CharField(max_length=512)
    qname = models.CharField(max_length=512, blank=True, default="")

    file_path = models.CharField(max_length=1024)
    line = models.IntegerField()
    line_end = models.IntegerField(null=True, blank=True)

    lang = models.CharField(max_length=32)
    signature = models.CharField(max_length=512, blank=True, default="")
    doc = models.TextField(blank=True, default="")

    # ★ 解析产物 or 维护者手工修补（GRAPH-STORAGE.md G1）
    origin = models.CharField(max_length=16, default=ORIGIN_PARSED)

    # ★ 扩展位（GRAPH-SCHEMA.md S1 / S10：语言特有信息）
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        # ⚠ uid 【不加唯一约束】—— B117 明确允许偶发重复
        indexes = [
            models.Index(fields=["project_ref", "file_path"]),
            models.Index(fields=["project_ref", "kind"]),
            models.Index(fields=["project_ref", "lang"]),
        ]

    def __str__(self) -> str:
        return self.uid


class Edge(ProjectRefMixin, TimeStampedModel):
    """图边。

    ★ 单向存一行（不存双向）—— 省一半空间；
    ⚠ 反向查询靠【反向索引】而不是反向行（GRAPH-STORAGE.md G3）。
    """

    from_node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="out_edges")
    to_node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="in_edges")

    type = models.CharField(max_length=32)
    origin = models.CharField(max_length=16, default=ORIGIN_PARSED)

    line = models.IntegerField(null=True, blank=True)
    # ★ 语法级拿不到精确调用图时如实标注（GRAPH-SCHEMA.md S3）
    confidence = models.CharField(max_length=16, blank=True, default="")

    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            # ★★ 两个索引，一个都不能少（G3）
            models.Index(fields=["project_ref", "from_node", "type"]),  # 正向：我调用了谁
            models.Index(fields=["project_ref", "to_node", "type"]),    # ★ 反向：谁调用了我
        ]


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
