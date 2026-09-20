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
    name = models.CharField(max_length=200)
    desc = models.TextField(blank=True, default="")

    #: ⚠ **可为空**（有意）：公开项目在被**原作者认领**之前，owner 可以是平台代管。
    #: 认领是路线图里的「社区纠错 · 原作者认领」。
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="projects",
    )

    # ------------------------------------------------------------------ 来源
    # ★ B109：源码**只能由服务端从托管平台获取** ⇒ 这里存的是「来源」，❌ 不是源码
    PROVIDER_GITHUB = "github"
    PROVIDER_GITEE = "gitee"
    PROVIDER_CHOICES = [
        (PROVIDER_GITHUB, "GitHub"),
        (PROVIDER_GITEE, "Gitee"),
    ]
    provider = models.CharField(max_length=16, choices=PROVIDER_CHOICES, blank=True, default="")
    repo_url = models.CharField(max_length=512, blank=True, default="")
    #: ★ 钉住的版本 —— ⚠ 一期：项目绑定一个 commit，换 commit ⇒ 重新解析
    #: （⚠ 图不可变 + 快照/epoch 是后续的事，见 GRAPH-STORAGE.md G1）
    commit = models.CharField(max_length=64, blank=True, default="")

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
    is_paid = models.BooleanField(default=False)
    #: ★ 定价说明（**展示用的一段文字**）—— ★★ **平台不参与定价**（`U9.1` 第 1 行）
    #: ⚠ 它不是金额字段 —— 一期读者私下付给作者，平台只负责"谁能看"的开关（`U9.6`）
    price_note = models.CharField(max_length=200, blank=True, default="")

    # ------------------------------------------------------------------ 许可核验
    # ★ 依据 `core/licensing.py`（`U3.4` / `B143`）
    #: ★ 识别出的 SPDX 标识（空 = 未识别 / 无许可证文件）
    license_spdx = models.CharField(max_length=64, blank=True, default="")
    #: ★ 类别：permissive / copyleft / restrictive / unknown / missing
    license_category = models.CharField(max_length=16, blank=True, default="")
    #: ★★ **"无许可证放行"的显式标记**（`U3.7` 配套建议 1）
    #: ⚠ 作用：★ **将来批量收回** —— 用户说"以后我是不会放行没许可证的"，
    #:   那时要能**一键筛出来**（❌ 不能靠翻审计）
    license_exception = models.BooleanField(default=False, db_index=True)
    #: ★ 检测证据（文件名 / SPDX / 原文片段）—— ★ **"我们凭什么这么判"的留痕**
    license_evidence = models.JSONField(default=dict, blank=True)

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
    graph_built_at = models.DateTimeField(null=True, blank=True, db_index=True)

    #: ★★ **定版时钉住的实际 ref**（★ 拉取时用的分支/tag/sha）——
    #: ★ 有了它，将来才回答得了"这张图是哪一版代码的"（★ 且它与 `graph_built_at` 同生共死）。
    resolved_ref = models.CharField(max_length=128, blank=True, default="")

    # ------------------------------------------------------------------ 定版判据
    @property
    def is_graph_built(self) -> bool:
        """★★ **图是否已定版** —— ★ 定版后**不可再解析**（`B103` / `B155`）。"""
        return self.graph_built_at is not None

    class Meta:
        indexes = [
            models.Index(fields=["is_public", "-created_at"]),
            models.Index(fields=["owner", "-created_at"]),
            # ★ 审核队列：按状态 + 时间（★ 管理员的待办清单）
            models.Index(fields=["review_state", "-created_at"]),
        ]
        verbose_name = "项目"

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
    ACTION_PUBLISH = "publish"
    #: ★★★ `B169`：**拉取代码**（★ 对**已有项目**发起）——
    #:   ⚠★ 与 `ACTION_PUBLISH` 一样**必须当场校验归属**：★ 两者都会让服务端**去拉一个远端仓库** ⚠
    ACTION_FETCH = "fetch"
    ACTION_CHOICES = [
        (ACTION_LOGIN, "登录 / 注册"),
        (ACTION_PUBLISH, "发布项目（需★当场校验归属）"),
        (ACTION_FETCH, "拉取代码（需★当场校验归属）"),
    ]

    #: ★ 随机串（★ primary key ⇒ **天然唯一**）
    state = models.CharField(max_length=64, primary_key=True)
    provider = models.CharField(max_length=16, choices=OAuthIdentity.PROVIDER_CHOICES)

    #: ★★ **意图** —— ★ 决定回调时走「登录」还是「注册 + 当场校验归属」
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, default=ACTION_LOGIN)

    #: ★ 邀请码（★ `U4.8` 流程第 ② 步：**跳转前就填好**）
    invite_token = models.CharField(max_length=64, blank=True, default="")
    #: ★ 登录成功后的去处
    next_url = models.CharField(max_length=512, blank=True, default="")
    #: ★ 发布场景：要校验归属的仓库 + 目标项目
    repo = models.CharField(max_length=512, blank=True, default="")
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
