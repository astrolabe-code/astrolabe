"""Astrolabe · ② 作业层：**作业投递**（① Web 层唯一允许调用的 jobs 入口）

★ 依据 `JOB-MODEL.md` J9：
    ① Web（Django） ── 写一条 Job 记录 + 推 Redis ──→ ★ 立刻返回 job_id
    ② 作业层（worker）←── 从队列领取 ──→ 执行 → 写回 Job 表

★★ **对 `ARCHITECTURE.md` A3 红线 #2 的精确化**（`B131`）——

原文写「❌ **① Web 层** import **② 的 worker 代码**」。这句话的**本意**是：
★ ❌ 不得在 **Web 请求里执行**耗时工作（那会让 web 线程被占住 ⇒ 单机凭空丢掉大部分容量）。

但**字面**执行会得出一个荒谬结论：① 不能把作业推进队列 ——
那 ① 就只能"写 Job 记录然后等别人来捞"，必须额外引入**轮询 Job 表**的第二套机制。

⇒ ★ **精确口径**（本模块就是这条口径的落点）：

| | 允许？ |
|---|---|
| ① 可以 import **本模块**（`dispatch`，**投递**） | ✅ |
| ① 不得 import `run_worker` / `jobs.tasks`（**执行**） | ❌ |

⚠ 判据：**「投递」是 O(毫秒) 的两次写，「执行」是 O(分钟) 的重活。**
"""

from __future__ import annotations

import logging

from django.db import transaction

from core import appsettings
from jobs import queue
from jobs.models import Job

log = logging.getLogger("astrolabe.jobs.dispatch")


class QueueBusy(Exception):
    """★★ **队列满了 / 你排得太多** —— 带着**给用户看**的原因 ⚠

    ⚠ 为什么不在 `enqueue()` 里静默丢弃：`B115` ①「投递即入队，❌ 不得静默拒绝」——
      静默丢会让用户看到"排队中"却永远轮不到（最糟的一种体验）。
      ⇒ 这里**在创建 Job 之前**就拦住，并把原因原样传给用户 ✅
    """


#: ★★ 全局队列闸门的**事务级咨询锁**编号（全站唯一，⚠ 不要改）⚠
#:   用它把"所有提交"串起来 —— 否则 N 个并发请求会同时看到"还没满" ✅
_QUEUE_LOCK_ID = 0x4153544C  # "ASTL"


def _check_capacity(project_ref: str) -> None:
    """★★ **队列公平闸门**（在创建 Job 之前调用）⚠

    ```
    ① 全局：队列深度 ≥ queue_max_jobs（管理员底线）⇒ 拒绝
    ② 单人：该用户"排队中 + 执行中"的作业 ≥ min(档位 parse_concurrency, queue_user_max)
            ⇒ 拒绝
    ```

    ⚠ 为什么要②：单个 worker 串行消费 ⇒ 一个人投 20 条，别人就排在后面干等 ⚠
    ⚠ 档位值只能**更小**：管理员那条线是底线，⛔ 特权不能突破安全边界
    """
    from django.db import connection

    global_cap = int(appsettings.get("queue_max_jobs") or 0)
    if global_cap > 0:
        # ★★ 先取**事务级咨询锁**：让并发提交在这里排队（提交/回滚时自动释放）⚠
        #   ⚠ 没有它：N 个请求同时看到"队列还没满"⇒ 一起进 ⇒ 溢出 N−1 条（没有上限）
        #   ⚠ 顺序固定（先全局锁、再用户行锁）⇒ 不会互相死等
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [_QUEUE_LOCK_ID])
        # ★ 深度数**数据库里的排队作业**（权威），⛔ 不用 Redis 计数：
        #   Redis 那边没有事务语义，读了也不能保证"读了就还成立"
        depth = Job.objects.filter(state=Job.STATE_QUEUED).count()
        if depth >= global_cap:
            raise QueueBusy(
                f"解析队列已满（{depth}/{global_cap}），请稍后再提交；"
                "★ 已有的作业会按顺序出图。"
            )

    # ---- 单用户：先找到这个人所有的项目 ref（Job 上 `project` 外键大多是 NULL）
    from core.models import Project

    row = (
        Project.objects.filter(project_ref=project_ref)
        .values_list("owner_id", "owner__profile__tier")
        .first()
    )
    if not row or not row[0]:
        return
    owner_id, tier = row
    # ★★ 锁住这个人那一行：同一用户的并发提交**串行化** ⚠
    #   （不同用户互不影响；持锁时间 = 一次 count + 一次 insert，毫秒级）
    from django.contrib.auth import get_user_model

    get_user_model().objects.select_for_update().filter(pk=owner_id).exists()

    refs = list(
        Project.objects.filter(owner_id=owner_id).values_list("project_ref", flat=True)
    )
    if not refs:
        return

    tier_cap = int(appsettings.quota_for(tier or "free").get("parse_concurrency") or 1)
    admin_cap = int(appsettings.get("queue_user_max") or 0)
    cap = min(tier_cap, admin_cap) if admin_cap > 0 else tier_cap
    if cap <= 0:
        return

    active = Job.objects.filter(
        project_ref__in=refs, state__in=(Job.STATE_QUEUED, Job.STATE_RUNNING)
    ).count()
    if active >= cap:
        raise QueueBusy(
            f"你已经有 {active} 个解析在排队或正在跑（上限 {cap} 个），"
            "等它们出图后再提交新的。"
        )


def submit(
    *,
    kind: str,
    project_ref: str,
    payload: dict | None = None,
    priority: int = 0,
    dedup_key: str = "",
    skip_limits: bool = False,
) -> tuple[Job, bool]:
    """创建 Job 记录并**投递入队**。

    Returns:
        `(job, created)` —— `created=False` 表示命中了 `dedup_key`、**合并到已有作业**。

    ★★ `B115` 四条硬要求（本函数是它们唯一的落点）：

    | # | 要求 | 本函数怎么满足 |
    |---|---|---|
    | ① | **投递即入队**，❌ 不得静默拒绝 | 入队失败 ⇒ ★ **把 Job 置 `failed` 并抛异常**，❌ 绝不假装成功 |
    | ② | 排队状态可见 | `queue_position` 由 `queue.queue_size()` 另算（见 jobs 接口） |
    | ③ | 并发粒度合理 | ★ 每用户 = min(档位 `parse_concurrency`, 管理员 `queue_user_max`)；全局 = `queue_max_jobs`，**都在事务内取锁后判定** ⚠ |
    | ④ | 幂等键语义正确 | 相同 `dedup_key` ⇒ ★ **合并到已有 Job 并返回同一个 id**（不是失败） |

    ⚠ **为什么"入队失败"必须显式失败**：Redis 挂了但 Job 记录留在 `queued`，
      用户会看到"排队中"却**永远不会被处理** —— 这是最糟的一种体验（静默黑洞）。
    """
    payload = payload or {}

    # ④ 幂等合并 —— ⚠ 挪到事务里做（与容量检查同锁区），否则"同键两请求"也会各建一条

    # ---------------------------------------------------------------- 创建 + 入队
    # ★★ 队列公平检查**必须和建作业在同一个事务里**（`2026-11-01`）⚠
    #   以前它在事务外：检查完到建作业之间有一个窗口，
    #   窗口期内 N 个并发请求全都看到"还没满" ⇒ 一起通过 ⇒ **溢出没有上限** ⚠
    #   现在：事务内取锁（全局咨询锁 + 用户行锁）后计数 ⇒ 并发也只有一个人通过 ✅
    with transaction.atomic():
        if not skip_limits:
            _check_capacity(project_ref)

        # ---------------------------------------------------------------- ④ 幂等合并
        if dedup_key:
            existing = (
                Job.objects.filter(
                    dedup_key=dedup_key,
                    state__in=(Job.STATE_QUEUED, Job.STATE_RUNNING),
                )
                .order_by("-queued_at")
                .first()
            )
            if existing is not None:
                log.info("作业去重命中：dedup_key=%s ⇒ Job#%s", dedup_key, existing.pk)
                return existing, False

        job = Job.objects.create(
            project_ref=project_ref,
            kind=kind,
            state=Job.STATE_QUEUED,
            payload=payload,
            priority=priority,
            dedup_key=dedup_key,
        )

    try:
        queue.enqueue(job.pk, priority)
    except Exception as exc:  # noqa: BLE001 —— ★ B115 ①：绝不静默
        job.state = Job.STATE_FAILED
        job.error_code = "enqueue_failed"
        job.error_msg = f"投递失败：{exc}"[:2000]
        job.save(update_fields=["state", "error_code", "error_msg"])
        log.exception("作业投递失败：Job#%s", job.pk)
        raise

    job.stage = "排队中"
    job.save(update_fields=["stage"])
    return job, True


def queue_position(job: Job) -> int:
    """★ `B115` ② 排队可见 —— 该作业前面还有几个。

    ⚠ 精确位置需要遍历 zset，这里用**队列总长**做上界估计（够前端展示"前面还有 N 个"）。
    """
    if job.state != Job.STATE_QUEUED:
        return 0
    try:
        return int(queue.queue_size())
    except Exception:  # noqa: BLE001 —— ⚠ 排队位置是"锦上添花"，Redis 挂了不该让接口失败
        return 0
