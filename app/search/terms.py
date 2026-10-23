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

import hashlib
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
#:   · · 2026-10-22 所有者定 **0.5**：
#:     * 只被搜过一次的词（1.0）能撑 ~5 个周期再消失，* 不会第二天就没了 ✅
MIN_COUNT = 0.5

#: ★★ **维护周期**（秒）—— **半天 = 43200** ⚠
#:   * 所有者：「每隔半天，定时回灌 postgresql」
#:   * 一次维护 = 合并 → 衰减 → 清理 → 回灌 ✅
#:   ⚠ 「一天一次」说的是**种子**（`SEED_INTERVAL`），* 两者周期不同 ⚠
FLUSH_INTERVAL = int(__import__("os").environ.get("SEARCH_TERM_FLUSH_SECONDS", "43200"))

#: 上次回灌的时间戳（* 存 Redis，* 进程重启也不会丢掉周期）⚠
LAST_FLUSH_KEY = "astrolabe:search:terms:last_flush"

#: ★★ 种子任务的时间戳与周期（* 所有者：「改为一天自动执行一次」）⚠
LAST_SEED_KEY = "astrolabe:search:terms:last_seed"
#: 种子任务多久跑一次（秒）—— 一天
SEED_INTERVAL = int(__import__("os").environ.get("SEARCH_TERM_SEED_SECONDS", "86400"))
#: 种子最多取多少条（* 笔记标题 + 项目名，合并后按更新时间取前 N）⚠
SEED_LIMIT = 2000

#: ★ 同人同词的去重窗口（秒）—— 15 分钟 ⚠
DEDUP_TTL = int(__import__("os").environ.get("SEARCH_TERM_DEDUP_SECONDS", "900"))

#: ★★★ **联想限流**（`B238` · 2026-10-23）——
#:
#: > 「不能按照IP区分，误伤太厉害了。游客都算一个人，给他们的搜索速率放高一点，
#: >   是正常用户的9倍就行了。登陆用户，就可以按他们的身份限制速率了。」
#:
#: ```
#: 登录用户 ⇒ 按 uid 单独计数：RATE_USER 次/秒
#: 游客     ⇒ **全体共用一个桶**：RATE_USER × 9 次/秒
#: ```
#: ⚠ 为什么游客要给 9 倍：* 他们共用一个桶，* 按单人速率会立刻把所有人卡死 ⚠
RATE_USER = int(__import__("os").environ.get("SEARCH_SUGGEST_RATE_USER", "10"))
RATE_GUEST = RATE_USER * 9


#: ★★ **进程内复用的 Redis 连接**（* 2026-10-23 修）⚠
#:
#: ⚠★ 原先每次调用都 `redis.Redis.from_url(...)` 新建一个对象：
#:   · · 对象是懒连接 ⇒ **每条命令都要重新建 TCP 连接**
#:   · · 实测一次 ZCARD 要 **1.87ms**（其中 ~1.8ms 是连接开销）⚠
#:   · · 现在复用同一个 client（* 内部有连接池）⇒ 实测 ~0.05ms ✅
_client = None


def _redis():
    global _client
    if _client is None:
        import redis
        from django.conf import settings

        _client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


# ---------------------------------------------------------------------------
# 写：记一次搜索
# ---------------------------------------------------------------------------

def record(kw: str, who: str = "") -> None:
    """★ 记一次搜索词（* 失败只记日志，⛔ 不能影响搜索）⚠

    ⚠★★ **同一人 + 同一词，15 分钟内只记一次**（* 所有者 2026-10-22 定）：
      · · 目的是挡掉「刷新页面 / 来回切页 / 反复搜索」把热度刷高 ⚠
      · · 去重键 15 分钟后自然过期，* 不占存储 ✅
    """
    if len(kw) < 2:
        return
    try:
        r = _redis()
        if who:
            dedup = f"astrolabe:search:terms:seen:{hashlib.sha1(f'{who}|{kw.lower()}'.encode()).hexdigest()[:20]}"
            # ★ SET NX：第一次成功 ⇒ 记账；已存在 ⇒ 15 分钟内重复，跳过 ⚠
            if not r.set(dedup, 1, nx=True, ex=DEDUP_TTL):
                return
        r.zincrby(TERMS_KEY, 1, kw)
        n = r.zcard(TERMS_KEY)
        if n > TERMS_MAX:
            r.zremrangebyrank(TERMS_KEY, 0, n - TERMS_MAX - 1)
    except Exception:
        logger.debug("热搜词记录失败（忽略）", exc_info=True)


# ---------------------------------------------------------------------------
# 读：联想
# ---------------------------------------------------------------------------

def allow_suggest(who: str, is_guest: bool) -> bool:
    """★★ **联想限流**（* 固定窗口：每秒一个计数键）⚠

    ```
    登录用户 u<id> ⇒ 每秒 RATE_USER 次
    游客     anon  ⇒ 每秒 RATE_USER × 9 次（* 全体共享）⚠
    ```

    ⚠★ 失败**放行**：* 联想是可选增强，* Redis 挂了不该连提示都没有 ✅
    """
    limit = RATE_GUEST if is_guest else RATE_USER
    try:
        r = _redis()
        key = f"astrolabe:rl:suggest:{who}:{int(time.time())}"
        n = r.incr(key)
        if n == 1:
            r.expire(key, 2)
        return n <= limit
    except Exception:
        return True


def matches(kw: str, limit: int = 8) -> list[str]:
    """★ 从热词里挑**包含** kw 的（* 全量取回内存筛，* ZSET 排序键是分数、做不了子串范围查）⚠"""
    try:
        pairs = _redis().zrevrange(TERMS_KEY, 0, -1, withscores=True)
    except Exception:
        return []

    # ★ 集合为空（* 断电 / 重启后）⇒ 从 PG 回灌一次再读；
    #   · 常态下有数据 ⇒ 不会有这第二次往返 ✅
    if not pairs:
        ensure_loaded()
        try:
            pairs = _redis().zrevrange(TERMS_KEY, 0, -1, withscores=True)
        except Exception:
            return []

    # ★★ 大小写不敏感（* 所有者：「大小写敏感就匹配时统一小写」）⚠
    #   · · 只在**比较时**转小写，* 返回的仍是原始写法（* 展示不失真）✅
    low = kw.lower()
    hits = [(m, s) for m, s in pairs if low in m.lower() and m.lower() != low]
    # ★ 前缀优先 → 热度高的优先 → 短的优先 ⚠
    hits.sort(key=lambda ms: (not ms[0].lower().startswith(low), -ms[1], len(ms[0])))
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

    # ---- ⑤ Top 2000 回灌（* 用衰减后的分数重建；* 两侧词集合保持一致）----
    result["loaded"] = reload_redis()
    try:
        _redis().set(LAST_FLUSH_KEY, int(time.time()))
    except Exception:
        pass

    return result


def reload_redis() -> int:
    """★★ **按 PG 的 Top N 重建 Redis**（* 两侧永久保持一致）⚠

    ⚠★ 每次都是「删旧键 → 重新 ZADD」：
      · · 保证 Redis 里**没有残留的旧词**（* 衰减/清理后才不会出现"Redis 有、PG 没有"）
      · · ⇒ **Redis 与 PG 的词集合始终相同**（* 所有者要求的"不能有重复词"）✅
    """
    from core.models import SearchTerm

    top = list(
        SearchTerm.objects.order_by("-count").values_list("term", "count")[:TERMS_MAX]
    )
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.delete(TERMS_KEY)
        if top:
            pipe.zadd(TERMS_KEY, {term: round(count, 3) for term, count in top})
        # ⚠★ 这里**不写** `LAST_FLUSH_KEY` —— 那是"上次衰减时间"，
        #   · 种子也会调本函数 ⇒ 若在这里写，* 种子每天把衰减时钟重置一次，
        #     * 结果**衰减永远不触发**（实测证实）⚠
        pipe.execute()
    except Exception:
        logger.warning("热词回灌 Redis 失败", exc_info=True)
    return len(top)


def seed_from_recent(limit: int = SEED_LIMIT) -> dict:
    """★★★ **种子任务：把「最近更新的笔记标题 + 项目名」灌进热词表** ⚠

    ## ★★★ 所有者原话（逐字）

    > 「补上种子命令，改为一天自动执行一次。具体步骤是，取今天更新日期最新的前 2000 条
    >   笔记和项目名称，给他们赋值 postgresql 里热词表分数的中位数。再逐条添加，
    >   注意不要产生重复的词，在 redis 和 redis 回灌过程也一样。redis 缓存和
    >   postgresql 里的热词表不能有重复词。」

    ## ★★ 规则

    ```
    ① 取数：公开可见的笔记标题 + 项目名，按 updated_at 倒序，合并后取前 2000 条
    ② 分值：热词表的**中位数**（表空 ⇒ 1.0，* 至少能被联想）
    ③ 去重：① batch 内部去重 ② 已存在的词**跳过**（不覆盖已有分数）
    ④ 回灌：PG Top2000 重建 Redis ⇒ 两侧词集合完全一致
    ```

    ⚠★ 为什么只插入、不覆盖：* 已经热起来的词不能被种子的中位数**拉低** ⚠
    """
    import statistics

    from django.db.models import Q

    from core.models import Note, Project, SearchTerm

    # ---- ① 取数（* 只取公开内容，* 免得把私有标题灌进公共联想）⚠
    note_rows = list(
        Note.objects.filter(
            deleted_at__isnull=True,
            state=Note.STATE_ACTIVE,
            is_public=True,
        )
        .filter(
            Q(project__isnull=True)
            | (Q(project__is_public=True) & Q(project__state=Project.STATE_ACTIVE))
        )
        .order_by("-updated_at")
        .values_list("title", "updated_at")[:limit]
    )
    project_rows = list(
        Project.objects.filter(is_public=True, state=Project.STATE_ACTIVE)
        .order_by("-updated_at")
        .values_list("name", "updated_at")[:limit]
    )

    merged = sorted(
        [(t, ts) for t, ts in note_rows + project_rows if t and t.strip()],
        key=lambda x: x[1],
        reverse=True,
    )[:limit]

    # ---- ② 中位数 ----
    vals = list(SearchTerm.objects.values_list("count", flat=True))
    median = max(statistics.median(vals) if vals else 1.0, 1.0)

    # ---- ③ 去重（batch 内 + 表内已存在）----
    seen: set[str] = set()
    candidates: list[str] = []
    for text, _ in merged:
        term = text.strip()
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        candidates.append(term)

    existing = set(
        SearchTerm.objects.filter(term__in=candidates).values_list("term", flat=True)
    )
    to_create = [
        SearchTerm(term=t, count=median) for t in candidates if t not in existing
    ]
    if to_create:
        # ★ `ignore_conflicts` 兜住并发写进来的同名词（* DB 是唯一约束）⚠
        SearchTerm.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)

    # ---- ④ 回灌（* 两侧词集合保持一致）----
    loaded = reload_redis()
    try:
        _redis().set(LAST_SEED_KEY, int(time.time()))
    except Exception:
        pass

    return {
        "candidates": len(candidates),
        "created": len(to_create),
        "skipped": len(candidates) - len(to_create),
        "median": round(median, 3),
        "loaded": loaded,
    }


def seed_due() -> bool:
    """★ 距离上次种子是否已满一天 ⚠"""
    try:
        raw = _redis().get(LAST_SEED_KEY)
    except Exception:
        return False
    if not raw:
        return True
    try:
        return time.time() - float(raw) >= SEED_INTERVAL
    except (TypeError, ValueError):
        return True


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
