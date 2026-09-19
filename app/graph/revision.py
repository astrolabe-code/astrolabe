"""Astrolabe · 图版本号（邻域缓存的命名空间代际）

★ 依据 `GRAPH-STORAGE.md` G5：**图不可变 + 维护者修补** ⇒ 缓存长期有效、极少失效。

★★ 核心思想：**「整片命名空间失效」不靠删 key，靠换命名空间。**

    astrolabe:neigh:{project_ref}:r{rev}:{vid}:d{depth}:{dir}:{etags}

    ⚠ 图一变，只把 `rev + 1` ⇒ ★ 旧代际的 key **立刻不可达**（O(1)），
      由 TTL 自然消亡。❌ **绝不** `SCAN` 全库删 key（会阻塞 Redis 主线程）。

★ 权威方 = **数据库**（`GraphRevision` 表），❌ 不是 Redis：
  · `bump()` 与 `write_graph()` **在同一个事务内** ⇒ 不存在"图新了、rev 还旧"的窗口
  · Redis 重启丢数据 ⇒ **rev 不会回退** ⇒ 不会把旧缓存当成新的

⚠ 分层（`ARCHITECTURE.md` A3）：本模块只依赖 ORM —— ★ **不 import Redis**，
  这样 `② 作业层` 在写图后可以直接调用它来失效缓存。
"""

from __future__ import annotations

from django.db.models import F
from django.utils import timezone

from graph.models import GraphRevision


def current(project_ref: str) -> int:
    """读当前图版本号（★ 项目首次写入前为 `0`）。

    ★ 一次**主键点查**（亚毫秒）—— 这点成本换取「缓存绝不串代际」是值得的。
    """
    rev = (
        GraphRevision.objects.filter(project_ref=project_ref)
        .values_list("rev", flat=True)
        .first()
    )
    return int(rev or 0)


def bump(project_ref: str) -> int:
    """图发生变化 ⇒ 版本号 +1（★ **必须与图写入在同一个事务内调用**）。

    ⚠ **什么时候必须调用**：

    | 场景 | 必须 bump？ |
    |---|---|
    | 解析作业写图（`write_graph`） | ✅ 是 |
    | ★ **维护者手工修补**（新增 / 修改 / 删边，G1） | ✅ **是** —— ⚠ 最容易漏的一处 |
    | 只改 UGC（解释 / 笔记） | ❌ 否 —— 那不动图 |

    ⚠ 用了 `F("rev") + 1` ⇒ **数据库层原子自增**，并发调用不会丢更新
      （最坏情况是号跳过几个 —— 无害，只要"变了就 +1"成立即可）。
    """
    obj, created = GraphRevision.objects.get_or_create(
        project_ref=project_ref, defaults={"rev": 1}
    )
    if not created:
        GraphRevision.objects.filter(project_ref=project_ref).update(
            rev=F("rev") + 1, updated_at=timezone.now()
        )
        obj.refresh_from_db(fields=["rev"])
    return int(obj.rev)
