"""★★ **搜索结果的 Redis 缓存**（2026-10-21）

## ★ 所有者原话

> 「搜索结果用redis缓存一下，频繁搜索的就那么几个，下次直接返回就行。
>   不过注意更新时间限制。」

## ★★ 设计

```
key   = search:<ns>:<uid>:<sha1(关键词)>      # ns = notes / projects
value = JSON（序列化好的结果列表）
TTL   = SEARCH_CACHE_TTL（默认 300 秒）
```

## ⚠★ 四条纪律

1. **key 里带 uid** —— 搜索结果依赖「谁能看什么」（私有笔记 / 项目成员），
   * ⛔ 不能共用一份 ✅
2. **TTL 兜底**（默认 5 分钟）⇒ 即使漏了主动失效，* 最多陈旧 5 分钟 ✅
3. **写入即失效**：* 笔记 / 项目任何写操作都调 `invalidate(ns)`
   （* 用 registry 集合记录本命名空间下所有 key，* 一次全清）⚠
4. **Redis 故障必须降级** ⇒ 所有调用 try/except，* 出错就当没有缓存 ✅
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

#: 缓存多久（秒）—— ★ 所有者要求「注意更新时间限制」
TTL_SECONDS = int(os.environ.get("SEARCH_CACHE_TTL", "300"))
#: registry 集合的 TTL 倍数（* 必须 ≥ 1，* 否则集合比数据先死，* 失效会漏键）⚠
REGISTRY_TTL_FACTOR = 2

#: ★ 统一走 `astrolabe:` 命名空间（* 与 jobs / basegraph / neigh / hot 一致）⚠
NS_NOTES = "astrolabe:search:notes"
NS_PROJECTS = "astrolabe:search:projects"

_client = None


def _redis():
    global _client
    if _client is None:
        try:
            import redis

            _client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=0.3,
                socket_connect_timeout=0.3,
            )
        except Exception:
            logger.warning("search_cache: 无法初始化 Redis，搜索缓存降级为直查")
            return None
    return _client


def _key(ns: str, uid: int, kw: str) -> str:
    digest = hashlib.sha1(kw.encode("utf-8")).hexdigest()[:20]
    return f"{ns}:{uid}:{digest}"


def get(ns: str, uid: int, kw: str):
    """读缓存；miss 或故障 ⇒ 返回 None（调用方回源）。"""
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(_key(ns, uid, kw))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.debug("search_cache: 读失败（忽略）", exc_info=True)
        return None


def put(ns: str, uid: int, kw: str, payload) -> None:
    """写缓存（带 TTL），并把 key 记进 registry 便于整体失效。"""
    client = _redis()
    if client is None:
        return
    key = _key(ns, uid, kw)
    try:
        pipe = client.pipeline()
        pipe.set(key, json.dumps(payload, ensure_ascii=False), ex=TTL_SECONDS)
        # ★ registry：* 失效时按它清；* 给个略长的 TTL 防无限增长 ⚠
        pipe.sadd(f"{ns}:__keys__", key)
        pipe.expire(f"{ns}:__keys__", TTL_SECONDS * REGISTRY_TTL_FACTOR)
        pipe.execute()
    except Exception:
        logger.debug("search_cache: 写失败（忽略）", exc_info=True)


def invalidate(ns: str) -> None:
    """清掉这个命名空间下的**所有**搜索结果（任何写入后调用）。"""
    client = _redis()
    if client is None:
        return
    registry = f"{ns}:__keys__"
    try:
        keys = list(client.smembers(registry))
        if keys:
            # ★ 先验活再删：* 已自然过期的键不必 DEL（* 省掉一批无效命令）⚠
            pipe = client.pipeline()
            for k in keys:
                pipe.exists(k)
            alive = [k for k, ok in zip(keys, pipe.execute()) if ok]
            if alive:
                client.delete(*alive)
        client.delete(registry)
    except Exception:
        logger.debug("search_cache: 失效失败（忽略）", exc_info=True)


def invalidate_all() -> None:
    """笔记 / 项目两路一起清（项目改名等场景用）。"""
    invalidate(NS_NOTES)
    invalidate(NS_PROJECTS)
