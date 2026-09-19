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
    """阻塞领取一个作业 id（优先级最高者）；超时返回 None。"""
    got = _client().bzpopmin(QUEUE_KEY, timeout=timeout)  # Redis 6.2+ 支持 zset 阻塞弹出
    if not got:
        return None
    _key, member, _score = got
    return int(member)


def remove(job_id: int) -> None:
    """把作业从队列移除（取消作业时用）。"""
    _client().zrem(QUEUE_KEY, str(job_id))


def queue_size() -> int:
    """队列长度 —— 供 job 接口算 `queue_position`（J5：排队可见）。"""
    return int(_client().zcard(QUEUE_KEY))
