"""★★ **热搜词**（`B238` / `D109` · 2026-10-22）⚠

## ★★★ 所有者原话（逐字）

> 「删掉标题联想的 20 分钟缓存。我说让你删掉这个去postgresql里查表的过程，
>   我一系列操作都是在减少对postgresql的查询频率，减小查库压力，就靠热词做联想。
>   还有，在postgresql里建一个热词表，用来存储redis里的热词，方便断电后，
>   redis恢复。」

## ★★ 数据流

```
用户搜索 ──ZINCRBY──→ Redis ZSET（唯一在线读写的地方）
                          │
                          │  每 5 分钟（后台任务）
                          ▼
                     SearchTerm 表（持久化副本）
                          │
                          │  Redis 空了（重启/丢失）
                          ▼
                     回灌 Redis（一次）
```

⚠★ **联想请求永远不查 PG**（除了 Redis 空时的这一次回灌）✅
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("astrolabe.search.terms")

#: 热词集合（* ZSET：member=词，score=被搜次数）⚠
TERMS_KEY = "astrolabe:search:terms"
#: 回灌的互斥锁（* 防多个请求同时往 Redis 灌）⚠
LOAD_LOCK = "astrolabe:search:terms:load"
#: 回灌后的静默标记（* 别让"新装没有热词"时每个请求都查一次库）⚠
LOAD_MARK = "astrolabe:search:terms:loaded"

#: 最多保留多少个热词（* 超出按分数淘汰，* 防止 ZSET 无限长）⚠
TERMS_MAX = 2000
#: 回灌标记多久失效（秒）
LOAD_MARK_TTL = 600


def _redis():
    import redis
    from django.conf import settings

    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


# ---------------------------------------------------------------------------
# 写：记一次搜索
# ---------------------------------------------------------------------------

def record(kw: str) -> None:
    """★ 记一次搜索词（* 失败只记日志，⛔ 不能影响搜索）⚠"""
    if len(kw) < 2:
        return
    try:
        r = _redis()
        r.zincrby(TERMS_KEY, 1, kw)
        n = r.zcard(TERMS_KEY)
        if n > TERMS_MAX:
            r.zremrangebyrank(TERMS_KEY, 0, n - TERMS_MAX - 1)
    except Exception:
        logger.debug("热搜词记录失败（忽略）", exc_info=True)


# ---------------------------------------------------------------------------
# 读：联想
# ---------------------------------------------------------------------------

def matches(kw: str, limit: int = 8) -> list[str]:
    """★ 从热词里挑**包含** kw 的（* 全量取回内存筛，* ZSET 排序键是分数、做不了子串范围查）⚠"""
    try:
        pairs = _redis().zrevrange(TERMS_KEY, 0, -1, withscores=True)
    except Exception:
        return []

    hits = [(m, s) for m, s in pairs if kw in m and m != kw]
    # ★ 前缀优先 → 热度高的优先 → 短的优先 ⚠
    hits.sort(key=lambda ms: (not ms[0].startswith(kw), -ms[1], len(ms[0])))
    return [m for m, _ in hits[:limit]]


# ---------------------------------------------------------------------------
# 持久化：Redis ⇄ PostgreSQL
# ---------------------------------------------------------------------------

def flush() -> int:
    """★★ **把 Redis 的热词合并进 PG**（* 取最大值，* 幂等，* 可反复跑）⚠"""
    from core.models import SearchTerm

    try:
        pairs = _redis().zrange(TERMS_KEY, 0, -1, withscores=True)
    except Exception:
        logger.warning("热词落库：读不到 Redis，跳过", exc_info=True)
        return 0
    if not pairs:
        return 0

    remote = {term: int(score) for term, score in pairs}
    existing = {t.term: t for t in SearchTerm.objects.filter(term__in=remote.keys())}

    to_create = []
    to_update = []
    for term, count in remote.items():
        row = existing.get(term)
        if row is None:
            to_create.append(SearchTerm(term=term, count=count))
        elif count > row.count:
            row.count = count
            to_update.append(row)

    if to_create:
        SearchTerm.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)
    if to_update:
        SearchTerm.objects.bulk_update(to_update, ["count"], batch_size=500)

    return len(to_create) + len(to_update)


def ensure_loaded() -> None:
    """★★ **Redis 空了 ⇒ 从 PG 回灌一次**（* 断电 / 重启后的恢复）⚠

    ```
    · ZSET 非空        ⇒ 什么都不做（* 常态）✅
    · 刚回灌过（标记在）⇒ 跳过（* 防"新装没热词"时每个请求都查库）⚠
    · 否则             ⇒ 查一次 PG，ZADD 回 Redis，打标记 ✅
    ```
    """
    try:
        r = _redis()
        if r.zcard(TERMS_KEY) > 0:
            return
        if r.exists(LOAD_MARK):
            return
        if not r.set(LOAD_LOCK, 1, nx=True, ex=30):
            return
        try:
            from core.models import SearchTerm

            rows = list(
                SearchTerm.objects.order_by("-count").values_list("term", "count")[:TERMS_MAX]
            )
            if rows:
                r.zadd(TERMS_KEY, {term: count for term, count in rows})
                logger.info("热词已从数据库回灌 %s 条", len(rows))
        finally:
            r.delete(LOAD_LOCK)
            r.set(LOAD_MARK, 1, ex=LOAD_MARK_TTL)
    except Exception:
        logger.debug("热词回灌失败（忽略）", exc_info=True)


def stats() -> dict:
    """★ 给运维命令用：Redis / PG 各有多少条 ⚠"""
    from core.models import SearchTerm

    try:
        in_redis = _redis().zcard(TERMS_KEY)
    except Exception:
        in_redis = -1
    return {"redis": in_redis, "db": SearchTerm.objects.count()}
