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

    #: ★★★ **这条基图的「请求地址」**（★ `B181` · 2026-10-13）⚠
    #:
    #: ★★ 所有者原话（逐字）：
    #:
    #: > 「**基图数据应该记录对应的请求地址**，比如 https://github.com/chk/repo/blob/{sha}/，
    #: > 以后对比这个地址，就知道取的是不是同一份数据」
    #:
    #: ★ 它是**规范化之后**的地址（★ 见 `canonical_url()`）——
    #:   ★★ 同一个仓库的 `Chk/Repo` 与 `chk/repo` 会得到**同一条** ✅
    #:
    #: ★★ 为什么要**存下来**而不是每次算：
    #:   · ★ 所有者要求「**记录**」（★ 原话）✅
    #:   · ★★ 取出后校验地址时**只是一次字段比较**（★ 见 `graph/binding.py::find()`）⚠
    #:   · ★ ★★ 调试路径的地址（`file://…`）**依赖源码目录** —— ★ 那目录事后
    #:     可能已经没了，★ 不存就再也算不出来 ⚠
    #:
    #: ⚠ 存量行的这个字段可能是空的 ⇒ ★ `canonical` 属性会**现算一个**兜底 ✅
    request_url = models.CharField(max_length=1024, blank=True, default="")

    #: ★★★ **基图的「身份证号」**（★ `B181`）⚠
    #:
    #: ★★ 所有者原话（逐字）：
    #:
    #: > 「**如果比较字符串比较麻烦，毕竟前面的https这些一模一样，
    #: > 可以用这个地址生成唯一的ID来比较，这是基图的身份证号。**」
    #:
    #: ★ 它是 `canonical` 的 SHA-256 取前 32 位（128 bit）——
    #:   ★★ **不是随机发的**，★ 而是**由地址算出来** ⇒ ★ 同一个地址永远得到同一个号 ✅
    #:   ★★ 所以【不用查库】就能算出"该是哪一份" ⚠
    #:
    #: ★★ 它同时是 Redis 映射的键（★ 见 `graph/binding.py`）——
    #:   ★ 所有者原话：「**用 redis 缓存最常用的哪些地址对应的图数据的位置，
    #:     以后直接取，不要频繁搜索数据库比较**」⚠
    graph_key = models.CharField(max_length=32, blank=True, default="", db_index=True)

    class Meta:
        constraints = [
            # ★★★ 一份源码版本**只有一份基图** —— ★ 这就是"不重复解析"的落脚点 ✅
            #   ⚠★ `B181`：判据从「三个字段各自相等」换成「**身份证号相等**」——
            #     ★★ 因为三个字段里只要有一个**大小写不同**就会漏判 ⚠
            #     （★ 实测过：`chk/repo` / `Chk/Repo` / `chk/Repo` 曾造出 **3 份**基图）
            #
            # ⚠★ **无条件唯一**（★ 所有者 2026-10-13 裁定：「这些字段按设计就是要有值的」）——
            #   ★★ 所以**每一行都必须有身份证号**，★ 没有例外 ⚠
            #   · ★ 远端源码 ⇒ 由 `https://…/blob/{sha}` 算出
            #   · ★ 调试源码 ⇒ 由 `file://{目录}` 算出
            #   · ★★ 两者都推不出来（★ 存量老行）⇒ 用 `legacy://…` 明确标记 ✅
            #     （★ 见 `graph/binding.py::get_or_create` 与数据迁移的回填）
            #   ⚠ 我一度想加 `condition=~Q(graph_key="")" 让空号不参与 —— ★ **那是错的**：
            #     ★★ 它把"字段没值"这个**异常状态**变成了**合法状态** ⚠
            #     ★ 而空号的行**谁都查不到**（★ `find()` 算不出地址就返回 None）⇒
            #       ★★ 等于在库里埋一个**永远孤立**的行 ⚠
            models.UniqueConstraint(fields=["graph_key"], name="uniq_base_graph_key"),

            # ------------------------------------------------------------------
            # ⚠★★ 2026-10-14（`B184`）：**`request_url` 只许远端形态** ⚠
            #
            # ★★ 所有者原话（逐字）：
            #   「**只能有远端形式也就是从github之类的上拉取，不能有上传文件，
            #     这留下了一个攻击缺口…所以，基图里这个字段只有唯一合法的样式，且不能为空**」
            #
            # ★★ 为什么必须由**数据库**挡（★ 而不是只靠应用层）：
            #   · ★ 应用层校验**可以被绕过**（★ 漏一个入口、★ 或者将来新写一个入口）⚠
            #   · ★★ 而这是**身份字段** —— ★ 它错了不会报错，
            #     ★★ 只会**静默地**把不同代码挤成同一份基图 ⚠
            #     （★ 库里已有实例：`someone_else/demo` 两份基图，★ 一份 legacy 一份 file）⚠
            #
            # ★ 正则口径（★ 与 `canonical_url()` 的实现逐字对齐）：
            #   · ★★ `^https://`                ← ★★ **file:// / legacy:// / 空串全挡掉** ⚠
            #   · ★ `(github\.com\|gitee\.com)`  ← ★ 只认这两个平台（★ 与 `_HOSTS` 一致）⚠
            #   · ★ `[^/]+/[^/]+`               ← ★ `owner/repo`
            #   · ★ `/blob/`                    ← ★ 必须是 blob 形态
            #   · ★ `[0-9a-f]{7,64}`            ← ★★ **必须是 hex**（★ 小写）⚠
            #     （★ 下界 7：★ GitHub 允许短 sha；★ 上界 64：★ sha-1 是 40、sha-256 是 64）⚠
            # ------------------------------------------------------------------
            models.CheckConstraint(
                check=models.Q(
                    request_url__regex=r"^https://(github\.com|gitee\.com)/[^/]+/[^/]+/blob/[0-9a-f]{7,64}$"
                ),
                name="chk_basegraph_request_url_remote",
            ),
        ]
        indexes = [
            # ★ 按【仓库】列它的全部版本（★ 拉取前的复用查询走 `graph_key`，❌ 不走这条）
            models.Index(fields=["provider", "repo_full_name"]),
        ]
        verbose_name = "基图"

    def __str__(self) -> str:
        return f"{self.provider}:{self.repo_full_name}@{self.sha[:12]}"

    # ------------------------------------------------------------------ 规范化
    #: ★ 各平台的【主机名】（★ 规范化地址用）—— ⚠ 必须显式写，❌ 不猜
    _HOSTS = {"github": "github.com", "gitee": "gitee.com"}

    @classmethod
    def canonical_url(cls, provider: str, repo_full_name: str, sha: str) -> str:
        """★★★ **这份基图的正规请求地址**（★ `B181` 的「身份证」之源）。

        ★★ 所有者原话：「**基图数据应该记录对应的请求地址，
          比如 https://github.com/chk/repo/blob/{sha}/**」

        ## ⚠★★ 规范化是**这里的全部重点**

        ★★ 为什么必须规范化：★ 平台认为**同一个仓库**的地址，★ 大小写却可以不同 ⚠

        | 用户输入 | 平台认为 |
        |---|---|
        | ★ `github.com/Chk/Repo` | ✅ 与 `chk/repo` **是同一个** |
        | ★ `github.com/chk/repo/`（末尾斜杠）| ✅ 同上 |
        | ★ `github.com/chk/repo` | ✅ 同上 |

        ⇒ ★★ 不规范化 ⇒ ★ 同一份代码会**被解析多次** ⚠
          （★ 而那正是 `B179` 要消灭的事：「用户拉一个图就解析一次，太浪费算力」）⚠

        ★ 规范化规则（★ 三条，★ 都是"平台怎么认"决定的，❌ 不是我们发明的）：

        | # | 规则 | 依据 |
        |---|---|---|
        | 1 | ★ `provider` 转小写 | ★ 我们自己的枚举，★ 一律小写 |
        | 2 | ★★ `owner/repo` 转**小写** | ★★ GitHub / Gitee 的仓库名**大小写不敏感** ⚠ |
        | 3 | ★ `sha` 转小写 | ★ hex 一律小写（⚠ 大写 hex 是同一个 commit）|

        ## ⚠★★ 2026-10-14（`B184`）：**调试路径整条取消** ⚠

        ★★ 以前没有 sha 时会退成 `file://{目录}` —— ★ 现已删除 ⚠

        ★★ 所有者的理由：★ 那让「**基图的身份**」变得**不可验证** ⚠
          （★ 本地目录既没有 sha、★ 别人也无法复核）⚠
          ★★ 而基图是**所有项目共享**的 ⇒ ★ 那就是**攻击缺口** ⚠

        ★★ 现在的行为：★ 没有可锚定的 sha ⇒ ★ **直接抛 `ValueError`** ⚠
          （★ 见函数体末尾的注释 —— ★❌ 不返回空串，★ 因为那会撞成同一个身份证号）⚠
        """
        prov = (provider or "").strip().lower()
        full = (repo_full_name or "").strip().strip("/").lower()
        commit = (sha or "").strip().lower()

        if len(commit) >= 7 and all(ch in "0123456789abcdef" for ch in commit):
            # ---- ★ 真 sha ⇒ 远端仓库的永久地址 ✅
            host = cls._HOSTS.get(prov)
            if not host or not full:
                raise ValueError(
                    "基图身份不合法：provider 或仓库名为空"
                    f"（provider={provider!r}, repo_full_name={repo_full_name!r}）"
                )
            return f"https://{host}/{full}/blob/{commit}"

        # ⚠★★ 2026-10-14（B184）：**调试路径整条取消** ⚠
        #
        # ★★ 以前这里会退回 `file://{目录}`（★ 没有 sha 时）——
        #   ★★ 而那让「基图的身份」变得**不可验证** ⚠
        #     （★ 本地目录既没有 sha、★ 别人也无法复核）⚠
        #   ★★ 而基图是**所有项目共享**的 ⇒ ★ 那就是**攻击缺口** ⚠
        #
        # ★★ 所有者原话（B184）：
        #   「**只能有远端形式也就是从github之类的上拉取，不能有上传文件，
        #     这留下了一个攻击缺口…所以，基图里这个字段只有唯一合法的样式，且不能为空**」
        #
        # ⚠★ 为什么是 **raise** 而不是 return ""：
        #   ★★ `key_of("")` 是一个**常量**（★ sha256 空串）⚠
        #   ⇒ ★ 返回空串会让**所有非法输入撞成同一个身份证号** ⚠
        #     （★ 而那正是"两个不同目录挤成一份基图"那条静默错的根）⚠
        #   ⇒ ★★ 所以必须**当场抛错**，★ 让调用方在处理前就失败 ✅
        raise ValueError(
            "基图身份不合法：没有可锚定的 commit sha"
            f"（provider={provider!r}, repo_full_name={repo_full_name!r}, sha={sha!r}）"
            "—— B184 起只接受远端仓库的 commit sha"
        )

    @staticmethod
    def key_of(canonical_url: str) -> str:
        """★★★ **由地址算出身份证号**（★ `B181`）。

        ★★ 为什么用哈希而不是直接存地址比：

        | | 直接比地址字符串 | ★ 比身份证号 |
        |---|---|---|
        | ★ 存哪 | 要存整条 URL | ★ **32 字符** |
        | ★ 比什么 | 逐个字符 | ★ **一次定长比较** |
        | ★★ 当 Redis 键 | ★ 键长、且 `{}` 之类要转义 | ★★ **干净利落** ✅ |

        ★ 取 **SHA-256 前 32 位**（= 128 bit）——
          ★ 碰撞概率约 1/3.4×10^38，★ 而基图量级是"几十万"⇒ ★ **可以认为不会撞** ✅
        """
        import hashlib

        return hashlib.sha256((canonical_url or "").encode("utf-8")).hexdigest()[:32]

    @property
    def canonical(self) -> str:
        """★ 这一行的正规地址。

        ⚠★ **优先用存下来的 `request_url`**（★ 所有者要求「记录」）——
          ★★ 只有存量行（★ 迁移还没回填）才现算兜底 ✅
        """
        return (self.request_url or "").strip() or self.canonical_url(
            self.provider, self.repo_full_name, self.sha
        )

    @property
    def blob_url(self) -> str:
        """★ 某个文件的**永久链接**前缀（★ 拼上路径与行号就能跳转）。

        ★★ `B181` 之后它就是 `canonical`（★ 规范化后的地址）——
        ★ 以前这里会**原样拼** `repo_full_name`，★ 于是 `Chk/Repo` 会给出
          `…/blob/Chk/Repo/…` 这种地址 ⚠（★ GitHub 认，★ 但同一份基图会有好几种写法）⚠
        """
        url = self.canonical
        # ⚠★ 只有 https 的才是【能点的网页链接】✅
        #   ★ `file://…`（调试路径）**不是** —— ★ 给了也点不开 ⚠
        return url if url.startswith("https://") else ""


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
