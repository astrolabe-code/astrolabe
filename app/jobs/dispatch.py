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

from jobs import queue
from jobs.models import Job

log = logging.getLogger("astrolabe.jobs.dispatch")


def submit(
    *,
    kind: str,
    project_ref: str,
    payload: dict | None = None,
    priority: int = 0,
    dedup_key: str = "",
) -> tuple[Job, bool]:
    """创建 Job 记录并**投递入队**。

    Returns:
        `(job, created)` —— `created=False` 表示命中了 `dedup_key`、**合并到已有作业**。

    ★★ `B115` 四条硬要求（本函数是它们唯一的落点）：

    | # | 要求 | 本函数怎么满足 |
    |---|---|---|
    | ① | **投递即入队**，❌ 不得静默拒绝 | 入队失败 ⇒ ★ **把 Job 置 `failed` 并抛异常**，❌ 绝不假装成功 |
    | ② | 排队状态可见 | `queue_position` 由 `queue.queue_size()` 另算（见 jobs 接口） |
    | ③ | 并发粒度合理 | ⚠ 不做「每用户全局 1」—— 限制交给队列深度与限流（J5） |
    | ④ | 幂等键语义正确 | 相同 `dedup_key` ⇒ ★ **合并到已有 Job 并返回同一个 id**（不是失败） |

    ⚠ **为什么"入队失败"必须显式失败**：Redis 挂了但 Job 记录留在 `queued`，
      用户会看到"排队中"却**永远不会被处理** —— 这是最糟的一种体验（静默黑洞）。
    """
    payload = payload or {}

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

    # ---------------------------------------------------------------- 创建 + 入队
    with transaction.atomic():
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
