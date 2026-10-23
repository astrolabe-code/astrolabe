"""★★ **Note → 搜索文档**（`B238`）—— 谁该进索引、字段怎么取 ⚠

## ★★★ 索引口径（与 PG 检索**完全一致**）

```
进索引：笔记公开 + 生效中 + 未删 + 所属项目公开且生效中
⛔ 不进：私有 / 隐藏 / 已删 / 私有项目里的笔记
```

⚠★ 为什么不「全量进索引 + 查询时过滤」：
  * 本平台搜索**只对公众开放**（所有者裁定：私有内容不进首页搜索）
  * 索引里就不该有私有内容 —— * 万一过滤条件写错，* 也不会泄露 ✅

## ★ 文档字段

| 字段 | 用途 |
|---|---|
| `id` | 主键（= `Note.pk`） |
| `title` / `body` | 可搜索 |
| `node_name` / `project_name` | 可搜索（* 用户常按函数名、项目名找） |
| `kind` / `project_ref` / `created_by_id` | 可过滤（* 将来搜索页的筛选） |
| `created_at` / `updated_at` | 可排序（* 毫秒时间戳） |
"""
from __future__ import annotations

from datetime import datetime

from core.models import Note, Project

#: 正文进索引的最长长度（* 够搜索即可，* ⛔ 不把整篇塞进索引）⚠
#:
#: ★★ 2026-10-22（所有者）：「既然不存全部正文，那4000字就没有必要呀？有几篇笔记能写
#:   4000字？能写1000字都很厉害了。把这个字数减小一点。」
#:
#: ⚠ 取 2000 的理由：
#:   · · 实测现有笔记最长 30 字；1000 已覆盖绝大多数场景
#:   · · 但**超长笔记按 1000 截断会搜不到后半段**，而多留 1000 字对短笔记**零成本**
#:     （* 只有超过上限的笔记才会被截，* 短笔记两者完全一样）✅
#:   · · 若将来发现索引偏大，这条改小 + 重新 reindex 即可 ⚠
BODY_INDEX_MAX = 2000


def is_searchable(note: Note) -> bool:
    """★ 判断一篇笔记**应不应该**出现在公共搜索里 ⚠"""
    if note.deleted_at is not None:
        return False
    if not note.is_public or note.state != Note.STATE_ACTIVE:
        return False

    project = note.project
    if project is not None:
        if not project.is_public or project.state != Project.STATE_ACTIVE:
            return False
    return True


def _ts(value) -> int:
    """★ Django datetime → 毫秒时间戳（* Meili 的排序字段用数字）⚠"""
    if not isinstance(value, datetime):
        return 0
    return int(value.timestamp() * 1000)


def _count_likes(note) -> int:
    """★ 赞数（* 优先走 Redis 缓存，* miss 才 COUNT）⚠"""
    from core import like_cache
    from core.models import NoteLike

    try:
        return int(
            like_cache.note_count(
                note.pk, lambda: NoteLike.objects.filter(note_id=note.pk).count()
            )
        )
    except Exception:
        return 0


def build_document(note: Note, like_count: int | None = None) -> dict:
    """★ 构造一份索引文档（* 调用方保证 `is_searchable(note)` 为真）⚠"""
    project = note.project
    return {
        "id": note.pk,
        "title": note.title or "",
        "body": (note.body or "")[:BODY_INDEX_MAX],
        "kind": note.kind or "",
        "project_ref": project.project_ref if project else "",
        "project_name": project.name if project else "",
        "node_name": getattr(note, "node_name", "") or "",
        # ★★ 存 **id** 而不是用户名（* 2026-10-23 所有者裁定）⚠
        #   · · 用户名可以改 ⇒ 存名字的快照会腐化（* 且没人会去重索引它）⚠
        #   · · 展示用的作者名一律从 PG 现取，* 索引里只留 id 供将来筛选 ✅
        "created_by_id": note.created_by_id or 0,
        # ⚠ 展示用的用户名（* 2026-10-23 所有者：搜索结果直接来自索引，不回库）
        #   · · 改名后会旧到下次重建 —— 「错了也没关系」✅
        "created_by": note.created_by.get_username() if note.created_by_id else "",
        "created_at": _ts(note.created_at),
        "updated_at": _ts(note.updated_at),
        # ★★ 两个计数进索引（* 2026-10-23 所有者：用户靠它判断值不值得点进去）⚠
        #   · · 慢几秒没关系；* 计数变更走 **PUT 部分更新**，碰不到正文 ✅
        "like_count": int(like_count) if like_count is not None else _count_likes(note),
        "comment_count": int(note.comment_count or 0),
    }


#: ★★★ **项目上会出现在笔记文档里的字段**（改这些 ⇒ 该项目下的笔记要重建索引）⚠
#:
#: | 字段 | 在笔记文档里是 | 怎么同步 |
#: |---|---|---|
#: | `name` | `project_name` | ★ **本集合负责**（* 改完要把该项目的笔记重新入队）⚠ |
#: | `is_public` / `state` | 决定笔记**是否该在索引里** | 级联改笔记（`Note.objects...update`）⇒ 已自动入队 ✅ |
#: | `desc` / `provider` / `repo_url` | ⛔ 不在笔记文档里 | 无需处理 |
#: | `project_ref` | `project_ref` | ★ 创建后不可变 ⚠ |
#:
#: ⚠ 将来往 `build_document` 里加项目字段，**必须同步加到这里**，否则改名类操作会留下旧快照。
PROJECT_FIELDS_IN_DOC = {"name"}


#: 索引设置（* `search_reindex` 与 `ensure_settings` 共用）⚠
INDEX_SETTINGS = {
    # ★ 越靠前权重越高：* 标题 > 正文 > 项目名 > 节点名 ⚠
    "searchableAttributes": ["title", "body", "project_name", "node_name"],
    "filterableAttributes": ["kind", "project_ref", "created_by_id"],
    "sortableAttributes": ["created_at", "updated_at"],
    "pagination": {"maxTotalHits": 1000},
}
