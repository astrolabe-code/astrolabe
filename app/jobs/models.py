"""Astrolabe · 作业：Job 表

★ 依据：JOB-MODEL.md  J3（表结构）· J4（状态机）· J5（并发与排队策略）

★★ `B115` 四条硬要求（**实现时逐条对照**）：
     ① 投递即入队（❌ 不得静默拒绝）
     ② 排队状态可见（queue_position / eta_s / stage）
     ③ 并发粒度合理（❌ 不用「每用户全局 1」限死排队）
     ④ 幂等键语义正确（重复投递 = ★ 合并，不是失败）

⚠ 旧缺陷（B115 记录，勿重犯）：`dedup_key` 静默拒绝 · 投递失败置 error · `job_max_per_user=1`
"""

from django.db import models


class Job(models.Model):
    """解析 / 索引等作业。

    ★ 状态只有 5 个（J4）—— ❌ 不再引入旧设计里的额外状态。
    """

    # ---- 状态机（J4）----
    STATE_QUEUED = "queued"
    STATE_RUNNING = "running"
    STATE_DONE = "done"
    STATE_FAILED = "failed"
    STATE_CANCELED = "canceled"
    STATE_CHOICES = [
        (STATE_QUEUED, "排队中"),
        (STATE_RUNNING, "执行中"),
        (STATE_DONE, "已完成"),
        (STATE_FAILED, "失败"),
        (STATE_CANCELED, "已取消"),
    ]

    # ---- 作业类型 ----
    KIND_PARSE = "parse"
    #: ★ 热度合并（Redis 热数据 → 数据库权威值）—— 由定时器 / 管理命令投递
    KIND_HEAT_FLUSH = "heat_flush"
    KIND_CHOICES = [
        (KIND_PARSE, "解析项目源码并产图"),
        (KIND_HEAT_FLUSH, "合并节点热度（Redis → 数据库）"),
    ]

    # ⚠ 与 core.ProjectRefMixin 保持一致（长度 64，见那里的说明）
    project_ref = models.CharField(max_length=64, db_index=True)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_QUEUED)

    payload = models.JSONField(default=dict, blank=True)

    # ★★ B115 第 ④ 条：相同 dedup_key ⇒ 【合并到已有 Job】并返回同一个 id
    #    ⚠ 绝不像旧实现那样「静默拒绝」
    dedup_key = models.CharField(max_length=128, blank=True, default="", db_index=True)

    # ★ 数值越大越优先（J5：小项目给高优先级 → 快速周转，体感最好）
    priority = models.SmallIntegerField(default=0)

    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # ★ B115 第 ② 条：排队与进度【可见】
    progress = models.SmallIntegerField(default=0)          # 0–100
    stage = models.CharField(max_length=64, blank=True, default="")  # 人类可读阶段
    eta_s = models.IntegerField(null=True, blank=True)      # 预计剩余秒数

    attempts = models.SmallIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_msg = models.TextField(blank=True, default="")
    worker_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        indexes = [
            # ★ 队列取作业：按 (priority DESC, queued_at ASC)（J3）
            models.Index(fields=["state", "-priority", "queued_at"]),
            models.Index(fields=["project_ref", "state"]),
        ]

    def __str__(self) -> str:
        return f"Job#{self.pk} {self.kind} {self.state}"
