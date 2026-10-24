"""★★ **用户资料与用户空间统计**（2026-10-24）⚠

## ★★★ 所有者原话（逐字）

> 「关注/粉丝要做，不过我现在还没有精力做，等我把项目完善一点了，再加上。
>   昵称/签名要加。私有内容在自己的空间里要显示」

## ★ 口径

```
昵称   = UserProfile.display_name，为空 ⇒ 回落 username（* 存量不用回填）✅
签名   = UserProfile.bio（单行，120 字）
可见性 = 与搜索索引同一套（* 复用 is_searchable 的判断，⛔ 不写第二份）
隐私   = 别人看只给公开；本人看给全部并标注 ⚠
```
"""
from __future__ import annotations

from django.db.models import Q

#: ★ 单页条数（* 用户空间列表）
PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


def display_of(user) -> str:
    """★ 展示名（* 昵称为空就回落到 username）⚠"""
    if user is None:
        return ""
    name = getattr(user, "username", "") or ""
    try:
        profile = user.profile
    except Exception:  # pragma: no cover - 老用户没有 profile
        return name
    return (getattr(profile, "display_name", "") or "").strip() or name


def bio_of(user) -> str:
    """★ 一句话签名（* 没有就空串）⚠"""
    if user is None:
        return ""
    try:
        return (user.profile.bio or "").strip()
    except Exception:  # pragma: no cover
        return ""


def display_map(usernames) -> dict[str, str]:
    """★★ **批量取展示名**（* 搜索结果这种只有用户名的场景用，避免 N+1）⚠"""
    from core.models import UserProfile

    names = [u for u in set(usernames) if u]
    if not names:
        return {}
    rows = UserProfile.objects.filter(
        user__username__in=names, display_name__gt=""
    ).values_list("user__username", "display_name")
    return {name: display.strip() for name, display in rows if display.strip()}


def attach_display(items: list[dict], key: str = "created_by") -> list[dict]:
    """★ 给一批条目补 `created_by_display`（* 一次查询）⚠"""
    names = display_map([it.get(key) for it in items])
    for it in items:
        name = it.get(key) or ""
        it["created_by_display"] = names.get(name, name)
    return items


# ---------------------------------------------------------------- 可见性


def visible_notes_qs(owner, *, is_self: bool):
    """★★ 某个用户的笔记（* 别人只看公开；本人看全部）⚠

    ⚠ 公开口径与 `search/documents.py::is_searchable` **完全一致**：
      笔记公开 ∧ active ∧ (无项目 ∨ 项目公开 ∧ 项目 active) ⚠
    """
    from core.models import Note, Project

    qs = Note.objects.filter(created_by=owner, deleted_at__isnull=True)
    if is_self:
        return qs
    return qs.filter(is_public=True, state=Note.STATE_ACTIVE).filter(
        Q(project__isnull=True)
        | Q(project__is_public=True, project__state=Project.STATE_ACTIVE)
    )


def visible_projects_qs(owner, *, is_self: bool):
    """★ 某个用户的项目（* 别人只看公开 ∧ active）⚠"""
    from core.models import Project

    qs = Project.objects.filter(owner=owner)
    if is_self:
        return qs
    return qs.filter(is_public=True, state=Project.STATE_ACTIVE)


# ---------------------------------------------------------------- 分页


def encode_cursor(obj) -> str:
    """★ keyset 游标：`<created_at iso>|<pk>`（* 稳定、无需 offset 深翻）⚠"""
    return f"{obj.created_at.isoformat()}|{obj.pk}"


def decode_cursor(cursor: str | None) -> tuple | None:
    """★ 解析游标（* 坏了就当没有，从第一页开始）⚠"""
    if not cursor or "|" not in cursor:
        return None
    from datetime import datetime

    ts_raw, _, pk_raw = cursor.partition("|")
    try:
        return datetime.fromisoformat(ts_raw), int(pk_raw)
    except (ValueError, TypeError):
        return None


def paginate(qs, cursor: str | None, limit: int | None = None):
    """★★ **keyset 分页**：按 `created_at` 倒序 + `pk` 兜底 ⚠

    Returns: `(rows, next_cursor)` —— `next_cursor` 为空表示到底了 ✅
    """
    size = max(1, min(int(limit or PAGE_SIZE), MAX_PAGE_SIZE))
    after = decode_cursor(cursor)
    if after is not None:
        ts, pk = after
        qs = qs.filter(Q(created_at__lt=ts) | Q(created_at=ts, pk__lt=pk))

    rows = list(qs.order_by("-created_at", "-pk")[: size + 1])
    has_more = len(rows) > size
    rows = rows[:size]
    return rows, (encode_cursor(rows[-1]) if has_more and rows else "")


# ---------------------------------------------------------------- 统计


def stats_of(owner, *, is_self: bool) -> dict:
    """★ 空间页顶部数字（* 只算"别人能看到的那部分"，本人另给 all）⚠"""
    from core.models import NoteComment, NoteLike

    notes = visible_notes_qs(owner, is_self=is_self)
    projects = visible_projects_qs(owner, is_self=is_self)

    note_ids = list(notes.values_list("pk", flat=True))
    likes = NoteLike.objects.filter(note_id__in=note_ids).count() if note_ids else 0
    comments = (
        NoteComment.objects.filter(
            note_id__in=note_ids, deleted_at__isnull=True
        ).count()
        if note_ids
        else 0
    )

    payload = {
        "notes": len(note_ids),
        "projects": projects.count(),
        "likes": likes,
        "comments": comments,
    }
    if is_self:
        # ★ 本人额外知道"含私有"的总量 ⚠
        payload["notes_all"] = notes.count()
        payload["projects_all"] = projects.count()
    return payload
