"""★★ **点赞数的 Redis 缓存**（`F3` 补充 · 2026-10-20）

## ★ 所有者原话（逐字）

> 「这个系统是由redis的，把点赞数这些装进redis缓存里就行了，常看的文章要经常
>   发送点赞数据的还是同一个，用redis就不用每次都计数了。」

## ★★ 设计（三层）

```
读：Redis → miss 或故障 ⇒ COUNT 数据库 ⇒ 回填 Redis
写：DB 事务（真相）⇒ INCR / DECR **已存在**的缓存 key
                      （key 不存在 ⇒ 什么都不做，下次读回源）
```

## ⚠★ 三条纪律

1. **数据库是真相**，Redis 只是缓存 ⇒ 丢了、错了都能自愈 ✅
2. **写路径只能 INCR 已存在的 key** —— `INCR` 对不存在的 key 会从 0 开始建，
   * 而数据库里可能已经有 5 个赞 ⇒ 缓存变 1 就是**永久错** ⚠
3. **Redis 故障必须降级**，绝不能把点赞页拖死 —— 所有调用都包了 try/except，
   出错就当没有缓存 ✅
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

#: 章赞：`astrolabe:like:note:<note_id>` → int
NOTE_KEY = "astrolabe:like:note:{id}"
#: 评论赞：`astrolabe:like:comment:<comment_id>` → int
COMMENT_KEY = "astrolabe:like:comment:{id}"
#: ★ 缓存 1 天；到期后下次读会重新 COUNT 一次（* 纠错机会）⚠
#:   ⚠ 从 7 天降到 1 天：* 这类「谁读谁留一个键」的缓存会随阅读量线性增长，
#:     * 短 TTL 才能把键数量压住（* 2026-10-21 审查结论）⚠
TTL_SECONDS = 1 * 86400
#: ★ Redis 必须**毫秒级失败**（* 不能让它拖住请求）⚠
SOCKET_TIMEOUT = 0.3

_client = None


def _redis():
    """懒加载的 Redis 客户端（* 连不上就返回 None，调用方降级）⚠"""
    global _client
    if _client is None:
        try:
            import redis

            _client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=SOCKET_TIMEOUT,
                socket_connect_timeout=SOCKET_TIMEOUT,
            )
        except Exception:  # pragma: no cover - 配置缺失/驱动异常
            logger.warning("like_cache: 无法初始化 Redis，全部降级为直查数据库")
            return None
    return _client


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------

def note_count(note_id: int, fallback) -> int:
    """读一篇笔记的章赞数。

    Args:
        note_id: 笔记 id
        fallback: 缓存 miss 时用的回调（* 返回数据库里的真实数）✅
    """
    client = _redis()
    key = NOTE_KEY.format(id=note_id)
    if client is not None:
        try:
            v = client.get(key)
            if v is not None:
                return int(v)
        except Exception:
            logger.debug("like_cache: 读 %s 失败，降级", key, exc_info=True)

    n = int(fallback())
    if client is not None:
        try:
            client.set(key, n, ex=TTL_SECONDS)
        except Exception:
            logger.debug("like_cache: 回填 %s 失败", key, exc_info=True)
    return n


def comment_count(comment_id: int, fallback) -> int:
    """读一条评论的赞数（同 `note_count` 的口径）。"""
    client = _redis()
    key = COMMENT_KEY.format(id=comment_id)
    if client is not None:
        try:
            v = client.get(key)
            if v is not None:
                return int(v)
        except Exception:
            logger.debug("like_cache: 读 %s 失败，降级", key, exc_info=True)

    n = int(fallback())
    if client is not None:
        try:
            client.set(key, n, ex=TTL_SECONDS)
        except Exception:
            logger.debug("like_cache: 回填 %s 失败", key, exc_info=True)
    return n


# ---------------------------------------------------------------------------
# 批量读（列表页用，⛔ 避免逐条 MGET）
# ---------------------------------------------------------------------------

def _batch(keys_template: str, ids: list[int], db_counts) -> dict[int, int]:
    """通用批量：MGET 已有的，miss 的调 `db_counts(missing_ids)` 回源 + 回填。"""
    if not ids:
        return {}
    client = _redis()
    keys = [keys_template.format(id=i) for i in ids]
    out: dict[int, int] = {}
    missing: list[int] = []

    if client is not None:
        try:
            vals = client.mget(keys)
        except Exception:
            vals = [None] * len(keys)
        for i, v in zip(ids, vals):
            if v is None:
                missing.append(i)
            else:
                out[i] = int(v)
    else:
        missing = list(ids)

    if missing:
        fresh = {int(k): int(v) for k, v in db_counts(missing).items()}
        for i in missing:
            out[i] = fresh.get(i, 0)
        if client is not None:
            try:
                pipe = client.pipeline()
                for i in missing:
                    pipe.set(keys_template.format(id=i), out[i], ex=TTL_SECONDS)
                pipe.execute()
            except Exception:
                logger.debug("like_cache: 批量回填失败", exc_info=True)
    return out


def note_counts(ids: list[int], db_counts) -> dict[int, int]:
    """批量读章赞数。`db_counts(missing)` 返回 `{note_id: count}`。"""
    return _batch(NOTE_KEY, ids, db_counts)


def comment_counts(ids: list[int], db_counts) -> dict[int, int]:
    """批量读评论赞数。`db_counts(missing)` 返回 `{comment_id: count}`。"""
    return _batch(COMMENT_KEY, ids, db_counts)


# ---------------------------------------------------------------------------
# 写（只调已存在的 key）
# ---------------------------------------------------------------------------

def _bump(key: str, delta: int) -> None:
    """★ 只调整**已存在**的缓存 key（* 不存在就跳过，下次读回源）⚠"""
    client = _redis()
    if client is None:
        return
    try:
        if not client.exists(key):
            return
        v = client.incrby(key, delta)
        # ★ 防负（* 理论上不会发生，但缓存宁可保守）⚠
        if int(v) < 0:
            client.set(key, 0, ex=TTL_SECONDS)
    except Exception:
        logger.debug("like_cache: 更新 %s 失败（忽略）", key, exc_info=True)


def bump_note(note_id: int, delta: int) -> None:
    """章赞 +1 / −1 后同步缓存。"""
    _bump(NOTE_KEY.format(id=note_id), delta)


def bump_comment(comment_id: int, delta: int) -> None:
    """评论赞 +1 / −1 后同步缓存。"""
    _bump(COMMENT_KEY.format(id=comment_id), delta)
