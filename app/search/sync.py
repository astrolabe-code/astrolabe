"""★★ **写后同步**（`B238` 第 2 步）—— 笔记写库后，把变更投给索引 ⚠

## ★★★ 所有者原话（逐字）

> 「我决定不要检查正确性了，而是在笔记修改存进postgresql之后，发送一条消息给redis，
>   让他删除相应的键……」
> 「我选这个写后通知，只是为了适应es的工作模式，试试水。」

## ★★ 链路

```
Note.save() / delete / QuerySet.update()
      ↓  transaction.on_commit（⚠ 回滚了就不发）
search.sync.enqueue_note(note_id)
      ↓  SADD 去重 + LPUSH
Redis: astrolabe:index:queue
      ↓  由 `manage.py search_worker` 消费（独立容器）
fetch note → 该进索引？upsert : delete_document
```

## ⚠★ 三条纪律

1. **只在提交后投递**（`transaction.on_commit`）—— 否则事务回滚了，索引却改了 ⚠
2. **投递永远不抛异常**（* Redis 挂了不能把笔记保存搞崩）⇒ 记日志、返回 False ✅
3. **失败要重试**（* 最多 5 次，指数退避）—— ⛔ 不能靠 TTL（Meili 没有过期）⚠
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.models import Note
from search import client, documents

logger = logging.getLogger("astrolabe.search.sync")

#: 待处理队列（LIST，LPUSH / BRPOP）
QUEUE_KEY = "astrolabe:index:queue"
#: 待处理集合（SET，* 去重用 —— 同一个 id 排队期间只入队一次）⚠
PENDING_KEY = "astrolabe:index:pending"
#: 重试队列（ZSET，score = 下次可执行的时间戳）
RETRY_KEY = "astrolabe:index:retry"
#: 失败次数（HASH）
ATTEMPTS_KEY = "astrolabe:index:attempts"

#: 最多重试几次（* 之后放弃，* 靠全量 reindex 兜底）⚠
MAX_ATTEMPTS = 5


#: ★★ 复用连接（* 2026-10-23：原来每次新建 ⇒ 每条命令重新握手，实测 ~1.8ms）⚠
_conn = None


def _redis():
    global _conn
    if _conn is None:
        import redis
        from django.conf import settings

        _conn = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
        )
    return _conn


def enqueue_note(note_id: int) -> bool:
    """★ 把一个笔记 id 投进索引队列（* 幂等：排队期间重复投递只留一条）⚠"""
    if not client.enabled():
        return False
    try:
        r = _redis()
        if r.sadd(PENDING_KEY, str(note_id)):
            r.lpush(QUEUE_KEY, str(note_id))
        return True
    except Exception:
        # ⚠ 搜索索引坏了不能影响笔记保存；* 丢了靠 reindex 兜
        logger.warning("索引投递失败 note=%s", note_id, exc_info=True)
        return False


def enqueue_many(note_ids) -> None:
    for nid in note_ids:
        enqueue_note(nid)


def enqueue_project_notes(project_ref: str) -> int:
    """★★ **项目里有字段变了 ⇒ 该项目下所有笔记重新入索引**（`B238`）⚠

    ⚠★ 为什么不是只改文档里的那一个字段：
      · Meili 的文档是**整篇覆盖**的（`add_documents` 是 upsert）
      · ⇒ 只能「重新生成整篇文档」再写，* 不能局部更新 ✅
    """
    from core.models import Note

    if not client.enabled():
        return 0

    ids = list(
        Note.objects.filter(project__project_ref=project_ref).values_list("pk", flat=True)
    )
    enqueue_many(ids)
    return len(ids)


def _schedule_after_commit(note_id: int) -> None:
    transaction.on_commit(lambda: enqueue_note(note_id))


# ---------------------------------------------------------------------------
# 消费
# ---------------------------------------------------------------------------

def apply(note_id: int) -> None:
    """★ 把**当前数据库状态**同步到索引（* 永远以库为准，⛔ 不用消息里的快照）⚠"""
    note = (
        Note.objects.filter(pk=note_id)
        .select_related("project", "created_by")
        .first()
    )

    if note is None or not documents.is_searchable(note):
        # 删了 / 转私有 / 项目转私有 ⇒ 从索引里移除
        client.delete_document(client.NOTES_INDEX, note_id)
        return

    client.add_documents(client.NOTES_INDEX, [documents.build_document(note)])


def drain_once(timeout: int = 2) -> bool:
    """★ 处理一个待办（* 先看重试队列里有没有到期的）；返回是否处理了东西 ⚠"""
    r = _redis()

    # ① 到期的重试
    due = r.zrangebyscore(RETRY_KEY, 0, _now(), start=0, num=5)
    if due:
        for raw in due:
            r.zrem(RETRY_KEY, raw)
            _run(r, int(raw))
        return True

    # ② 新任务
    item = r.brpop(QUEUE_KEY, timeout=timeout)
    if not item:
        return False
    _run(r, int(item[1]))
    return True


def _run(r, note_id: int) -> None:
    try:
        apply(note_id)
    except Exception as exc:
        attempts = r.hincrby(ATTEMPTS_KEY, str(note_id), 1)
        if attempts >= MAX_ATTEMPTS:
            logger.error("索引同步放弃 note=%s：%s", note_id, exc)
            r.hdel(ATTEMPTS_KEY, str(note_id))
            r.srem(PENDING_KEY, str(note_id))
            return

        # 指数退避：2 / 4 / 8 / 16 秒
        delay = 2 ** attempts
        r.zadd(RETRY_KEY, {str(note_id): _now() + delay})
        logger.warning("索引同步失败 note=%s（第 %s 次，%ss 后重试）：%s",
                       note_id, attempts, delay, exc)
        return

    r.hdel(ATTEMPTS_KEY, str(note_id))
    r.srem(PENDING_KEY, str(note_id))


def _now() -> float:
    import time

    return time.time()


# ---------------------------------------------------------------------------
# 信号：删除（含 CASCADE —— 删用户 / 删项目会连带删笔记）
# ---------------------------------------------------------------------------

@receiver(post_delete, sender=Note)
def _on_note_deleted(sender, instance, **kwargs):
    """★ 行都没了 ⇒ 通知**删文档**（* `apply` 查不到会自动删）⚠"""
    transaction.on_commit(lambda: enqueue_note(instance.pk))
