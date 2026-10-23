"""★★ **索引对账**（`B238` · 2026-10-23）⚠

## ★★★ 所有者原话（逐字）

> 「先做A和B吧。A的对账时间选在深夜，没几个人用就行，这时系统卡点，不影响。」

## ★ 为什么需要它

```
PostgreSQL 是真相，Meilisearch 是副本
  ⇒ 副本迟早会漂移（消息丢了 / 消费者崩了 / 有人直接改库）
  ⇒ 而 Meili **没有 TTL**，漂移不会自愈 ⚠
  ⇒ 唯一能发现它的手段：**定期把两边的 id 集合比一遍** ✅
```

## ★★ 两种漂移

| 类型 | 现象 |
|---|---|
| **缺失**（库里有、索引没有） | 新笔记搜不到 |
| **残留**（索引有、库里没有/不该有） | 点进去 404，或改过的标题还是旧的 |

## ★ 什么时候跑

* 深夜（默认 03:00–05:00）—— * 所有者：这时系统卡点不影响 ✅
* 每天最多一次（日期记 Redis，* 重启不会重复跑）⚠
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger("astrolabe.search.reconcile")

#: 对账窗口的小时（* 深夜，默认 3 点开始，到 5 点截止）⚠
RECONCILE_HOUR = int(os.environ.get("SEARCH_RECONCILE_HOUR", "3"))
RECONCILE_END_HOUR = int(os.environ.get("SEARCH_RECONCILE_END_HOUR", "5"))

#: 记录"今天已经对过账"（* 存 Redis，* 值 = 本地日期）⚠
DAY_KEY = "astrolabe:index:reconcile_day"
#: 心跳（* 消费者每 60 秒写一次，* 供 healthcheck 判断假死）⚠
HEARTBEAT_KEY = "astrolabe:index:heartbeat"


def _redis():
    from search import terms  # 复用它的连接单例

    return terms._redis()


def searchable_ids() -> set:
    """★ 数据库里**应该**在索引中的笔记 id（* 与 documents.is_searchable 一致）⚠"""
    from django.db.models import Q

    from core.models import Note, Project

    qs = (
        Note.objects.filter(
            deleted_at__isnull=True,
            state=Note.STATE_ACTIVE,
            is_public=True,
        )
        .filter(
            Q(project__isnull=True)
            | (Q(project__is_public=True) & Q(project__state=Project.STATE_ACTIVE))
        )
        .values_list("pk", flat=True)
    )
    return set(qs)


def _why(note_id: int) -> str:
    """★★ **这条为什么不该在索引里**（* 2026-10-23 补：可见性要能说清原因）⚠

    > 「索引对账顺便把项目和笔记的公开性，是否隐藏也检查了。私有的，被隐藏的项目或
    >   笔记要把其索引从 meilisearch 里删除。」

    ```
    笔记已删除 / 已软删 / 已转私有 / 被管理员隐藏
    所属项目已转私有 / 被管理员隐藏
    ```
    """
    from core.models import Note

    note = (
        Note.objects.filter(pk=note_id)
        .select_related("project")
        .only("pk", "deleted_at", "is_public", "state", "project__is_public", "project__state")
        .first()
    )
    if note is None:
        return "笔记已删除"
    if note.deleted_at is not None:
        return "笔记已软删"
    if not note.is_public:
        return "笔记已转私有"
    if note.state != Note.STATE_ACTIVE:
        return "笔记被管理员隐藏"

    project = note.project
    if project is not None:
        if not project.is_public:
            return "所属项目已转私有"
        if project.state != "active":
            return "所属项目被管理员隐藏"
    return "其他（可见性判断不一致）"


def reconcile(fix: bool = True) -> dict:
    """★★ 对一次账：比较两边的 id 集合，* 可选直接修 ✅

    ## ★★ 检查的内容（不只是"有没有"）

    ```
    ① 该不该在索引里：笔记未删 + 公开 + 生效中 + 所属项目公开且生效中
    ② 索引里多出来的：逐条给出**原因**（私有 / 隐藏 / 已删 / 项目私有…）
    ```

    Returns:
        `{pg, index, missing, stale, fixed, reasons, summary}`⚠
    """
    from collections import Counter

    from core.models import Note
    from search import client

    pg = searchable_ids()
    docs = client.list_documents(client.NOTES_INDEX, "id,updated_at")
    index = {d["id"] for d in docs if "id" in d}
    doc_ts = {d["id"]: d.get("updated_at") for d in docs if "id" in d}

    missing = sorted(pg - index)
    stale = sorted(index - pg)

    # ★★ 内容过期：* id 在两边都有，但 `updated_at` 对不上
    #   （* 消息丢了 / 消费者放弃重试 ⇒ 索引里是旧内容，* id 比对发现不了）⚠
    pg_ts = {
        nid: int(ts.timestamp() * 1000)
        for nid, ts in Note.objects.filter(pk__in=(pg & index)).values_list("pk", "updated_at")
    }
    outdated = sorted(
        nid for nid, ts in doc_ts.items() if nid in pg_ts and ts != pg_ts[nid]
    )

    # ★ 逐条说明"为什么该删"（* 私有 / 隐藏 / 项目私有 / 已删）⚠
    reasons = {nid: _why(nid) for nid in stale}
    summary = dict(Counter(reasons.values()))

    fixed = 0
    if fix and (missing or stale or outdated):
        from search import sync

        # ★ 缺的：* 重新投递（走正常索引链路，* 幂等）⚠
        for note_id in missing:
            sync.enqueue_note(note_id)
        # ★ 多的：* 直接删文档（* 库里都不该有了，* 不必等队列）⚠
        for note_id in stale:
            try:
                client.delete_document(client.NOTES_INDEX, note_id)
            except Exception:
                logger.warning("对账删除失败 note=%s", note_id, exc_info=True)
        for note_id in outdated:
            sync.enqueue_note(note_id)
        fixed = len(missing) + len(stale) + len(outdated)

    return {
        "pg": len(pg),
        "index": len(index),
        "missing": missing,
        "stale": stale,
        "outdated": outdated,
        "fixed": fixed,
        "reasons": reasons,
        "summary": summary,
    }


def due() -> bool:
    """★ 现在是否该对账（* 深夜窗口 + 今天还没跑过）⚠"""
    from django.utils import timezone

    now = timezone.localtime()
    if not (RECONCILE_HOUR <= now.hour < RECONCILE_END_HOUR):
        return False
    try:
        last = _redis().get(DAY_KEY)
    except Exception:
        return False
    return last != now.strftime("%Y-%m-%d")


def mark() -> None:
    """★ 记下"今天已经对过账"（* TTL 两天，* 跨天自动失效）⚠"""
    from django.utils import timezone

    try:
        _redis().set(DAY_KEY, timezone.localtime().strftime("%Y-%m-%d"), ex=172800)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 心跳（* 给 healthcheck 用）⚠
# ---------------------------------------------------------------------------

def beat() -> None:
    """★ 消费者每轮写一次（* 证明"我还活着并且在跑"）⚠"""
    try:
        _redis().set(HEARTBEAT_KEY, int(time.time()))
    except Exception:
        pass


def heartbeat_age() -> float:
    """★ 距离上次心跳过了多少秒（* 没有记录 ⇒ 无穷大）⚠"""
    try:
        raw = _redis().get(HEARTBEAT_KEY)
    except Exception:
        return float("inf")
    if not raw:
        return float("inf")
    try:
        return max(0.0, time.time() - float(raw))
    except (TypeError, ValueError):
        return float("inf")
