"""Astrolabe · 共享内核：标识体系

★ 三层标识（`B117` · `GRAPH-STORAGE.md` G3.5）：

    node_id   服务器内部主键（PG 发号，★ 绝对唯一）
    vid       ★ 对外 + 锚点挂载（绝对唯一）—— 一期 = node_id
    uid       ★ 人类可读标签（⚠ **允许偶发重复**，❌ **不用于引用**）

★★ 核心规律（`B117`）：**「能重复的只用来看；不能重复的才用来挂。」**

⚠ 因此：
  · 图节点 / 边的引用一律用【主键外键】，❌ 不用 uid 字符串
  · 锚点挂 vid（= node_id），❌ 不得挂 uid
"""

from django.conf import settings
from django.db import models

from core.refs import new_project_ref


class TimeStampedModel(models.Model):
    """公共时间戳（审计用）。"""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ProjectRefMixin(models.Model):
    """按项目隔离的公共字段。

    ⚠ `project_ref` 由路由 / 视图层校验（严格 `^proj_[0-9a-f]{32}$`），
       且**必须由 auth / project 注入**，❌ 图与搜索模块不得自行判定。
    """

    # ⚠ 长度 64（而非旧的 32）—— 旧设计里 project_ref 是 sha256_16 的 hex（32 位），
    #   而现在 `vid` 改为服务器发号（B117），project_ref 不再与哈希绑定，
    #   需要容纳 `proj_<32 hex>`（37 位）这类人类可读的标识。
    project_ref = models.CharField(max_length=64, db_index=True)

    class Meta:
        abstract = True


class UidMixin(models.Model):
    """人类可读标签（★ 允许重复 —— 见本文件顶部说明）。"""

    uid = models.CharField(
        max_length=1024,
        db_index=True,
        help_text="人类可读标签：<kind>#<相对路径>#<名字>#<重载键>（⚠ 允许重复）",
    )

    class Meta:
        abstract = True


class Project(TimeStampedModel):
    """项目 —— ★ 图 / 作业 / UGC **全部挂在它上面**。

    ★ 为什么放在 `core`（共享内核）而不是新开一个 app：
      ① ② 都要用它（Web 层判权限、作业层拉源码解析），且它**不含任何层特有逻辑**。

    ⚠ **何时该拆出去**：等它长出「成员 / 协作者 / 发布审批 / 许可分级」等子系统时，
      再拆成独立的 `projects` app。★ 现在拆是**过度设计**。
    """

    # ------------------------------------------------------------------ 标识
    #: ★ 对外唯一标识（形态 `^proj_[0-9a-f]{32}$`，见 `core/refs.py`）
    #: ⚠ **不可变** —— 改名**不换** ref（图 / 锚点 / 邻域缓存 / 公开链接都挂在它上面）
    project_ref = models.CharField(
        max_length=64, unique=True, editable=False, default=new_project_ref
    )
    # ⚠★★ 2026-10-14（`B192`）：**从 200 缩到 120** ⚠
    #   ★★ 因为它进了**联合唯一索引** `UNIQUE (owner, name)` ——
    #     ★ 索引的体积**直接由这里决定** ⚠
    #   ★ 实测：★ 现有的名字**最长 19 字**、★ 平均 **4 字** ⇒ ★ **缩了碰不到任何数据** ✅
    name = models.CharField(max_length=120)
    desc = models.TextField(blank=True, default="")

    #: ⚠ **可为空**（有意）：公开项目在被**原作者认领**之前，owner 可以是平台代管。
    #: 认领是路线图里的「社区纠错 · 原作者认领」。
    # ⚠★★ 2026-10-14（`B198`）：**`null=True` 去掉，★ 删除行为改为 `PROTECT`** ⚠
    #
    # ★★ 所有者原话（逐字）：「**没有平台代管项目**」
    #
    # · ★ 原先可空的理由是「公开项目在被**原作者认领**之前，owner 可以是平台代管」
    #   ★★ 而那条路线**不存在了** ⇒ ★ 项目**一定属于某个用户** ✅
    # · ★★ `SET_NULL` → **`PROTECT`**：★ 有项目就**不许删号** ⚠
    #   （★ 否则会留下无主项目 —— ★ 而那正是"可空"想解决的问题）⚠
    #   ⇒ ★ 要注销 ⇒ ★ 必须**先显式处置**它的项目（★ 删 / 转移）——
    #     ★★ 那是**明面动作**，❌ 不是静默置空 ✅
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="projects",
    )


    # ------------------------------------------------------------------ 绑定的基图
    # ⚠★★ 2026-10-14（`B179` 第二步）：**把 `graph_projectbasegraph` 那张表并进来** ⚠
    #
    # ★★ 为什么可以并（★ 这是对旧理由的一次核实）：
    #   · ★ 旧 docstring 说「依赖方向 graph → core，★ 在 core 上挂 graph 的外键会绕成一个圈」⚠
    #   · ★★ 而**实测**：★ `core/models.py:217` 与 `core/publish.py:500`
    #     **已经在 `from graph import binding`** ⚠
    #   · ★★ 而架构文档 `ARCHITECTURE.md` A3 管的是【层】（Web/作业/计算/共享内核）——
    #     ★ `core` 与 `graph` **同属共享内核** ✅
    #   ⇒ ★★ 所以那个"绕圈"的理由**不成立** ✅
    #
    # ★★ 而**一个项目只绑一份基图** ⇒ ★★ 一张外键就够了，* 白多一张表 ⚠
    #   · ★ 少一个可能产生**孤儿行**的地方 ✅
    #   · ★★ `is_graph_built` 可以**直读外键**（★ 不再每个项目查一次）✅
    #
    # ⚠★ 为什么用**字符串引用** `"graph.BaseGraph"`：
    #   ★★ 这样 `core/models.py` **不需要 import graph** ⇒ ★ 连"可能成圈"的念头都没有 ✅
    #   （★ Django 会延迟解析它 ✅）
    #
    # ⚠★ 为什么 `on_delete=PROTECT`：
    #   · ★ 基图是**所有项目共享**的（`B179`）⚠
    #   · ★★ 删一份**还有人绑着**的基图 ⇒ ★★ 那些项目的图会凭空消失 ⚠
    #   · ★ 而所有者裁定基图「**一直留着，不要做定期清理**」✅
    #   ⇒ ★★ 所以：★ 要删基图 ⇒ **先显式解绑**（★ 那是明面动作）✅
    #   ★（★ 第 1 批删那 15 份冒烟基图时，* 正是**先摘绑定再删**才没出事的 ✅）
    base_graph = models.ForeignKey(
        "graph.BaseGraph",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    # ------------------------------------------------------------------ 可见性
    #: ★ 公开 = 任何人可读（含游客）；私有 = 仅 owner
    is_public = models.BooleanField(default=False)

    # ------------------------------------------------------------------ 状态
    # ★★ `U3.5`：**「隐藏」与「下架」是两个不同力度的动作**，⚠ 混用会出问题
    STATE_ACTIVE = "active"
    #: ★ **隐藏（unlist）** —— 从列表 / 搜索 / 首页消失，★ **直接链接仍可访问**
    #: ★ 用于「**存疑但未定论**」（收到举报、还在核查）
    STATE_HIDDEN = "hidden"
    #: ★★ **下架（takedown）** —— **彻底不可访问**（→ 404）
    #: ★ 用于「**确认侵权**」
    STATE_TAKEN_DOWN = "taken_down"
    STATE_CHOICES = [
        (STATE_ACTIVE, "正常"),
        (STATE_HIDDEN, "已隐藏"),
        (STATE_TAKEN_DOWN, "已下架"),
    ]
    state = models.CharField(
        max_length=16, choices=STATE_CHOICES, default=STATE_ACTIVE, db_index=True
    )

    # ------------------------------------------------------------------ 付费
    # ★★ `U9.4` 一期：**只做"付费可见性判定"，❌ 不做支付**
    #: ★ 标记这个项目里有需要付费才能看的**讲解**（★ 代码与图**永远免费**，`U9.2`）

    # ------------------------------------------------------------------ 许可核验
    # ★ 依据 `core/licensing.py`（`U3.4` / `B143`）

    # ------------------------------------------------------------------ 审核
    REVIEW_NONE = "none"
    REVIEW_PENDING = "pending"
    REVIEW_APPROVED = "approved"
    REVIEW_REJECTED = "rejected"
    REVIEW_STATE_CHOICES = [
        (REVIEW_NONE, "无需审核"),
        (REVIEW_PENDING, "待审核"),
        (REVIEW_APPROVED, "已通过"),
        (REVIEW_REJECTED, "已拒绝"),
    ]
    #: ★ 审核状态 —— ★ 详情在 `ProjectReview`（它承载**"为什么进审核"**）
    review_state = models.CharField(
        max_length=16, choices=REVIEW_STATE_CHOICES, default=REVIEW_NONE, db_index=True
    )

    # ------------------------------------------------------------------ 处置留痕
    # ⚠★★ 2026-10-15（`B196`）：**三列** ⚠
    #
    # ★★ 所有者原话（逐字）：
    #   「**还有把这个项目下架，隐藏之类的功能，这对于网上展示内容的平台很重要。**」
    #
    # ★★ 为什么必须有（* 缺它的后果）：
    #   · ★ `state` 只有"现在是什么状态"，* **没有原因** ⚠
    #   · ★★ 作者来问"**为什么下架我**"⇒ ★ **答不出来** ⚠
    #
    # ★★ 为什么放在项目行上（* 而不是另建一张处置流水表）：
    #   · ★ `state`（* `hidden` / `taken_down`）**本来就在这张表上** ⚠
    #   · ★★ 理由与它是**同一条事实的组成部分** ⚠
    #   · ★ 作者要看它 ⇒ ★ 一次查询就够（* ❌ 不用再 join 一张表）✅
    #   · ⚠★ 代价：* 只能存**最近一次** ⇒ ★ 多次处置的历史靠 `AuditLog` ⚠
    #     （* 它的注释里早就预留了 `project.takedown` 这个 action ✅）

    #: ★★ **最近一次处置的理由**（★ 管理员处置时写）· ★ 空串 = 没处置过
    moderation_reason = models.CharField(max_length=400, blank=True, default="")

    #: ★ **谁做的这次处置**（★ FK → `auth_user`）· ★ NULL = 没处置过
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="moderated_projects",
    )

    #: ★ **什么时候处置的** · ★ NULL = 没处置过
    moderated_at = models.DateTimeField(null=True, blank=True)

    # ------------------------------------------------------------------ 图定版
    # ★★★ **图一旦生成就【定版】—— 此后不可再解析**（`B103` / `B155`）。
    #
    # > **用户原话**：「代码解析完成之后**应该不允许重新解析**。因为，我要求
    # > **图数据不能频繁、大面积改动**，**代码也不能改动**，否则，
    # > **解释里的"几行到几行"就失效了**。你要解析另一个版本的，那就**重新建一个项目**。
    # > 觉得解析质量太差，那就**删了项目重新建一个**。」
    #
    # ★★★ 这条约束的**根本原因是锚点**（`B98` 的 L0）：
    #   ★ 解释 / 提问 / 阅读路径都**挂在「文件 + 行区间」上** —— ⚠ 一旦重新解析、
    #     代码换了版本，那些行号**全部错位**，★ 而**没有任何机制能自动发现**。
    #   ⇒ ★★ 所以"图不可变"**不是性能优化，是数据完整性的前提**。
    #
    # ★ 两条出路（★ 用户明确给的）：
    #   · 要**另一个版本** ⇒ ★ **新建一个项目**（★ 两个版本并存，各自的解释不互相破坏）
    #   · 觉得**质量太差** ⇒ ★ **删了重建**（★ 删除会连带释放存储 —— `B152`）
    #
    # ⚠★ 它也是 `Project.review_state == pending` 时"还没解析"的**权威判据** ——
    #   ★ 比"数一下有几个节点"可靠（★ 后者是**副作用**，⚠ 会被任何一次清空误导）。


    # ------------------------------------------------------------------ 定版判据
    @property
    def is_graph_built(self) -> bool:
        """★★ **图是否已定版** —— ★ 定版后**不可再解析**（`B103` / `B155`）。

        ⚠★★ 2026-10-14（`B179` 第二步 / `B197`）：**改为派生** ⚠

        ## ★★ 为什么改

        ★ 原先它读 `Project.graph_built_at` —— ★ 而那一列与
          `BaseGraph.built_at` 是**同一条事实的两份** ⚠
        ★★ 而"两份"迟早不一致（★ 实测踩过：★ 图建好了，★ 项目那边还是 None）⚠

        ## ★ 现在的判据

        ★★ `base_graph_id` 有值 **且** 那份基图**已建好** ✅

        ⚠★ 一次性会把 `base_graph` 取回来（★ Django 的关系访问）——
          ★★ 列表页请传 `_built_flags()` 预载的那个值（★ 见 `web/views/projects.py`）⚠
        """
        return (
            self.base_graph_id is not None
            and self.base_graph is not None
            and self.base_graph.built_at is not None
        )

    class Meta:
        constraints = [
            # ⚠★★ 2026-10-14（`B192`）：**同一用户下不许建同名项目** ⚠
            #
            # ★★ 所有者原话（逐字）：「**同一个用户下建的项目是不允许同名的**」
            #
            # · ★ 为什么需要它：★ 现有唯一约束只有 `project_ref`（★ 那是随机 UUID）
            #   ★★ 于是同一个用户可以建**无数个同名项目** ⚠
            #   ⇒ ★ 列表里分不清、★ 且容易误建 ⚠
            # · ★ 前提由 `B198` 保证：★ `owner` 已改为 **NOT NULL** ⇒
            #   ★★ 这条约束对**所有项目**都生效（★ 不再有"平台代管"那类空属主）✅
            # · ⚠★ **代价（★ 如实记）**：★ 它引入一棵 `(int, varchar(120))` 的索引
            #   ★★ 而 `name` 正是为此从 200 缩到 **120** 的 ⚠
            models.UniqueConstraint(
                fields=["owner", "name"], name="uniq_owner_project_name"
            ),
        ]
        indexes = [
            models.Index(fields=["is_public", "-created_at"]),
            models.Index(fields=["owner", "-created_at"]),
            # ★ 审核队列：按状态 + 时间（★ 管理员的待办清单）
            models.Index(fields=["review_state", "-created_at"]),
        ]
        verbose_name = "项目"

    # ------------------------------------------------------------------
    # ⚠★★ 2026-10-14（`B197`）：**源码相关信息全部改为【从基图派生】** ⚠
    #
    # ★★ 所有者原话（逐字，见原话区 A15）：
    #   「**项目表与基图表很多字段是重复的，你不觉得有问题吗？把重复的删掉，
    #     只存在基图表里，前端需要这些信息的话访问基图表就行了。**」
    #
    # ⇒ ★★ 于是删掉了这 7 列：
    #   `provider` · `repo_url` · `license_spdx` · `license_category` ·
    #   `license_exception` · `license_evidence` · `resolved_ref`
    #
    # ★★ 而**接口契约不能变**（★ 前端照旧收这些字段）⇒
    #   ★ 所以这里用**同名属性**把它们接回来，* 值全部来自 `base_graph` ✅
    #
    # ⚠★ 三个必须说清的点：
    #
    # ① ★★ **只读** ⚠ —— ★ 它们没有 setter，* 赋值会 `AttributeError`
    #   · ★ 那是**故意的**：★ 写它们就等于"在两处各写一份" ⚠
    #   · ★★ 要改 ⇒ ★ 改基图那一行（* 唯一权威）✅
    #
    # ② ★★ **没绑基图时全部为空** ⚠
    #   · ★ 笔记型项目（★ `base_graph` 为 NULL）**本来就没有源码** ⚠
    #   · ★ 而那**不是缺数据** —— ★ 是这类项目的**正常状态** ✅
    #   · ★★ 判据只有一个：★ `base_graph_id` 是否为空 ✅
    #
    # ③ ★★ **一次属性访问 = 一次关系查询** ⚠
    #   · ★ 列表页请走 `select_related("base_graph")`（* 一次 join）✅
    #   · ★★ 否则 N 个项目 = N 次查询 ⚠
    # ------------------------------------------------------------------
    @property
    def provider(self) -> str:
        """★★ **这份源码从哪个平台拉的**（★ 派生）。空 = 没绑基图。"""
        return (self.base_graph.provider or "") if self.base_graph_id else ""

    @property
    def repo_url(self) -> str:
        """★★ **源码仓库地址**（★ 派生，如 `https://github.com/owner/repo`）。

        ★ 由 `provider` + `repo_full_name` **拼出来** —— ★ 这正是"可推导的不该存" ✅
        ★（★ 与 `core/publish.py::_repo_url()` 同一口径 ✅）
        """
        if not self.base_graph_id:
            return ""
        host = {"github": "github.com", "gitee": "gitee.com"}.get(
            self.base_graph.provider or ""
        )
        full = (self.base_graph.repo_full_name or "").strip().strip("/")
        return f"https://{host}/{full}" if host and full else ""

    @property
    def resolved_ref(self) -> str:
        """★★ **真正解析到的那一版 ref**（★ 派生）。空 = 没绑 / 没记。"""
        return (self.base_graph.ref or "") if self.base_graph_id else ""

    # ---- 许可（★ 权威全在基图 ✅）----
    @property
    def license_spdx(self) -> str:
        return (self.base_graph.license_spdx or "") if self.base_graph_id else ""

    @property
    def license_category(self) -> str:
        """⚠★ 语义变了：★ 原先这一列是"分类"，* 现在派生自基图的**原因码** ✅"""
        if not self.base_graph_id:
            return ""
        return (self.base_graph.license_reason_code or "")[:16]

    @property
    def license_exception(self) -> bool:
        """★★ **许可是否有例外**（★ 派生）。★ 判据 = 基图的决定不是 `allow` ✅"""
        if not self.base_graph_id:
            return False
        return (self.base_graph.license_decision or "") != "allow"

    @property
    def license_evidence(self) -> dict:
        return (self.base_graph.license_evidence or {}) if self.base_graph_id else {}

    def __str__(self) -> str:
        return f"{self.name}（{self.project_ref}）"


class ProjectReview(TimeStampedModel):
    """★ 项目审核记录 —— ★★★ **核心要求：必须能回答「为什么进审核」**（`U3.7`）。

    > **用户原话**：「★★★ 所以，**审核里一定要显示表明为什么进审核**。」

    ★★ 用户为什么强调这一点（`U3.7`）：

    | # | 理由 |
    |---|---|
    | **1** | ★ 管理员需要**判断依据** —— ⚠ 否则只能凭感觉 |
    | **2** | ★★ **审计需要** —— 将来回头看"**为什么放行了这个**" |
    | **3** | ★★★ **这也是法律保护** —— ★★ **"平台做了判断"比"平台没看就放行"好得多** |

    ★★★ 而最根本的一句（`U3.7`）：

    > **「人工审核通过」≠「平台背书版权」** —— ★ 它只表示
    > ★ **「在已知信息下，未发现明显问题」**。
    > ⇒ ★★ 所以**必须写清"我们看了什么、依据什么决定的"**。

    ⚠ **一次审核 = 一条记录**（❌ 不是往 `Project` 上塞一个状态字段）——
      ★ 因为同一项目**可能被审多次**（补了许可证后重审），★ 历史必须留得住。

    ★★★ **本表同时承担第二个职责：上传限额的「流水账」**（`U3.9`）。

    ⚠★ 为什么必须由它来计数（❌ 不能直接数 `Project` 表）：

    | 做法 | 结果 |
    |---|---|
    | ❌ 数 `Project` 表 | ★★ 用户**把项目删掉再传一次**就能**绕过限额** |
    | ✅ 数本表的流水 | ★★ 流水是 **append-only**，删项目**删不掉**它 |

    ⚠★ 所以 `project` 用的是 **`SET_NULL`（不是 `CASCADE`）** +
      ★ 冗余的 `project_ref` / `project_name`：
      ⇒ ★★ **项目删了，流水还在**，限额**绕不过去**。
    """

    DECISION_PENDING = "pending"
    DECISION_APPROVED = "approved"
    DECISION_REJECTED = "rejected"
    DECISION_CHOICES = [
        (DECISION_PENDING, "待审核"),
        (DECISION_APPROVED, "放行"),
        (DECISION_REJECTED, "拒绝"),
    ]

    #: ⚠★ **`SET_NULL` 而非 `CASCADE`** —— ★★ 见类文档：删项目**不得**抹掉限额流水
    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviews"
    )
    #: ★ 冗余：项目被删后**流水仍然可读**（后台 / 用户都能看懂这条记录是什么）
    project_ref = models.CharField(max_length=64, blank=True, default="", db_index=True)
    project_name = models.CharField(max_length=200, blank=True, default="")

    # ------------------------------------------------------------------
    # ⚠★★ 2026-10-15（`B196`）：**申诉两列** ⚠
    #
    # ★★ 所有者原话（逐字）：
    #   「**review_state是审核状态，审核是很重要的，而且，你的表里缺少了审核不通过的
    #     理由和作者的申诉理由等**」
    #
    # ★★ 为什么加在【本条流水】上，* 而不是项目表：
    #   · ★ 申诉**天然是"对某一次决定"的回应** ⇒ ★ 它属于**那条记录** ⚠
    #   · ★★ 若放项目表 ⇒ ★ 只能存**最后一次** ⇒ ★ 历史丢失 ⚠
    #   · ★ 而 `B146` 已裁定本表 **append-only** ⇒ ★ 每一轮都是新的一条 ✅
    #     ⇒ ★ 于是"申诉链"天然记下来（* 一环指一环）✅
    #
    # ⚠★ 为什么不加 `appealed_at`：★ 那条新记录自己的 `created_at` 就是申诉时刻 ⚠
    #   （* 避免"同一条事实两列"—— * 正是被批过的毛病）⚠
    # ------------------------------------------------------------------

    #: ★★ **作者对"被拒"的申辩**（★ 他为什么觉得该放行）· ★ 空串 = 这次不是申诉
    appeal_note = models.TextField(blank=True, default="")

    #: ★★ **这次提交是在申诉【哪一次】决定**
    #: ★ FK → 本表自身（* 自引用）。★ NULL = 不是申诉
    #: ⚠★ `SET_NULL` 而不是 CASCADE：* 被申诉那条若被删，* 本条**不该跟着消失** ⚠
    appeal_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appeals",
    )

    # ---------------------------------------------------------------- 提交人
    #: ★ **谁提交的** —— ★★ 限额按它计数（`U3.9`）
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_reviews",
    )
    #: ★ 冗余用户名 —— ⚠ 用户注销后**流水仍能读懂**（否则后台只剩一堆 NULL）
    submitted_by_name = models.CharField(max_length=150, blank=True, default="")
    #: ★ 提交来源（`github` / `gitee`），★ 用于"同一仓库重复提交"检测
    repo_url = models.CharField(max_length=512, blank=True, default="")

    # ---------------------------------------------------------------- ① 为什么进审核
    #: ★ 机器可读的原因码（`no_license` / `copyleft` / `restrictive` / `unknown_license` / …）
    reason_code = models.CharField(max_length=32, db_index=True)
    #: ★★ **人类可读的原因**（`U3.7` ①）—— ★ 后台直接显示这一条
    reason_text = models.CharField(max_length=400)
    #: ★★ **系统检测到的证据**（`U3.7` ②）—— 许可证文件 / SPDX / 原文片段
    evidence = models.JSONField(default=dict, blank=True)
    #: ★ **系统的建议**（`U3.7` ③）—— ⚠ 只是建议，❌ 系统不代替判断
    suggestion = models.CharField(max_length=200, blank=True, default="")
    #: ★★ **给【用户】看的说法**（`U3.8`）—— ⚠ 与 `reason_text` **不是同一件事**：
    #:   `reason_text` 给管理员（含判断要点），本字段给提交者（说清状态 + 该做什么）
    user_message = models.CharField(max_length=400, blank=True, default="")

    # ---------------------------------------------------------------- 决定（★ 人做的）
    decision = models.CharField(
        max_length=16, choices=DECISION_CHOICES, default=DECISION_PENDING, db_index=True
    )
    #: ★ **谁决定的** —— ⚠ 可追责（`U2.5` 纪律 1）
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="decided_reviews",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    #: ★★ 决定理由（★ **为什么放行 / 为什么拒绝**）——
    #: ⚠★ **驳回时必填**（由 `reject()` 强制）：★ 用户说「**用户要能看见自己的申请被驳回的原因**」
    decision_note = models.TextField(blank=True, default="")
    #: ★★ 是否**系统自动判定**（许可宽松 ⇒ 自动放行）—— ⚠ 与"管理员看过"必须能区分
    auto_decided = models.BooleanField(default=False)

    # ---------------------------------------------------------------- 额度
    #: ★★ **驳回时是否退还了上传额度**（`U3.9`）——
    #: ⚠ 因为限额是「**提交即计次**」（否则恶意刷的人被驳回也不占额度 ⇒ 防刷失效），
    #: ★ 所以**被误驳回的用户会亏额度** ⇒ ★ 必须给管理员一个**退还**的动作。
    quota_refunded = models.BooleanField(default=False)

    class Meta:
        indexes = [
            # ★ 管理员的待办清单：先看待审、再按时间
            models.Index(fields=["decision", "-created_at"]),
            models.Index(fields=["project", "-created_at"]),
            # ★ 限额计数：某人某时段提交了几次（★ 高频查询，必须有索引）
            models.Index(fields=["submitted_by", "-created_at"]),
            # ★ "同一仓库重复提交"检测
            models.Index(fields=["submitted_by", "repo_url"]),
        ]
        verbose_name = "项目审核"

    def __str__(self) -> str:
        return f"{self.project_ref or self.project_id}:{self.reason_code}:{self.decision}"

    # ------------------------------------------------------------------ 裁决
    def approve(self, *, by, note: str = "") -> None:
        """★ 放行（人工）。"""
        self._decide(self.DECISION_APPROVED, by=by, note=note)

    def reject(self, *, by, note: str, user_message: str = "", refund_quota: bool = False) -> None:
        """★★ **驳回** —— ★★★ **必须写理由**。

        > **用户原话**：「申请要能驳回，**用户要能看见自己的申请被驳回的原因**。」

        ⚠★ 所以理由**不是可选项** —— ★ 没有理由的驳回，用户只会看到"被拒绝了"
        却不知道该怎么办，⚠ 那等于**把审核变成黑箱**。
        ★ 这里直接 `raise` 而不是静默接受空理由（★ **让错误在开发期就暴露**）。
        """
        if not (note or "").strip():
            raise ValueError(
                "驳回必须填写理由 —— 用户有权知道自己为什么被驳回（U3.8）"
            )
        self._decide(
            self.DECISION_REJECTED,
            by=by,
            note=note,
            user_message=user_message,
            refund_quota=refund_quota,
        )

    def _decide(self, decision, *, by, note="", user_message="", refund_quota=False) -> None:
        from django.utils import timezone

        from core.models import AuditLog

        self.decision = decision
        self.decided_by = by if getattr(by, "pk", None) else None
        self.decided_at = timezone.now()
        self.decision_note = note or ""
        self.auto_decided = False
        if user_message:
            self.user_message = user_message[:400]
        if decision == self.DECISION_REJECTED and refund_quota:
            self.quota_refunded = True
        self.save(
            update_fields=[
                "decision", "decided_by", "decided_at", "decision_note",
                "auto_decided", "user_message", "quota_refunded",
            ]
        )

        # ★ 同步项目状态（★ 项目可能已被删 ⇒ 用冗余 ref 定位）
        project = self.project
        if project is not None:
            new_state = (
                Project.REVIEW_APPROVED
                if decision == self.DECISION_APPROVED
                else Project.REVIEW_REJECTED
                if decision == self.DECISION_REJECTED
                else Project.REVIEW_PENDING
            )
            project.review_state = new_state
            project.save(update_fields=["review_state"])

        # ★★ **管理动作必留痕**（`U2.5` 纪律 1）
        AuditLog.objects.create(
            actor=by if getattr(by, "pk", None) else None,
            action=f"review.{decision}",
            target_kind="ProjectReview",
            target_id=str(self.pk),
            detail={
                "project_ref": self.project_ref,
                "project_name": self.project_name,
                "reason_code": self.reason_code,
                "note": note or "",
                "refund_quota": bool(refund_quota),
            },
        )

    @classmethod
    def auto_allow(cls, *, project, user, verdict) -> "ProjectReview":
        """★ **系统自动放行**（许可宽松）—— ⚠ 仍**必须留一条流水**。

        ★★ 为什么自动放行也要建记录：
          ① ★ 它是**限额的流水**（`U3.9`）—— ⚠ 不建则自动放行的提交**不计次** ⇒ **防刷漏一半**
          ② ★ 它是**审计** —— 将来要能回答"这个项目什么时候自动过的、依据是什么"
        """
        return cls.objects.create(
            project=project,
            project_ref=project.project_ref,
            project_name=project.name,
            submitted_by=user if getattr(user, "pk", None) else None,
            submitted_by_name=getattr(user, "username", "") or "",
            repo_url=(project.repo_url or "")[:512],
            reason_code=verdict.reason_code,
            reason_text=verdict.reason_text[:400],
            evidence=verdict.evidence,
            suggestion=verdict.suggestion[:200],
            user_message=verdict.user_message[:400],
            decision=cls.DECISION_APPROVED,
            auto_decided=True,
        )


class Invite(TimeStampedModel):
    """★★★ 邀请凭证（`U4.7`）—— ★★ **邀请制 = 连带责任**。

    > **用户原话**：「**必须还有邀请注册机制**，我要先做一些**公开上线测试**，
    > ★★ **不能让任何人都能注册，必须是我邀请到的人**。」

    ★★★ 这个策略是对的，因为它是**「读开放 + 写邀请」**：

    | | 策略 | 为什么 |
    |---|---|---|
    | ★ **读** | ★★ 完全开放（连游客都能完整读） | ★ 能被搜索引擎收录、能被分享 ⇒ **有流量** |
    | ★★ **写** | ★★ **邀请制** | ★★ 早期**内容质量比数量重要得多** —— ⚠ 一个垃圾解释会**劝退**新读者 |

    ★★★ 一句话：★ **「让人随便看，但只让信得过的人写。」**

    ---

    ## ★★ 为什么是「长随机 token」而不是「短邀请码」

    | | 短明文码 | ★ 长 token |
    |---|---|---|
    | 过期 / 邀请人 | ⚠ 要额外记 | ✅ **凭证自带**（就是这条记录） |
    | ★ **能不能被猜** | ⚠★ **短码可以被爆破** | ✅★ **`secrets` 长随机串，猜不到** |

    ## ★★ 四条写死的规则（`U4.7`）

    | # | 规则 |
    |---|---|
    | **1** | ★ **用一次即失效**（或限定 `max_uses`）—— ⚠ 否则**一个码泄露 = 无限注册** |
    | **2** | ★ **必须有过期时间** —— ⚠ 否则**泄露了就永久有效** |
    | **3** | ★★★ **必须记录「谁邀请了谁」**（落在 `UserProfile.invited_by`） |
    | **4** | ★★ **通过邀请进来的只能是普通用户（`free`）** —— ⚠ ❌ **不能通过邀请拿到 VIP** |

    ⚠★ 第 4 条特别标出：★ 它和 `U1` 的**铁律**是同一件事 ——
      ★★ **VIP 只与付费 / 授予有关，❌ 不能从"被谁邀请"这条路径进来**。
    """

    #: ★ 长随机凭证（`secrets.token_urlsafe`）—— ★ **唯一**，写进邀请链接
    token = models.CharField(max_length=64, unique=True, db_index=True)

    #: ★ **谁邀请的** —— ★★ 连带责任的落点
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_invites",
    )
    #: ★ 冗余用户名 —— ⚠ 邀请人注销后**记录仍能读懂**
    created_by_name = models.CharField(max_length=150, blank=True, default="")

    #: ★ **可用次数**（默认 1 ⇒ 「用一次即失效」）
    max_uses = models.PositiveSmallIntegerField(default=1)
    #: ★ 已用次数 —— ⚠★ 与 `max_uses` 的比较**必须在锁内**做（否则并发会**超发**）
    used_count = models.PositiveSmallIntegerField(default=0)

    #: ★ **过期时间**（★ 规则 2 —— ❌ 不允许为空串门的"永不过期"）
    expires_at = models.DateTimeField(null=True, blank=True)
    #: ★ **作废时间** —— ★ 管理员可以**随时收回**一个还没用完的邀请
    revoked_at = models.DateTimeField(null=True, blank=True)

    #: ★ 备注（发给谁 / 什么用途）—— ★ 半年后能看懂这个码是干嘛的
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["created_by", "-created_at"]),
        ]
        verbose_name = "邀请"

    def __str__(self) -> str:
        return f"{self.token[:8]}…({self.used_count}/{self.max_uses})"

    # ------------------------------------------------------------------ 状态
    def is_expired(self, now=None) -> bool:
        from django.utils import timezone

        if self.expires_at is None:
            return False
        return (now or timezone.now()) >= self.expires_at

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_exhausted(self) -> bool:
        return self.used_count >= self.max_uses

    def is_usable(self, now=None) -> bool:
        """★ 还能用吗（★ 三个条件缺一不可）。"""
        return not (self.is_revoked or self.is_expired(now) or self.is_exhausted)

    def reject_reason(self, now=None) -> str:
        """★ **为什么不能用** —— ★★ 给用户看的（⚠ 别让他以为是网络问题）。

        ★ 与 `U3.9` 的限额提示同一个道理：★ **说清原因，用户才不会反复重试**。
        """
        if self.is_revoked:
            return "这个邀请链接已被作废，请联系邀请你的人重新发一个。"
        if self.is_expired(now):
            when = self.expires_at.strftime("%Y-%m-%d %H:%M") if self.expires_at else ""
            return f"这个邀请链接已于 {when} 过期，请联系邀请你的人重新发一个。"
        if self.is_exhausted:
            return "这个邀请链接已经被用过了，请联系邀请你的人重新发一个。"
        return ""

    def describe(self) -> str:
        """★ 给管理员看的（★ 一眼能判断该不该留它）。"""
        state = "可用" if self.is_usable() else f"失效（{self.reject_reason()[:24]}…）"
        return (
            f"{self.token[:10]}…  {self.used_count}/{self.max_uses}  {state}"
            f"  邀请人={self.created_by_name or '—'}  备注={self.note or '—'}"
        )


class OAuthIdentity(TimeStampedModel):
    """★ 第三方身份绑定（`U4.5` / `U3.2`）—— ★★ **「登录方式」不是「账号」**。

    > **用户原话（`B141`）**：「本站要有**登陆功能**，也就是在本站要**有账号**，**就像 B 站一样**。」
    >
    > ★★ 澄清：★ **「有账号」说的是【身份】，「怎么登录」说的是【凭证】。**

    ★ 所以本表是**凭证**表：★ **一个本站账号可以绑多个 provider**
      （★ `unique(user, provider)` ⇒ 一期同一 provider 只绑一个）。

    ## ★★ 为什么必须存 `provider_user_id`（数字 ID），而不是 `login`

    ★★★ `U3.2` 坑 1：**GitHub 用户名可以被改。**

    | 存什么 | 后果 |
    |---|---|
    | ❌ 只比 `login` 字符串 | ⚠★ 用户**改个名，归属校验就失效**（★ 或更糟：**把自己的验证过了**） |
    | ✅ ★★ 比 `provider_user_id` | ★ **数字 ID 不可变** ⇒ 改名不影响 |

    ⇒ ★ `login` 在本表里**只用于展示**（⚠ 用户改一次名，这里就旧了 —— 所以每次登录刷新它）。

    ## ⚠★★ 本表**不存 `access_token`** —— 这是有意的

    ★★ 依据 `U3.3`：★ **只申请 `read:user`，❌ 不碰私有仓库**；
    ★ 而归属校验用的是 `GET /repos/{owner}/{repo}` —— ★ **公开信息**。

    ⇒ ★★ 所以**没有任何需要长期持有 token 的理由** ⇒
      ★ 归属校验**当场取、当场用、用完即弃**（见 `core/oauth.py`）。
    ★★ 收益：★ **彻底消灭「token 泄露」这一类事故** ——
      与 `U4.2` 理由 4「**少一套凭据要保护**」是同一个精神。
    """

    PROVIDER_GITHUB = "github"
    PROVIDER_GITEE = "gitee"
    PROVIDER_CHOICES = [
        (PROVIDER_GITHUB, "GitHub"),
        (PROVIDER_GITEE, "Gitee"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oauth_identities"
    )
    provider = models.CharField(max_length=16, choices=PROVIDER_CHOICES, db_index=True)

    #: ★★ **数字 ID —— 归属校验的唯一依据**（★ 不可变，`U3.2` 坑 1）
    provider_user_id = models.CharField(max_length=64, db_index=True)

    #: ⚠ **会变** —— ★ 只用于展示；★ 每次登录刷新一次
    login = models.CharField(max_length=150, blank=True, default="")
    avatar_url = models.CharField(max_length=512, blank=True, default="")

    #: ★ 最近一次登录时间（★ 便于排查"这个绑定还用不用"）
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # ★★ 一个 provider 身份只能绑一个本站账号（⚠ 否则归属校验会有歧义）
            models.UniqueConstraint(
                fields=["provider", "provider_user_id"], name="uniq_provider_identity"
            ),
            # ★ 一期：一个本站账号在一个 provider 只绑一个身份（⚠ 多绑留到将来）
            models.UniqueConstraint(fields=["user", "provider"], name="uniq_user_provider"),
        ]
        verbose_name = "第三方身份"

    def __str__(self) -> str:
        return f"{self.provider}:{self.login}({self.provider_user_id})"


class OAuthState(TimeStampedModel):
    """★★ OAuth 的 `state` —— ★★ **既防 CSRF，又承载「意图」**（`U4.8`）。

    ## ★ 为什么要落库，而不是放 session

    | | session | ★ 本表 |
    |---|---|---|
    | ★ **多实例** | ⚠ 需要共享 session 存储 | ✅ **天然可用**（`ARCHITECTURE.md` A0-3：**Web 层无状态**） |
    | ★ **一次性** | ⚠ 要自己擦 | ✅ **`consumed_at` 标记**（★ 防重放） |
    | ★ **可审计** | ❌ | ✅ 留得住 |

    ## ★★ `state` 里为什么要带这么多东西（`invite_token` / `repo` / `project_ref`）

    ★★★ 因为本平台的设计是 ★★ **不长期保存 `access_token`**（见 `OAuthIdentity` 文档）⇒
      ★ 那些"本来可以事后从库里取"的信息（要发布哪个项目、邀请码是多少），
      ★ **必须在跳转前塞进 `state`**，回调时一次性用完。

    ⚠ 而这些字段**用户可能篡改**吗？—— ❌ **不可能**：
      ★ `state` 本身是服务端生成的**随机串**，★ 这些值是**服务端存的行**里的，
      ⚠ 用户只拿着那串 `state`，**改不了它对应的内容**。
    """

    ACTION_LOGIN = "login"

    #: ⚠★★ `B176` ①（2026-10-12）：**下面两个 action 已【退役】—— 只留给历史数据读** ⚠
    #:   ★ `ACTION_PUBLISH`：建项目（★ 发布曾经被**拆到授权回调里**完成）
    #:   ★ `ACTION_FETCH`  ：拉取代码（`B169` 确立的）
    #:   ★★★ 所有者裁定「**删掉归属验证，有风险**」之后 ⇒ ★ 那两件事
    #:     **都不再需要 `access_token`** ⇒ ★★ 各自挪回了**普通的接口** ✅
    #:     （★ `POST /api/projects/publish/start/` · ★ `POST /api/projects/<ref>/fetch/`）
    #:   ⇒ ★★ **现在没有任何代码会创建这两个 action 的 state** ⚠
    #:   ⚠★ 常量与 `choices` **刻意保留**（❌ 不删）—— ★ 因为库里还有历史行，
    #:     ★ 删掉会让 `ACTION_CHOICES` 与实际数据对不上（★ 且要动一次迁移）⚠
    #:   ★ 详见 `web/views/auth.py::callback()` 的说明与 `docs/backend-decisions.md` 的 `B176`。
    ACTION_PUBLISH = "publish"
    ACTION_FETCH = "fetch"

    ACTION_CHOICES = [
        (ACTION_LOGIN, "登录 / 注册"),
        (ACTION_PUBLISH, "发布项目（⚠ B176 ① 起已退役，仅历史数据）"),
        (ACTION_FETCH, "拉取代码（⚠ B176 ① 起已退役，仅历史数据）"),
    ]

    #: ★ 随机串（★ primary key ⇒ **天然唯一**）
    state = models.CharField(max_length=64, primary_key=True)
    provider = models.CharField(max_length=16, choices=OAuthIdentity.PROVIDER_CHOICES)

    #: ★★ **意图** —— ★★ `B176` ① 之后**只剩「登录 / 注册」一种**了 ⚠
    #:   （★ 以前的「发布意图」「拉取意图」已退役 —— 见上面 `ACTION_PUBLISH` 的说明）
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, default=ACTION_LOGIN)

    #: ★ 邀请码（★ `U4.8` 流程第 ② 步：**跳转前就填好**）
    invite_token = models.CharField(max_length=64, blank=True, default="")
    #: ★ 登录成功后的去处
    next_url = models.CharField(max_length=512, blank=True, default="")
    #: ★ 发布场景：要校验归属的仓库 + 目标项目
    repo = models.CharField(max_length=512, blank=True, default="")
    # ⚠★★ 2026-10-14（`B183`/`B197`）：**裸 `project_ref` 之外再补一个真外键** ⚠
    #   ★★ 所有者裁定：「**12 处裸 project_ref 必须有引用完整性**」（"缠绕"的总根源）⚠
    #   · ★ 裸字符串没有任何保证 —— ★ 项目删了这些行还在，* 永远指着不存在的东西 ⚠
    #   · ★★ 实测已因此出过事：「判重只看流水 ⇒ 删了项目照样拦死人」⚠
    #   · ★ 有外键 ⇒ ★★ 数据库【当场】挡住不可能的状态 ✅
    # ⚠★ 字符串引用 "core.Project" ⇒ ★ 不需要 import，* 不可能成环 ✅
    project = models.ForeignKey(
        "core.Project", null=True, blank=True,
        on_delete=models.CASCADE, related_name="+",
    )
    project_ref = models.CharField(max_length=64, blank=True, default="")

    #: ★★ **发布意图的其余字段**（`name` / `desc` / `source_path` …）
    #: ⚠★ 为什么必须存在 `state` 里：★ 本平台**不长期保存 `access_token`**（见 `OAuthIdentity`）⇒
    #:   ★ **发布动作只能在回调那一刻做** ⇒ ★ 用户在 `/start/` 时填的东西
    #:   **必须跨过一次跳转活下来**，★ 而 `state` 是**唯一**能承载它的地方。
    #: ★ 用一个 JSON 而不是各开一个字段：★ 这类"意图参数"会随功能长，
    #:   ⚠ 每加一个就迁移一次**不划算**（★ 且它们**不参与查询**）。
    intent = models.JSONField(default=dict, blank=True)

    #: ★ 「记住我」（契约 §12：7 / 30 天两档）——
    #: ⚠ 为什么它必须活在 `state` 里：★ 回调时**用户已经不在我们的页面上**了
    #:   （他在 GitHub），⇒ ★ 除了 `state` **没有别的地方能记住这个选择**。
    remember = models.BooleanField(default=True)

    #: ★ 过期时间（★ 由 `AppSetting: oauth.state_ttl_seconds` 决定）
    expires_at = models.DateTimeField()
    #: ★★ **已消费标记** —— ★ 一次性，防重放
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["expires_at"]),     # ★ 清理用
            models.Index(fields=["-created_at"]),
        ]
        verbose_name = "OAuth 会话"

    def __str__(self) -> str:
        return f"{self.state[:10]}…:{self.provider}:{self.action}"

    def is_usable(self, now=None) -> bool:
        """★ 还能用吗（★ 两个条件：**没用过** + **没过期**）。"""
        from django.utils import timezone

        if self.consumed_at is not None:
            return False
        return (now or timezone.now()) < self.expires_at

    def reject_reason(self, now=None) -> str:
        """★ **为什么不能用** —— ★★ 给用户看的（★ 同 `U3.9`：说清原因，用户才不会反复重试）。"""
        if self.consumed_at is not None:
            return "这次授权已经用过了，请重新发起登录。"
        return "授权会话已过期，请重新发起登录。"


class ApiToken(models.Model):
    """★★ **API 令牌（Bearer）** —— 本站的「登录凭证」（`U4.4` 纪律 1 · 契约 §12）。

    > ★★ **明文只返回一次，库里只存哈希。**

    | | |
    |---|---|
    | ★ 明文 | ★ **只在签发的那一刻返回给前端**（此后服务端**再也拿不到**） |
    | ★ 库里 | ★ **`blake2b(raw, digest_size=32)` 的 hex**（64 字符） |

    ⚠★★ 为什么**不是** Django 的 `make_password`（慢哈希）：

    ★ 慢哈希（PBKDF2/argon2）是为了对抗**低熵口令**的**离线爆破**；
    ★★ 而本表的 token 是 **`secrets` 生成的高熵随机串** ⇒ **爆破在物理上不可能**
      ⇒ ★ 再用慢哈希只是**白白拖慢每个请求**（⚠ 每个 API 请求都要校验一次）。

    ★ 契约 §12 点名了 `blake2b(raw, digest_size=32)` —— 与上面的判断一致 ✅。

    ## ★ 为什么要存一个 `prefix`（明文前 8 位）

    ★ 为了**能辨认**「这是哪个令牌」—— ⚠ 否则后台只能看到一堆哈希，
      ★ "登出全部设备"时**不知道该撤哪个**。
    ⚠ 8 位前缀**远不足以还原** 32 字节的随机串（★ 这才是关键）。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens"
    )

    #: ★ `blake2b(raw).hexdigest()` —— ★ 唯一，⭐ **查 token 就走这个索引**
    token_hash = models.CharField(max_length=64, unique=True)
    #: ★ 明文前 8 位（★ 只为辨认，❌ 不足以还原）
    prefix = models.CharField(max_length=16, blank=True, default="", db_index=True)

    #: ★ 从哪来（`github` / `gitee` / `admin`）—— ★ 便于排查"这个 token 是谁发的"
    provider = models.CharField(max_length=16, blank=True, default="")
    user_agent = models.CharField(max_length=200, blank=True, default="")

    expires_at = models.DateTimeField(db_index=True)
    #: ★ 撤销时间（⚠ 登出 = 撤销这一个；"登出全部设备" = 撤销该用户全部）
    revoked_at = models.DateTimeField(null=True, blank=True)
    #: ★ 最近一次使用（★ 便于看出"这个 token 还用不用"，⚠ 不做写放大：只在超过阈值时更新）
    last_used_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["expires_at"]),     # ★ 清理用
        ]
        verbose_name = "API 令牌"

    def __str__(self) -> str:
        return f"{self.user_id}:{self.prefix}…"

    def is_valid(self, now=None) -> bool:
        """★ 还有效吗（★ 三个条件：**没撤销** + **没过期**）。"""
        from django.utils import timezone

        if self.revoked_at is not None:
            return False
        return (now or timezone.now()) < self.expires_at


class ProjectStorage(models.Model):
    """★★ **项目在「用户存储空间」里占了多少**（`B152`）。

    ## ★★ 为什么是「每个项目一条」而不是「每个用户一条累计值」

    | 做法 | 删除项目时 | 能回答"哪个项目最占空间"吗 |
    |---|---|---|
    | ❌ 用户一条累计值 | ⚠ 要**记得减回去** —— 少减一次就永久错 | ❌ |
    | ✅ ★ **每个项目一条** | ★ **删掉那一行就自动释放** | ✅ |

    ★★ 而"用户的用量"= **`SUM` 一下**（★ 这个查询**不高频**：只在发布前检查与设置页显示）。
    ⇒ ★★ **不额外存"用户汇总值"** —— ⚠ 两份记账**早晚会不一致**
      （★ 与 `B146` 抓出的"计数必须只有一个来源"是**同一条纪律**）。

    ## ⚠★ 一条硬纪律：**路径只能由 `project_ref` 派生**

    ★ `project_ref` 的形态是 **`proj_[0-9a-f]{32}`** ⇒ ★ **天然不含 `/` 与 `..`**
      ⇒ ★★ **结构上就不可能路径穿越**（★ 这是"不校验也不会出事"的那一类设计）。

    ⚠★ 反过来：★ **绝不接受用户提供的路径** —— ⚠ 那等于让用户读容器里的**任何**目录。
    """

    #: ★ 一个项目一条（★ 主键就是 `project_ref`）
    # ⚠★★ 2026-10-14（`B183`/`B197`）：**裸 `project_ref` 之外再补一个真外键** ⚠
    #   ★★ 所有者裁定：「**12 处裸 project_ref 必须有引用完整性**」（"缠绕"的总根源）⚠
    #   · ★ 裸字符串没有任何保证 —— ★ 项目删了这些行还在，* 永远指着不存在的东西 ⚠
    #   · ★★ 实测已因此出过事：「判重只看流水 ⇒ 删了项目照样拦死人」⚠
    #   · ★ 有外键 ⇒ ★★ 数据库【当场】挡住不可能的状态 ✅
    # ⚠★ 字符串引用 "core.Project" ⇒ ★ 不需要 import，* 不可能成环 ✅
    project = models.ForeignKey(
        "core.Project", null=True, blank=True,
        on_delete=models.CASCADE, related_name="+",
    )
    project_ref = models.CharField(max_length=64, primary_key=True)
    #: ★ 归属者（⚠ 项目被删后仍留一行也不碍事；`SET_NULL` 便于排查历史）
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="project_storages",
    )

    bytes_used = models.BigIntegerField(default=0)
    files_used = models.IntegerField(default=0)

    #: ★ 相对 `settings.ASTROLABE_STORAGE_ROOT` 的路径（★ 存相对值 ⇒ **换根目录不用改库**）
    path = models.CharField(max_length=512, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    #: ★ 最近一次统计时间（★ "这个数字是什么时候的" —— ⚠ 没有它就没法判断要不要对账）
    measured_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # ★ 用户用量 = SUM(...) —— ★ 这个索引就是为它建的
            models.Index(fields=["owner"]),
            models.Index(fields=["-bytes_used"]),
        ]
        verbose_name = "项目存储占用"

    def __str__(self) -> str:
        return f"{self.project_ref}:{self.bytes_used}B/{self.files_used}files"


class Collaborator(models.Model):
    """★★★ **项目协作者**（★ `B202` / `B206` / `B207`）—— ★ 一张**一对多**表。

    ## ★★★ 所有者原话（2026-10-16，逐字）

    > 「**协作者是以项目为基准邀请的，也就是说，一个项目甭管是私有的还是公开的，
    > 只要邀请了，对方都可以查看修改**」

    > 「**除了删除项目，协作者权限与作者一样大。**」

    ## ★★ 为什么每行只有 `(project, user)` 两列

    ```
    ★★ 没有 role ——* 「协作者不需要读或者写这些权利划分」（* B202）⚠
    ★★ 没有 invited_by / created_at ——* 想知道"谁邀的、何时进的"查 `AuditLog`
       （* 存一份必然打架，* 同 `B197` 的纪律）⚠
    ```

    ## ★★ 为什么**不继承** `TimeStampedModel`（* 2026-10-16 自我纠正）

    ```
    ★★ 我第一版继承了它 ⇒ * 带出 `created_at` / `updated_at` 两列 ⚠
       · · ★ 而 `B202`③ 明说**没有 created_at** ——* "何时进的"查 `AuditLog`，
         * 表里再存一份**必然打架**（* 同 `B197` 的纪律）⚠
       · · ★★ 所以改回纯 `models.Model`：* 只有 (project, user) 两列 ✅
    ```

    ## ★★ 三条硬纪律

    | # | 纪律 |
    |---|---|
    | ① | ★★ **本表不参与任何"读内容"判断之外的事** —— 它只让 `can_edit` 多放一行人（`B207`②）⚠ |
    | ② | ★★ **删项目不在协作者权限内**（`can_delete` 单判 owner/staff，`B207`②）⚠ |
    | ③ | ★★ **成员被移除后，他建的笔记/评论全留着** —— 没有"冻结"这个动作（`B202`③）⚠ |

    ⚠★ **项目内访问齐平**（`B207`① 的状态不变量）：
      * 不存在"能看不能改"，也不存在"能改不能看"——
      * ★★ 协作者与 owner 在**内容**上同权，* 只有"删项目"这一件事例外 ⚠
    """

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="collaborators"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="collaborations",
    )

    class Meta:
        constraints = [
            # ★★ 同一人在同一项目只有一行（* 添加端点靠它做幂等）✅
            models.UniqueConstraint(fields=["project", "user"], name="uniq_collaborator"),
        ]
        # ⚠★ 2026-10-16（`B199` 纪律）：**不另加索引** ⚠
        #   · ★ 唯一约束自带的索引前缀就是 `project` ⇒ "列成员"已覆盖 ✅
        #   · ★ 按 `user` 反查（* "我参与了哪些项目"）**本批没有用例** ⇒ 不加 ⚠
        #   · ★★ 能少加一个字段进索引就少加一个 ⚠
        verbose_name = "项目协作者"

    def __str__(self) -> str:
        return f"{self.project_id}:{self.user_id}"


class UserProfile(TimeStampedModel):
    """用户档案 —— ★ 与 Django `User` **一对一**。

    ⚠★ 依 `USERS-AND-AUTH.md` `U10` 纪律 2：
      ❌ **不往 Django 的 `User` 上加业务字段** —— 升级 / 迁移时会冲突。

    ★ 这里承载 `U1` 三条正交线里的**订阅层级**（`tier`），
      ⚠ 而**站点职权**仍用 Django 自带的 `is_staff` / `is_superuser`（❌ 不重复造）。
    """

    TIER_FREE = "free"
    TIER_VIP = "vip"
    #: ⚠ `enterprise` **不是公开版的一档**（`U2.4`）—— ★ 故此处**不提供**该取值
    TIER_CHOICES = [
        (TIER_FREE, "普通用户"),
        (TIER_VIP, "VIP 用户"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )

    #: ★★ 订阅层级 —— ⚠ **只决定配额与荣誉，❌ 绝不决定内容可读性**（`U1` 铁律）
    tier = models.CharField(max_length=16, choices=TIER_CHOICES, default=TIER_FREE)

    #: ★★ **邀请人**（`U4.7` 规则 3）——
    #: ⚠★ **邀请制 = 连带责任**：★ 有人邀请垃圾账号进来，要能找到邀请人。
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invited_users",
    )

    #: ★ **付费槽位额度**（`U9.3`）—— ★ 管理员可调；⚠ 一期**无支付**，手工开
    paid_slots = models.PositiveSmallIntegerField(default=0)

    #: ★ **配额覆盖**（`U6`）—— ⚠ 空 = 用档位默认；★ 非空 = 管理员给该用户单独放宽
    quota_override = models.JSONField(default=dict, blank=True)

    #: ★ **深度分析是否开通**（契约 §17.7）——
    #: ⚠ VIP 拥有该能力，但 ★ **仍需管理员显式开通**（`U6`）
    deep_analysis_granted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "用户档案"

    def __str__(self) -> str:
        return f"{self.user_id}@{self.tier}"


class AppSetting(models.Model):
    """★ 参数中心 —— ★★ **配额与开关必须可配置，❌ 不得硬编码**（`U6` 要点 3）。

    ⚠ 键的定义在 `core/appsettings.py` 的 `KEYS`（★ 唯一权威）——
      ❌ **不要绕过它直接读写本表**（那会变成"隐形配置"）。
    """

    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "参数"

    def __str__(self) -> str:
        return f"{self.key}={self.value!r}"


class AuditLog(models.Model):
    """★ 审计日志 —— ★★ **管理动作必留**（`U2.5` 纪律 1）。

    ★★ 为什么它是"最大权力唯一的约束"：

    > ⚠ 「掌管整个网站」= 权力最大 ⇒ ★★ **可追责**是它唯一的约束。
    > ★ 特别是 `U2.5` 的三条纪律：**改参数 · 特批 · 读私有内容**，
    > ⚠ **每一个都必须留痕**。

    ⚠ 目标用 `target_kind + target_id`（❌ 不是外键）——
      ★ 因为审计要能记**已删除对象**（如被下架的项目），★ 外键会随对象消失。
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    #: ★ 动作（如 `setting.change` / `project.takedown` / `invite.create`）
    action = models.CharField(max_length=64, db_index=True)
    target_kind = models.CharField(max_length=32, blank=True, default="")
    target_id = models.CharField(max_length=128, blank=True, default="", db_index=True)

    #: ★ **依据与前后值** —— ⚠★ 这一栏是"我们凭什么这么判"的留痕（`U3.7`）
    detail = models.JSONField(default=dict, blank=True)

    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["target_kind", "target_id", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]
        verbose_name = "审计日志"

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_id}"


class UserSetting(TimeStampedModel):
    """★★ **用户档设置**（★ `B190` · 2026-10-15）。

    ## ★★ 所有者原话（逐字）

    > 「**我差点忘了，你要有张属性或设置表，用来设置一下用户或项目的
    > 可能我还没想到的设置，就像IDE的设置一样。**」

    > 「**三级继承很好**」

    ## ⚠★ 三条设计口径

    ```
    ① ★★ 未设置 = 不存行 ⚠
       · ★ 存一行 ⇒ ★ 覆盖默认 ✅
       · ★★ 删一行 ⇒ ★ 自动回到代码里的默认值 ⚠
       · ★（★ 若一设置就存一个默认值 ⇒ ★ 以后改默认值【对老行不生效】⚠）
       · ★ 而且表不会因为"每个用户 × 每个键"而膨胀 ✅

    ② ★★ 键必须已在 core/settings_table.py::SCOPED_KEYS 注册 ⚠
       · ★ 未注册的键 ⇒ ★ 写不进来（* set_value 直接 KeyError）✅
       · ★★ 这就是「属性种类由所有者指定」的硬执行点 ⚠

    ③ ★★ 值存 jsonb（* 与 AppSetting 一致）⚠
       · ★ jsonb 不保类型 ⇒ ★ 读出来按注册表转一次（* _coerce）✅
    ```

    ⚠★ 为什么**不**把三档合成一张表（* `scope` + `owner_id`）：
      ★★ 那要两个可空外键 + "恰有其一"的 CHECK —— ★ 正是被批过的形状 ⚠
      · ★ 而三档的差别是"**属主不同**"（* 那是本质差异，* ❌ 不是冗余）✅
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="settings",
    )
    #: ★ 键名（★ 必须已在 `SCOPED_KEYS` 注册）
    key = models.CharField(max_length=64)
    #: ★ 值（★ jsonb：* 与 `AppSetting` 同一口径 ✅）
    value = models.JSONField(default=dict, blank=True)
    #: ★ 最后改它的人（★ 管理员给某个用户单独改时，* 记的是管理员）⚠
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        constraints = [
            # ★★ 一个用户一个键只有一行 ✅
            models.UniqueConstraint(fields=["user", "key"], name="uniq_user_setting"),
        ]
        verbose_name = "用户设置"

    def __str__(self) -> str:
        return f"{self.user_id}:{self.key}"


class ProjectSetting(TimeStampedModel):
    """★★ **项目档设置**（★ `B190` · 2026-10-15）。

    ## ★★ 它装什么（★ 第一个键就是所有者定的那个）

    ```
    note.orphan_comment_policy  ⇒ ★ 段落被修改后，原段评怎么办
    ```

    ## ★★★ 所有者原话（逐字）

    > 「**修改段落了，评论默认不再显示，但要给作者三个选项，
    > 挂在新写的段落上，放底部评论区里，默认的不显示。
    > 嗯，这个不要每次修改都跳，记录到项目设置里**」

    ⇒ ★★ **它是【项目级策略】，★ 不是每次编辑时问一遍** ✅
      · ★ 三个选项其实是**一种政策**：* 遇到失锚评论时怎么办 ⚠
      · ★★ 好处：* 作者不用在每次敲键盘后做决定（* 那会烦死人）⚠

    ⚠★ 与 `UserSetting` 同构，* 但属主不同（* 那是本质差异）✅
    """

    project = models.ForeignKey(
        "core.Project",
        on_delete=models.CASCADE,
        related_name="settings",
    )
    key = models.CharField(max_length=64)
    value = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "key"], name="uniq_project_setting"),
        ]
        verbose_name = "项目设置"

    def __str__(self) -> str:
        return f"{self.project_id}:{self.key}"


# ===========================================================================
# 笔记与互动（★ `B190` · 2026-10-15）—— ★★ 六张新表
# ===========================================================================
#
# ★★★ 所有者原话（逐字）：
#
#   「**我设计一个项目表，一个用户表，一个节点表，一个边关系表，一个基图表，
#     一个markdown笔记表。你觉得怎么样？还有对markdown解释的点赞与评论数据
#     装在哪里好？注意，我要的评论是类似番茄小说的段评和章评**」
#
# ★★ 由此定下的骨架：
#
# ```
# core_note          笔记本体（★ 挂在【代码节点】上，1:N）
# core_note_link     笔记之间的联系（★ 所有者拍的那张关联表）
# core_note_block    笔记段落（★★ 段评的锚点）
# core_note_comment  评论（★ 章评 + 段评【同表】）
# core_note_like     点赞（★ 章赞 + 段赞【同表】）
# core_note_revision 历史版本（★ 环形缓冲）
# ```
#
# ⚠★★ **笔记【不占】图节点** —— ★★ 所有者原话（2026-10-14，逐字）：
#   「**笔记占图节点干什么？你想想笔记图节点是干什么的？那是我为了显示笔记之间
#     联系而设计的，图节点可以天然的显示联系。**」
#   ⇒ 而所有者随后又否掉"塞进 graph_node"那条路：
#     「**我的天呀，笔记节点，你填假值进去干什么？不是人为放宽了图节点能填进去的值？
#       你要不就重新建一张表。**」
#   ⇒ ★★ 所以：★ 笔记**有自己的表**，★ 之间的联系由 `core_note_link` 表达 ✅
#     （* `graph_node` 一个字段都不动 ✅）


class Note(TimeStampedModel):
    """★★ **一篇笔记** —— ★ 用户记下的一段 markdown 想法。

    ## ★★ 归属（★ 所有者 2026-10-14 定）

    > 「**笔记挂在节点上 —— 一个节点可以有多篇笔记（1:N）**」

    ⚠★ `node_id` 是 **FK → `graph_node`**（* ❌ 不是裸 uid）——
      ★★ `B117` 立的规矩：「**能重复的只用来看；不能重复的才用来挂**」⚠
      · ★ `uid` 允许重复 ⇒ ★ 只配看 ⚠
      · ★★ `node_id` 是主键 ⇒ ★ 才配挂 ⚠

    ## ⚠★ 三个"不要"

    ```
    ① ★★ 不要【标题列与正文打架】⚠
       · ★ `title` 允许用户改，* 但**每次保存都拿正文前几字覆盖**会冲掉他的手改 ⚠
       · ★ 折中：* 建时取正文前几字；* 保存时若开头有 `#` 标题则用它 ✅
       · ★★ 其余时候不动 ✅

    ② ★★ 不要【四张盒子表】⚠
       · ★ "盒子"是【展示】，❌ 不是容器 ⚠
       · ★★ 一列 `kind` + 前端分组渲染 ⇒ ★ 加第五种盒子只需加一个枚举值 ✅

    ③ ★★ 不要【坐标列】⚠
       · ★ 所有者 2026-10-14：*「**笔记不要整坐标，太麻烦…每次打开都是标准排布，
         可以拖拽就行了呗**」⇒ ★ 拖拽**纯前端**，* 不落库 ✅
    ```
    """

    #: ★★ **它挂在哪个代码节点下**（★ 1:N 的"1"）⚠
    node = models.ForeignKey(
        "graph.Node",
        on_delete=models.CASCADE,
        related_name="notes",
    )
    #: ★★ **盒子**（* `flash` 灵光一闪 / `question` 提问质疑 / …）——
    #: ★ 所有者：「**笔记以后我会划分为几个类型…分别放入一个节点下的四个不同盒子**」
    #: ⚠★ **固定枚举**（* 所有者 2026-10-14：*「**可增删最多四五个，你整个表干什么？**」）✅
    kind = models.CharField(max_length=16, default="flash")
    #: ★ 标题（★ 允许用户手改；* 规则见类文档 ①）⚠
    title = models.CharField(max_length=120, blank=True, default="")
    #: ★ 正文（★ markdown 原文）——
    #: ★★ **一个 blob**，* ❌ 不拆结构化块数组（* 所有者 2026-10-14 定的口径）⚠
    body = models.TextField(blank=True, default="")
    #: ★ 卡片外观（★ 指向皮肤存储位置的地址）——
    #: ★★ 所有者 2026-10-14：*「**卡片外观就加一个指向皮肤存储地方的地址，不难吧？**」
    card_skin = models.CharField(max_length=200, blank=True, default="")
    #: ★★ **每篇笔记单独设可见性，* 默认可见**（* 所有者 2026-10-14 定）⚠
    is_public = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notes",
    )

    # ------------------------------------------------------------------ 状态
    # ★★ `B208`⑦（* 2026-10-16）：* 笔记也要能被管理员**隐藏 / 下架** ⚠
    #
    # ★★ 所有者原话整句（* A34）：「管理员只有隐藏下架项目和笔记的权限」✅
    #
    # ⚠★ **只有两态** ——* 刻意**不设** `taken_down` ⚠
    #   · ★ 所有者裁定（* 逐字）：「**下架是彻底从服务器上删除数据。**」✅
    #   · · ★ 下架 = **物理删除** ⇒* 行都没了，* 要那个态干什么？⚠
    #   · ★ 所以本列只需表达"**被隐藏**"这一种中间态 ✅
    #
    # ⚠★ **隐藏的语义**（* 所有者裁定，* 覆盖 `U3.5` 旧口径）：
    #   · ★★ **只有作者能看到**，* 别人**直接链接也不可访问** ⚠
    #   · ★★ 比私有项目更严：* **连协作者也不能看** ✅
    #     （* 私有项目 = owner ∨ 协作者；* 隐藏 = **仅作者**）⚠
    STATE_ACTIVE = "active"
    STATE_HIDDEN = "hidden"
    STATE_CHOICES = [
        (STATE_ACTIVE, "正常"),
        (STATE_HIDDEN, "已隐藏"),
    ]
    state = models.CharField(
        max_length=16, choices=STATE_CHOICES, default=STATE_ACTIVE, db_index=True
    )

    # ---------------------------------------------------------------- 处置留痕
    # ★★ 同 `Project` 侧那三列（* `B196` 的形状）——* 「最近一次处置」⚠
    #   · ★ `state` 只有"现在是什么状态"，* **没有原因** ⚠
    #   · ★★ 作者来问"**为什么隐藏我**"⇒ ★ **答不出来** ⚠
    #   · ⚠★ 代价：* 只能存**最近一次** ⇒ ★ 多次处置的历史靠 `AuditLog` ⚠
    #: ★★ **最近一次处置的理由**（★ 管理员处置时写）· ★ 空串 = 没处置过
    moderation_reason = models.CharField(max_length=400, blank=True, default="")
    #: ★ **谁做的这次处置**（★ FK → `auth_user`）· ★ NULL = 没处置过
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="moderated_notes",
    )
    #: ★ **什么时候处置的** · ★ NULL = 没处置过
    moderated_at = models.DateTimeField(null=True, blank=True)

    # ---------------------------------------------------------------- 软删（回收站）
    # ★★ `B210`（* 2026-10-16）：* 删除改**软删** + 回收站 ⚠
    #
    # ★★ 所有者原话整句：「**管理员删除就是彻底删除，没有恢复机制，
    #    所以，才有了隐藏这个不太严的。**」✅
    #
    # ★★ 两条删除路径因此分开（* 这是本设计的**全部要点**）：
    # ```
    # ① ★★ 其他人删（* 作者 / 协作者 / owner，* 走 DELETE /api/notes/<id>/）
    #      ⇒ ★ 软删：* 本两列写上，* 行还在，* **可从回收站恢复** ✅
    # ② ★★ 管理员删（* 走 POST /api/admin/notes/<id>/moderate/ take_down）
    #      ⇒ ★★ **物理删除**（* 行都没了）⇒* **没有恢复机制** ⚠
    # ```
    # ★★ 所以：* **软删行必然是非管理员删的** ⇒* `deleted_by` 一列
    #   就直接回答"谁删的"（* 所有者要求「分清管理员删的还是其他用户删的」）✅
    #
    # ⚠★ 读路径：* `core/access.py::can_read_note` 顶部判 `deleted_at` ⇒
    #   软删笔记对**所有人**不可见（* 含作者，* 恢复走回收站）⚠
    #: ★★ **什么时候被软删的** · ★ NULL = 没被删（* 正常笔记）✅
    deleted_at = models.DateTimeField(null=True, blank=True)
    #: ★ **谁删的**（★ FK → `auth_user`）· ★ NULL = 没被删
    #: ⚠★ **SET_NULL** 而不是 CASCADE ——* 删号不删笔记（* 同 `moderated_by`）⚠
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deleted_notes",
    )

    # ---- 冗余计数（★ 列表免 count；* 真相在明细表，* 必须可重算）----
    like_count = models.IntegerField(default=0)
    comment_count = models.IntegerField(default=0)

    class Meta:
        indexes = [
            # ★★ **只留一棵**（★ `B199`：能少加一个字段进索引就少加一个）⚠
            #   · ★ 盒子视图总是"按 kind 分组 + 按时间排" ⇒ ★ 一棵就够 ✅
            #   · ★★ 原先还想加 `(node_id, created_at)` —— ★ 那是多余的前缀 ⚠
            models.Index(fields=["node", "kind", "-created_at"]),
            # ★ "我的笔记"
            models.Index(fields=["created_by", "-created_at"]),
        ]
        verbose_name = "笔记"

    def __str__(self) -> str:
        return (self.title or self.body[:20] or f"note#{self.pk}")[:40]


class NoteLink(TimeStampedModel):
    """★★ **笔记与笔记之间的联系**（★ 所有者拍的那张关联表）。

    ## ★★★ 所有者原话（2026-10-14，逐字）

    > 「**我的天呀，笔记节点，你填假值进去干什么？不是人为放宽了图节点能填进去的值？
    > 你要不就重新建一张表。存储笔记节点之间的联系，要不就在笔记表里建一个一对多的
    > 映射字段，可以修改映射关系名称**」

    ## ★★ 为什么是关联表（* 而不是"笔记表上一个映射字段"）

    | | ★ 关联表 | ★★ 笔记表上一个字段 |
    |---|---|---|
    | 支持 N:M | ✅ | ⚠ 只能"一条指向多条" |
    | ★★ **反向能查吗** | ✅ 一个索引就够 | ❌ 要全表扫 / JSON 包含查询 ⚠ |
    | 关系名放哪 | ★ 每条连线自带 ✅ | ⚠ 得塞进那个字段里 |
    | 将来"笔记↔函数" | ★ 加一列即可 ✅ | ❌ 更别扭 |

    ★★ 关键在第二行：* 联系**天然是双向的** ⇒ ★「**谁引用了我**」必须能查 ⚠
    """

    from_note = models.ForeignKey(
        Note, on_delete=models.CASCADE, related_name="links_out"
    )
    to_note = models.ForeignKey(
        Note, on_delete=models.CASCADE, related_name="links_in"
    )
    #: ★★ 「**映射关系名称**」—— ★ 每条连线自带一个，* **可改** ✅
    relation = models.CharField(max_length=32, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="note_links",
    )

    class Meta:
        constraints = [
            # ★★ 同一条关系不重复建 ✅
            models.UniqueConstraint(
                fields=["from_note", "to_note", "relation"],
                name="uniq_note_link",
            ),
        ]
        indexes = [
            # ⚠★ 2026-10-15（`B199`）：**`(from_note, relation)` 那一棵已删** ⚠
            #   · ★ 它被上面那条唯一索引的【前缀】完全覆盖 ⚠
            #   · ★★ 而 `relation` 也从 `(to_note, relation)` 里去掉：
            #     ★ 一条笔记被引用的次数**不多** ⇒ ★ 找到 to_note 后再筛 relation 几乎免费 ⚠
            #     （* `relation` 是 varchar(32) ⇒ ★ 去掉它 **省 32 字节/条**）⚠
            models.Index(fields=["to_note"]),
        ]
        verbose_name = "笔记关联"

    def __str__(self) -> str:
        return f"{self.from_note_id} -{self.relation}-> {self.to_note_id}"


class NoteBlock(TimeStampedModel):
    """★★★ **笔记的一个段落** —— ★★ **段评的锚点**（★ 全案最关键的一张）。

    ## ★★ 为什么必须有稳定 id（* 而不是"第几段"）

    ```
    ❌ 用"第几段"当锚点 ⇒ ★ 上面插一段 ⇒ ★★ 所有段评【整体错位】⚠
       · ★ 而那是静默的**（★ 没人会发现，* 评论就这么挂到了别的段落上）⚠
    ❌ 用"引用文本"当锚点 ⇒ ★ 那段话一被改，* 锚点就断了 ⚠
    ✅ 给每段一个**稳定 id** ⇒ ★ 编辑不影响锚点 ✅
    ```

    ## ★★ 保存时怎么续用旧 id（* `B188` 定的判据：**完全相同**）

    ```
    1. 解析新正文 ⇒ 新段落列表（★ 按【空行】分隔 —— ★ 与渲染无关）
    2. 每段算 fingerprint
    3. ★★ 指纹【完全相同】的旧行 ⇒ **续用原 id** ✅
    4. 匹配不上的新段 ⇒ 建新行；* 没被续上的旧行 ⇒ 删
       ⇒ ★ 它上面的评论 `block_id` 变 NULL（★ 即"失锚"）⚠
    ```

    ## ★★★ 所有者原话（2026-10-14，逐字）

    > 「**还有评论有问题，我想的是如果作者没有删除这段话，那评论就一直挂在这段话上，
    > 不知道这个实现容易吗？有没有引出更大的问题？**」

    > 「**嗯，看来是不容易的。那如果这个段不改，其他端改了，不影响这个段的评论，
    > 更容易实现吗？**」

    > 「**不用，我查了番茄小说的机制，他也是哪怕改一个字，段评就没了的。**」

    ⚠★ 代价（* 如实记）：* 改一个字 ⇒ 该段评论**掉锚** ⇒ 降级到章评区 + 标注 ⚠
      · ★ 而"降级怎么办"由 `note.orphan_comment_policy`（* 项目级策略）决定 ✅
    """

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="blocks")
    #: ★★ **只用于排序显示 —— ★❌ 绝不当锚点** ⚠
    ordinal = models.IntegerField(default=0)
    #: ★ 该段当前文本
    text = models.TextField(blank=True, default="")
    #: ★★ **规范化文本的哈希**（★ 保存时据此续用原 id）——
    #: ⚠★ 2026-10-15（`B199`）：**从 `varchar(64)` 缩到 16** ⚠
    #   · ★ 64 bit 哈希 ⇒ ★ 一篇笔记的段落只有几十个 ⇒ ★ 碰撞概率可忽略 ✅
    #   · ★★ 而它进索引 ⇒ ★ 缩一次 **省 48 字节/条** ⚠
    fingerprint = models.CharField(max_length=16, blank=True, default="")
    #: ★ 冗余计数（* 可重算）
    comment_count = models.IntegerField(default=0)

    class Meta:
        constraints = [
            # ★★ 一篇笔记内 ordinal 不重复 ✅
            models.UniqueConstraint(fields=["note", "ordinal"], name="uniq_note_block"),
        ]
        indexes = [
            # ★★ 对齐就查它（* `note_id + fingerprint`）✅
            models.Index(fields=["note", "fingerprint"]),
            # ⚠★ 2026-10-15（`B199`）：**`(note_id, ordinal)` 那一棵已删** ⚠
            #   · ★ 它被上面那条唯一索引【完全覆盖】⚠
        ]
        verbose_name = "笔记段落"

    def __str__(self) -> str:
        return f"{self.note_id}#{self.ordinal}"


class NoteComment(TimeStampedModel):
    """★★ **一条评论** —— ★★ **章评与段评【同表】**。

    ## ★★ 核心机制：一个"锚点"概念，两种评论

    ```
    anchor_kind = 'chapter'    ⇒ ★ 章评（* 锚在整篇）· block_id 恒 NULL
    anchor_kind = 'paragraph'  ⇒ ★ 段评（* 锚在某一段）· block_id 有值
    ```

    ## ⚠★★ `anchor_kind` 为什么必须有（* 光靠 block_id 分不出来）

    ```
    ★★ 光靠 `block_id IS NULL` **分不出**两种情况：
      · ★ 「章评」（★ 本来就锚在整篇）
      · ★★ 「失锚的段评」（★ 段落被改了）
    ⇒ ★★ 所以必须单独一列，* 且它【创建时就定死，不随锚点失效而变】✅
    ```

    ## ★★ 失锚之后的三个选项（* 所有者 2026-10-14 定）

    > 「**修改段落了，评论默认不再显示，但要给作者三个选项，挂在新写的段落上，
    > 放底部评论区里，默认的不显示。嗯，这个不要每次修改都跳，记录到项目设置里**」

    | 选项 | 落法 |
    |---|---|
    | ★ 挂到新写的段落上 | ★ 保存时把 `block_id` **重钉**到同位置的新块 ✅ |
    | ★ 放到章评区 | ★ `block_id` 置 NULL，* 但 `anchor_kind` 仍是 `paragraph` ⇒ 显示为"原段落已变更" ✅ |
    | ★★ 默认不显示 | ★ 同上，* 只是不出现在列表里（* 仍可在该分组找到）✅ |

    ⚠★ **数据不因策略分裂** —— ★ 失锚评论**仍是评论**（* 一张表）⚠
      · ★ 三个选项只是**展示位置**的三种选择 ⚠
      · ★★ 所以：* 策略改了，* **一条数据都不用搬** ✅
    """

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="comments")
    #: ★★ **是不是段评**（* `False` = 章评 · `True` = 段评）——
    #: ★★ **创建时定死，* 不随锚点失效而变** ⚠
    #:
    #: ⚠★★ 2026-10-15（`B199`）：**从 `anchor_kind` varchar(16) 改成 bool** ⚠
    #:   · ★ 它只有 2 种取值 ⇒ ★ bool **省 15 字节/条** ⚠
    #:   · ★★ 而偏索引的条件要一个【真列】⇒ ★ 属性做不了 ⚠
    #:     （* 实测踩到：* `FieldError: Cannot resolve keyword 'is_paragraph' into field`）⚠
    #:   · ★ 于是**反过来**：* 列存 bool，* `anchor_kind` 变成属性 ✅
    #:     （* 存两份必然打架 —— * 那是被批过的毛病）⚠
    is_paragraph = models.BooleanField(default=False)
    #: ★★ 段评的锚点。★ `SET_NULL`（* ❌ 不是 CASCADE）——
    #: ★★ **引用历史的东西，绝不能被被引用行的删除静默带走** ⚠
    #:   （* `GraphPatch` 的 CASCADE 已经实测闯过一次祸；* 同一类错误不许第二次）⚠
    block = models.ForeignKey(
        NoteBlock,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="comments",
    )
    #: ★★ **这条评论的类型**（* `B214` · 2026-10-17）⚠
    #:
    #: ★★★ 所有者原话（* 逐字）：「**回复和@是两种不同的东西，嗯，视觉效果不一样，
    #:   底层记录这两种不同类型就行**」+「**只要在原来的评论表里加一个类型，
    #:   是回复还是@或者两个一起，就完了呗**」
    #:
    #: ## ★★ 四种取值（* 决定**视觉**，* ⛔ 不决定数据）
    #:
    #: ```
    #: comment 普通     ⇒ 没头没高亮，* 就是一条评论 ✅
    #: reply   回复     ⇒ 头部「回复 @X」（* X = 正文里第一个 @ 的人）✅
    #: mention @提及    ⇒ 正文里的 @ 的人**高亮** ✅
    #: both    两者一起 ⇒ 头部 + 高亮**都渲染** ✅
    #: ```
    #:
    #: ⚠★ **「回复谁」记在正文里**（* `@用户名` 那段文本）——
    #:   · · ★ 所有者裁定：* ⛔ 不建自引用链（* parent 已删）、* ⛔ 不建提及表、
    #:     ⛔ 不加 reply_to 列 ——* 「加一个类型……就完了呗」✅
    #:   · · ★★ 所以类型只回答「**渲染成哪种视觉**」，* 人是谁看正文 ⚠
    KIND_COMMENT = "comment"
    KIND_REPLY = "reply"
    KIND_MENTION = "mention"
    KIND_BOTH = "both"
    KIND_CHOICES = [
        (KIND_COMMENT, "普通评论"),
        (KIND_REPLY, "回复"),
        (KIND_MENTION, "@提及"),
        (KIND_BOTH, "回复+@提及"),
    ]
    #: ★★ `reply` / `mention` / `both` 都要求正文里**至少一个 @ **
    #:   （* 否则「回复 @?」渲染不出来 ——* 后端 400 挡掉，* ⛳ 不让坏数据入库）⚠
    KIND_NEEDS_AT = (KIND_REPLY, KIND_MENTION, KIND_BOTH)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_COMMENT)
    #: ★ 评论正文（* markdown 原文；* 「回复谁」就在这里的 `@用户名`）⚠
    body = models.TextField(blank=True, default="")
    #: ★★ **引用时的原文快照** —— ★ 即便那段后来改了，* 也能显示"当时是这句" ✅
    #:   （* 番茄小说就是这么做的）⚠
    quote = models.CharField(max_length=500, blank=True, default="")
    #: ★ 正常 / 隐藏 / 待审
    state = models.CharField(max_length=16, default="normal")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="note_comments",
    )
    #: ★★ **软删** —— ★ `B214` 去链之后楼中楼不断链了，
    #: ⚠ 但**保留软删**（* 删了就真没了；* 数据留一份，* 只是不显示）✅
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            # ⚠★★ 2026-10-15（`B199`）：`anchor_kind`(varchar16) → `is_paragraph`(bool) ⚠
            #   · ★ 它只有 2 种取值 ⇒ ★ varchar(16) **省 15 字节/条** ⚠
            #   · ★★ 而且能拿来做【偏索引】—— * 每棵树只装自己那类行 ⇒ **体积约减半** ✅
            # ⓪ 章评（* 不锚段落）—— ★★ 这棵树【只装章评】⚠
            models.Index(
                fields=["note", "-created_at"],
                condition=models.Q(is_paragraph=False),
                name="ix_comment_chapter",
            ),
            # ① 段评（* 锚在某一段）—— ★★ 这棵树【只装段评】⚠
            models.Index(
                fields=["block", "-created_at"],
                condition=models.Q(is_paragraph=True),
                name="ix_comment_paragraph",
            ),
            # ⚠★ 2026-10-17（`B214`）：**楼中楼那棵 `(parent, created_at)` 索引【已删】** ⚠
            #   · ★ 所有者裁定：* 评论**不做链状**（* `parent` 一列都没了）⇒
            #     楼中楼不再有「层」，* 也就没有按父查的需求 ✅
            #   · ★ 「回复谁」记在**正文的 @** 里（* 只有 `kind` 一列决定视觉）✅
            # ③ "我的评论"
            models.Index(fields=["created_by", "-created_at"]),
        ]
        verbose_name = "评论"

    @property
    def anchor_kind(self) -> str:
        """★★ `'chapter'` / `'paragraph'`（★ 由 `is_paragraph` 派生）。

        ⚠★ **接口契约不变** —— ★ 前端照旧收 `anchor_kind` ✅
          · ★ 而库里只存那个 1 字节的 bool ⚠
          · ★★ 派生 ⇒ ★ 不可能不一致 ✅
        """
        return "paragraph" if self.is_paragraph else "chapter"

    def __str__(self) -> str:
        return f"{self.note_id}:{self.anchor_kind}:{self.pk}"


class NoteLike(TimeStampedModel):
    """★★ **一个赞** —— ★★ **章赞与段赞【同表】**。

    ## ⚠★★ 幂等约束：**普通 UNIQUE 挡不住重复的"章赞"** ⚠

    ```sql
    -- ❌ 这样写挡不住：
    UNIQUE (note_id, user_id, block_id)
    -- ★★ PostgreSQL 认为【两个 NULL 不相等】⇒
    --    ★ block_id 为 NULL 的行可以插【任意多份】⚠
    --    ★★ 于是"同一个人对同一篇笔记点了 100 次章赞" ✅ 通过 ⚠

    -- ✅ 正解一（* 本机 PG 17.11 支持）：
    UNIQUE NULLS NOT DISTINCT (note_id, user_id, block_id)

    -- ✅ 正解二（* 2026-10-15 采用）：**拆成两条偏唯一索引** ⚠
    --   · ★ 各 12 字节（* 比三列合一的 20 字节省）✅
    --   · ★★ 语义还更清楚 ✅
    ```

    ⚠★ 为什么最终选"正解二"而不是 `NULLS NOT DISTINCT`：
      ★★ 两条偏索引**每棵只装自己那类行** ⇒ ★ 体积更小、* 语义更清 ⚠
      · ★ 而 `NULLS NOT DISTINCT` 是一棵**装全部**的索引 ⚠
    """

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="likes")
    #: ★★ `is_paragraph`（* 取代原先的 `anchor_kind` varchar(16)）——
    #: ★ 只有 2 种取值 ⇒ ★ bool **省 15 字节/条** ⚠
    is_paragraph = models.BooleanField(default=False)
    #: ★★ **段赞指着哪个段落**（* 章赞恒 NULL）⚠
    #:
    #: ⚠★★ 2026-10-17（`B211`①）：`SET_NULL` ⇒ **`CASCADE`** ⚠
    #:
    #: ★★ 为什么改（* 所有者裁定：* 段赞锚点被删 ⇒ 赞跟着没）：
    #:   · ★ 段落被 realign 删掉时（* 改了字的段换新 id），* 赞**跟着删**、* 计数 −1 ✅
    #:   · ★★ 而 `SET_NULL` 的后果是**静默养脏数据**：
    #:     · · ★ ⓪ PG 里两个 NULL **互不相等** ⇒* 偏唯一索引 `(block,user)` 挡不住
    #:       ⇒* 同一用户能在同一篇上堆**多行失锚赞**（* 赞了新段 + 旧的挂着）⚠
    #:     · · ① 合并计数**只涨不减**（* 失锚行永远算在里面）⚠
    #:     · · ② 取消时按 `block_id` 匹配不到 NULL 行 ⇒* `removed:false`
    #:       ⇒* **那个赞永远取消不掉** ⚠
    #:   · ★★ 判据（* `B212`①）：* 计数错误必须**有界且自愈** ——*
    #:     SET_NULL 的错误随时间累积，* ❌ 系统性漂移；* CASCADE 的错误是
    #:     「锚点没了赞没了」，* ✅ 有界、* 可解释、* 与失锚评论同一族思想 ⚠
    block = models.ForeignKey(
        NoteBlock,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="likes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="note_likes",
    )

    class Meta:
        constraints = [
            # ★★ 章赞：一人一次（* 偏唯一索引）✅
            models.UniqueConstraint(
                fields=["note", "user"],
                condition=models.Q(is_paragraph=False),
                name="uniq_like_chapter",
            ),
            # ★★ 段赞：一人一次（* 偏唯一索引）✅
            models.UniqueConstraint(
                fields=["block", "user"],
                condition=models.Q(is_paragraph=True),
                name="uniq_like_paragraph",
            ),
        ]
        verbose_name = "点赞"

    def __str__(self) -> str:
        return f"{self.note_id}:{self.user_id}"


class NoteRevision(TimeStampedModel):
    """★★ **一篇笔记的一个历史版本**（★ 环形缓冲）。

    ## ★★★ 所有者原话（2026-10-14，逐字）

    > 「**笔记要有历史版本，不过不用太多，最多追溯10个版本就行**」

    > 「**嗯，这才对嘛，保存十个是保持最近十个，你别到了十个就不保存了**」

    ## ★★ 环形缓冲语义（* 四条，* 缺一条就会实现错）

    ```
    ① ★★ **一直存，永不停止** ⚠
       · ★ 每存一份新的 ⇒ **删掉最老的那一份** ✅
       · ★★ ❌ 不是"满 10 个就停"（* 那是最容易实现错的一处）⚠
    ② ★★ 上限是【每篇笔记】最近 N 份 ⚠
       · ★ 不是全局、* 也不是每个用户总共 N 份 ✅
    ③ ★★ 「当前正文」【不占】那 N 个位置 ⚠
       · ★ `Note.body` = 现在这一版；* 本表装**历史** ⚠
       · ★ 回档 = 把某一份历史**恢复成当前** ✅
    ④ ★ 超出上限即【永久】删 ⚠
       · ★ 这是**有意的**（* 否则无上限）⚠
       · ★ 界面须说明「更早的已不可恢复」⚠
    ```

    ## ★★ 触发方式（* `B191` 定：**定时自动**）

    ★ 业界先例：* 口袋写作「**每三分钟自动存一次档**」⚠
    ★★ 而实现上**不需要后台定时器**：
      · ★ 用户保存正文时，* 顺手判断"距上次快照是否超过间隔" ⇒ 超了就存一份 ✅
      · ★★ 没人写的时候本来就没有新内容可存 ⇒ ★ 定时器纯属浪费 ⚠

    ⚠★ 间隔与上限都在**用户档设置**里（* `note.revision_interval` / `note.revision_limit`）：
      · ★★ 且都是 `gated=True` ⇒ ★ **只有管理员能改** ⚠
      · ★（* 所有者 2026-10-14：*「**历史版本数是网站管理员可以给每个用户单独指定**」）⚠
    """

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="revisions")
    #: ★ 那一版的正文
    body = models.TextField(blank=True, default="")
    #: ★ 那一版的标题
    title = models.CharField(max_length=120, blank=True, default="")
    #: ★★ **那一版的字数** —— ★ 口袋写作的历史版本列表就显示"时间和字数"⚠
    word_count = models.IntegerField(default=0)
    #: ★ `auto`（定时）/ `manual`（点了存稿）
    source = models.CharField(max_length=16, default="auto")

    class Meta:
        constraints = [
            # ★★ 一篇笔记一个时刻只有一版 ✅
            models.UniqueConstraint(
                fields=["note", "created_at"], name="uniq_note_revision"
            ),
        ]
        # ⚠★ 2026-10-15（`B199`）：**`(note_id, -created_at)` 那一棵已删** ⚠
        #   · ★ 它被上面那条唯一索引【完全覆盖】⚠
        verbose_name = "笔记版本"

    def __str__(self) -> str:
        return f"{self.note_id}@{self.created_at:%Y-%m-%d %H:%M}"
