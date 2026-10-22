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

#: ★★★ **每小时的衰减底数**（* 所有者 2026-10-22：「代表每一个小时衰减一次」
#:   「不要用 0.8 这个底数，这样的指数衰减太陡峭了，要换一个平和一点的」）⚠
#:
#:   ```
#:   半天倍率 = r ^ 12
#:     r = 0.99  ⇒ 半天 0.886 · 半衰期 ~3 天   （偏快）
#:     r = 0.995 ⇒ 半天 0.942 · 半衰期 ~6 天   ← 默认
#:     r = 0.998 ⇒ 半天 0.976 · 半衰期 ~14 天  （偏慢）
#:   ⚠ 注意：* `0.8 ^ 12 = 0.069` ⇒ 半天掉 93%，* 那是"每天全部重来" ⚠
#:   ```
DECAY_BASE = float(__import__("os").environ.get("SEARCH_TERM_DECAY_BASE", "0.995"))

#: ★ 分数衰减到低于这个值 ⇒ 直接删行（* 不让表无限长）⚠
MIN_COUNT = 1

#: ★★ **回灌周期**（秒）—— 半天 = 43200 ⚠
#:   * 所有者：「每隔半天，定时回灌 postgresql，并取分数最高的前 2000 条数据载入 redis 缓存」
FLUSH_INTERVAL = int(__import__("os").environ.get("SEARCH_TERM_FLUSH_SECONDS", "43200"))

#: 上次回灌的时间戳（* 存 Redis，* 进程重启也不会丢掉周期）⚠
LAST_FLUSH_KEY = "astrolabe:search:terms:last_flush"


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

def flush_and_decay(decay: bool = True) -> dict:
    """★★★ **半天一次的维护**（* 所有者 2026-10-22 定）⚠

    > 「热词的分数要有定期衰减，不能只增不减。这个 redis 表里的数据半天回填一次
    >   postgresql 数据库也没关系，就是要按条目修改，有这个热词的就修改分数，
    >   没有的，就加一个条目。……postgresql 里的热词条目的分数也要定时衰减。
    >   每隔半天，定时回灌 postgresql，并取分数最高的前 2000 条数据载入 redis 缓存。」
    > 「**postgresql 里存的热词分数在 redis 回灌的时候，也要做同步衰减后，再逐条赋值，
    >   最后，再选出前 2000 条回灌 redis。**」

    ## ★★ 五步（顺序即所有者口述的顺序）

    ```
    ① 算倍率：DECAY_BASE ^ 实际经过小时数（* 首次部署 ⇒ 1.0 不衰减）⚠
    ② 衰减 PG：表里**已有**的分数先乘倍率
    ③ 逐条赋值：Redis 每个词 × 同一倍率 ⇒ 有则更新、无则插入
    ④ 清理：count < 1 的行删掉
    ⑤ 回灌：PG 取 Top 2000 ⇒ 重建 Redis ZSET
    ```

    ⚠★ 两侧乘**同一个倍率**（"同步衰减"）⇒ 谁的数都不比谁新，* 不会一边衰减一边不衰减 ⚠
    """
    from django.db.models import F
    from django.utils import timezone

    from core.models import SearchTerm

    result = {"merged": 0, "decayed": 0, "pruned": 0, "loaded": 0, "factor": 1.0}

    # ---- ① 倍率 ----
    hours = hours_since_flush()
    factor = (DECAY_BASE ** hours) if (decay and hours > 0) else 1.0
    result["factor"] = round(factor, 4)
    now = timezone.now()

    # ---- ② 先衰减 PG 里已存的分数 ----
    if factor < 1.0:
        SearchTerm.objects.update(count=F("count") * factor, updated_at=now)

    # ---- ③ 逐条赋值（Redis 的分数也乘同一倍率）----
    try:
        pairs = _redis().zrange(TERMS_KEY, 0, -1, withscores=True)
    except Exception:
        logger.warning("热词落库：读不到 Redis，跳过", exc_info=True)
        return result

    if pairs:
        remote = {term: round(float(score) * factor, 3) for term, score in pairs}
        existing = {t.term: t for t in SearchTerm.objects.filter(term__in=remote.keys())}

        to_create = []
        to_update = []
        for term, count in remote.items():
            row = existing.get(term)
            if row is None:
                to_create.append(SearchTerm(term=term, count=count))
            elif count > row.count:
                # ★ 取较大值：* 防 Redis 丢过数据时把 PG 的计数改小（安全网）⚠
                row.count = count
                row.updated_at = now
                to_update.append(row)

        if to_create:
            SearchTerm.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)
        if to_update:
            SearchTerm.objects.bulk_update(to_update, ["count", "updated_at"], batch_size=500)
        result["merged"] = len(to_create) + len(to_update)

        # ---- ④ 清理低分 ----
        pruned, _ = SearchTerm.objects.filter(count__lt=MIN_COUNT).delete()
        result["pruned"] = pruned

    result["decayed"] = SearchTerm.objects.count()

    # ---- ⑤ Top 2000 回灌（* 用衰减后的分数重建）----
    top = list(
        SearchTerm.objects.order_by("-count").values_list("term", "count")[:TERMS_MAX]
    )
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.delete(TERMS_KEY)
        if top:
            pipe.zadd(TERMS_KEY, {term: round(count, 3) for term, count in top})
        pipe.set(LAST_FLUSH_KEY, int(time.time()))
        pipe.execute()
        result["loaded"] = len(top)
    except Exception:
        logger.warning("热词回灌 Redis 失败", exc_info=True)

    return result


def hours_since_flush() -> float:
    """★ 距上次回灌过了多少**小时**（* 没有记录 ⇒ 0，* 首次部署不衰减）⚠"""
    try:
        raw = _redis().get(LAST_FLUSH_KEY)
    except Exception:
        return 0.0
    if not raw:
        return 0.0
    try:
        return max(0.0, (time.time() - float(raw)) / 3600.0)
    except (TypeError, ValueError):
        return 0.0


def due() -> bool:
    """★ 距离上次回灌是否已满 `FLUSH_INTERVAL`（* 时间戳存 Redis，* 重启不重置）⚠"""
    try:
        raw = _redis().get(LAST_FLUSH_KEY)
    except Exception:
        return False
    if not raw:
        return True
    try:
        return time.time() - float(raw) >= FLUSH_INTERVAL
    except (TypeError, ValueError):
        return True


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
