"""★★ **用户空间**（`/u/<username>` · 2026-10-24）⚠

## ★★★ 所有者原话（逐字）

> 「我想参考B站的用户空间设计。」
> 「关注/粉丝要做，不过我现在还没有精力做，等我把项目完善一点了，再加上。昵称/签名要加。
>   私有内容在自己的空间里要显示」

## ★ 结构（B 站三层：头部资料 → Tab → 内容流）

```
GET /api/u/<username>/            资料 + 统计
GET /api/u/<username>/notes/      笔记（公开 / 本人全部）
GET /api/u/<username>/projects/   项目
GET /api/u/<username>/activity/   笔记 + 项目合并流（主页 Tab）
GET /api/me/profile/              本人资料（GET / PATCH）
```

## ★★ 两条铁律

```
① 别人看：只给公开内容 —— 口径与 `search/documents.py::is_searchable` 一致
② 本人看：给全部，并在每条上标 is_public / state（* 「仅自己可见」角标）⚠
```

## ⚠ 分页

keyset（`created_at` + `pk`），⛔ 不用 offset —— 笔记越写越多，深翻会慢 ⚠
"""
from __future__ import annotations

from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from core import profiles
from core.models import Note, Project
from web.permissions import current_user
from web.http import fail, ok_flat


def _resolve(username: str):
    """★ 用户名 → User（* 找不到就 None）⚠"""
    from django.contrib.auth import get_user_model

    if not username:
        return None
    return get_user_model().objects.filter(username=username).first()


def _self_viewer(request: HttpRequest, user) -> bool:
    viewer = current_user(request)
    return viewer is not None and getattr(viewer, "pk", None) == user.pk


def _note_item(n: Note, likes: dict) -> dict:
    """★ 列表用的瘦笔记（* 不带正文全文，只带摘要）⚠"""
    return {
        "type": "note",
        "ref": n.ref,
        "title": n.title or "",
        "kind": n.kind or "",
        "excerpt": (n.body or "").strip().replace("\n", " ")[:140],
        "is_public": bool(n.is_public),
        "state": n.state or "",
        "like_count": int(likes.get(n.pk, 0)),
        "comment_count": int(n.comment_count or 0),
        "project": (
            {"project_ref": n.project_ref, "project_name": n.project_name}
            if n.project_ref
            else None
        ),
        "created_at": n.created_at.isoformat() if n.created_at else "",
        "updated_at": n.updated_at.isoformat() if n.updated_at else "",
    }


def _project_item(p: Project) -> dict:
    """★ 列表用的瘦项目 ⚠"""
    return {
        "type": "project",
        "project_ref": p.project_ref,
        "name": p.name or "",
        "desc": (p.desc or "")[:140],
        "is_public": bool(p.is_public),
        "state": p.state or "",
        "provider": p.provider or "",
        "node_count": int(p.node_count or 0),
        "edge_count": int(p.edge_count or 0),
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
    }


def _like_counts(notes) -> dict:
    """★ 一批笔记的赞数（* 走 like_cache，miss 才 COUNT）⚠"""
    from django.db.models import Count

    from core import like_cache
    from core.models import NoteLike

    pks = [n.pk for n in notes]
    if not pks:
        return {}
    db_counts = {
        row["note_id"]: row["c"]
        for row in NoteLike.objects.filter(note_id__in=pks)
        .values("note_id")
        .annotate(c=Count("id"))
    }
    return like_cache.note_counts(pks, db_counts)


@require_http_methods(["GET"])
def detail(request: HttpRequest, username: str) -> JsonResponse:
    """★ `GET /api/u/<username>/` —— 资料 + 统计 ⚠"""
    user = _resolve(username)
    if user is None:
        return fail("用户不存在", 404, code="not_found")

    is_self = _self_viewer(request, user)
    return ok_flat(
        username=user.username,
        display_name=profiles.display_of(user),
        bio=profiles.bio_of(user),
        joined_at=user.date_joined.isoformat() if user.date_joined else "",
        is_self=is_self,
        stats=profiles.stats_of(user, is_self=is_self),
    )


@require_http_methods(["GET"])
def notes(request: HttpRequest, username: str) -> JsonResponse:
    """★ `GET /api/u/<username>/notes/?sort=new|hot&cursor=&limit=` ⚠"""
    user = _resolve(username)
    if user is None:
        return fail("用户不存在", 404, code="not_found")

    is_self = _self_viewer(request, user)
    qs = profiles.visible_notes_qs(user, is_self=is_self).select_related("project")

    sort = (request.GET.get("sort") or "new").strip().lower()
    if sort == "hot":
        # ⚠ 「最热」按评论数排（* 赞数在另一张表，排序要 join 聚合，先不用）⚠
        qs = qs.order_by("-comment_count", "-created_at", "-pk")
        rows = list(qs[: max(1, min(int(request.GET.get("limit") or profiles.PAGE_SIZE), profiles.MAX_PAGE_SIZE))])
        return ok_flat(items=[_note_item(n, _like_counts(rows)) for n in rows], next_cursor="")

    rows, cursor = profiles.paginate(qs, request.GET.get("cursor"), request.GET.get("limit"))
    return ok_flat(items=[_note_item(n, _like_counts(rows)) for n in rows], next_cursor=cursor)


@require_http_methods(["GET"])
def projects(request: HttpRequest, username: str) -> JsonResponse:
    """★ `GET /api/u/<username>/projects/?cursor=&limit=` ⚠"""
    user = _resolve(username)
    if user is None:
        return fail("用户不存在", 404, code="not_found")

    is_self = _self_viewer(request, user)
    qs = profiles.visible_projects_qs(user, is_self=is_self)
    rows, cursor = profiles.paginate(qs, request.GET.get("cursor"), request.GET.get("limit"))
    return ok_flat(items=[_project_item(p) for p in rows], next_cursor=cursor)


@require_http_methods(["GET"])
def activity(request: HttpRequest, username: str) -> JsonResponse:
    """★★ `GET /api/u/<username>/activity/` —— 笔记 + 项目**按时间合并**（主页 Tab）⚠

    ```\n    两条流各自 keyset 取一页 ⇒ 归并排序 ⇒ 截断\n    游标格式 `<ts>|<pk>`，* 两条流共用同一个时间水位 ✅\n    ```\n    """
    user = _resolve(username)
    if user is None:
        return fail("用户不存在", 404, code="not_found")

    is_self = _self_viewer(request, user)
    size = max(1, min(int(request.GET.get("limit") or profiles.PAGE_SIZE), profiles.MAX_PAGE_SIZE))

    after = profiles.decode_cursor(request.GET.get("cursor"))
    note_qs = profiles.visible_notes_qs(user, is_self=is_self).select_related("project")
    project_qs = profiles.visible_projects_qs(user, is_self=is_self)

    if after is not None:
        ts, pk = after
        cond = Q(created_at__lt=ts) | Q(created_at=ts, pk__lt=pk)
        note_qs = note_qs.filter(cond)
        project_qs = project_qs.filter(cond)

    note_rows = list(note_qs.order_by("-created_at", "-pk")[: size + 1])
    project_rows = list(project_qs.order_by("-created_at", "-pk")[: size + 1])

    merged = [(n.created_at, n.pk, _note_item(n, _like_counts(note_rows))) for n in note_rows]
    merged += [(p.created_at, p.pk, _project_item(p)) for p in project_rows]
    merged.sort(key=lambda t: (t[0], t[1]), reverse=True)

    page = merged[:size]
    items = [it for _, _, it in page]
    next_cursor = (
        profiles.encode_cursor(type("X", (), {"created_at": page[-1][0], "pk": page[-1][1]})())
        if len(merged) > size and page
        else ""
    )
    return ok_flat(items=items, next_cursor=next_cursor)


@require_http_methods(["GET", "PATCH"])
def my_profile(request: HttpRequest) -> JsonResponse:
    """★★ `GET / PATCH /api/me/profile/` —— 本人资料（昵称 / 签名）⚠

    ```\n    昵称：≤40 字，允许空（空 ⇒ 全站回落 username）\n    签名：≤120 字，单行（换行折成空格）\n    ⛔ 不允许改 username（* 那是身份，不是资料）⚠\n    ```\n    """
    user = current_user(request)
    if user is None:
        return fail("请先登录", 401, code="unauthenticated")

    profile = getattr(user, "profile", None)
    if profile is None:
        from core.models import UserProfile

        profile = UserProfile.objects.create(user=user)

    if request.method == "PATCH":
        import json

        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return fail("请求体不是合法 JSON", 400, code="bad_json")

        dirty: list[str] = []
        if "display_name" in body:
            name = " ".join(str(body.get("display_name") or "").split())[:40]
            profile.display_name = name
            dirty.append("display_name")
        if "bio" in body:
            bio = " ".join(str(body.get("bio") or "").split())[:120]
            profile.bio = bio
            dirty.append("bio")
        if dirty:
            profile.save(update_fields=dirty + ["updated_at"])

    return ok_flat(
        username=user.username,
        display_name=profiles.display_of(user),
        bio=profiles.bio_of(user),
        raw_display_name=profile.display_name or "",
    )
