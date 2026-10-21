"""Astrolabe · ② 作业层：队列中介（Redis）

★ 依据 JOB-MODEL.md J9：
     ① Web（Django）  ── 写一条 Job 记录 + 推 Redis ──→ ★ 立刻返回 job_id
     ② 作业层（worker）←── 从队列领取 ──→ 执行 → 写回 Job 表

⚠ 分层纪律（ARCHITECTURE.md A3 红线 #2）：
   ★ 本模块**不直接给 ① Web 层用** —— ① 走 `jobs/dispatch.py`（那是**投递**入口）。
   ⚠ 精确口径见 `dispatch.py` 顶部：**「投递」允许，「执行」禁止**。

★ 队列用 Redis zset：score = -priority ⇒ ★ score 最小者先出（= 优先级最高）
"""

import redis
from django.conf import settings

QUEUE_KEY = "astrolabe:jobs"


def _client() -> "redis.Redis":
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def enqueue(job_id: int, priority: int = 0) -> None:
    """投递作业到队列。

    ★ `B115` 第 ① 条：**投递即入队** —— 本函数不返回失败，
      也不像旧实现那样「静默拒绝」。
    """
    _client().zadd(QUEUE_KEY, {str(job_id): -priority})


def dequeue(timeout: int = 5) -> int | None:
    """阻塞领取一个作业 id（优先级最高者）；超时返回 None。

    ⚠★ 2026-10-21：**领到的先验活**（* 修「僵尸任务占着队列」）⚠

    ```
    旧问题：worker 在「pop 之后、zrem 之前」崩掉
      ⇒ 这个 job id 永远留在 zset 里（* bzpopmin 已经把它弹出了，
         但进程死了没来得及 zrem ⇒ 下一个人捡到的就是它）
      ⇒ 之后每次 bzpopmin 都先捡到这条死任务，* 队列被堵死 ⚠
    ```
    ★ 修法：* 领到后回库确认这个作业**还存在且状态是排队中**；
      不成立 ⇒ `zrem` 掉这条残留，* 继续领下一条（* 一次最多赶 20 条，
      * 避免死循环）✅
    """
    from jobs.models import Job

    for _ in range(20):
        got = _client().bzpopmin(QUEUE_KEY, timeout=timeout)
        if not got:
            return None
        _key, member, _score = got
        try:
            job_id = int(member)
        except (TypeError, ValueError):
            continue

        # ★ 验活：* 行没了 / 不在排队中 ⇒ 这是残留，* 清掉继续领 ⚠
        if Job.objects.filter(pk=job_id, state=Job.STATE_QUEUED).exists():
            return job_id
        remove(job_id)
    return None


def remove(job_id: int) -> None:
    """把作业从队列移除（取消作业时用）。"""
    _client().zrem(QUEUE_KEY, str(job_id))


def queue_size() -> int:
    """队列长度 —— 供 job 接口算 `queue_position`（J5：排队可见）。"""
    return int(_client().zcard(QUEUE_KEY))
