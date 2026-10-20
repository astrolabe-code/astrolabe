"""Astrolabe · **点赞接口**（★ `B203` ⑤ · 2026-10-16）

★★★ **本文件只做一件事**：★ 把 `core_note_like` 那张表暴露成 HTTP ⚠

## ★★ 七条口径（★ 全是已登记的决策）

```
① ★★ 章赞与段赞【同表】（* B187）——
     · · ★ `anchor_kind=chapter`   ⇒ ★ block 恒 NULL ✅
     · · ★ `anchor_kind=paragraph` ⇒ ★ **必须**给 block_id ✅

② ★★★ **幂等**（* B203⑤ 原话：「重复 POST 返回 200 且计数不变，❌ 不是 409」）——
     · · ★ 点过了再点 ⇒ ★ `200` + `already:true` + **计数不动** ✅
     · · ★ 取消一个**没点过**的赞 ⇒ ★ 同样 `200`（* 取消也幂等）✅
     · · ★★ 靠模型上那两条【偏唯一索引】保证（* `uniq_like_chapter` /
       `uniq_like_paragraph`）⚠

③ ★★ `Note.like_count` = 这篇笔记的**全部**赞（* 章赞 + 段赞）——
     · · ★ 段落级**没有**计数列 ⇒ ★ 段赞计数现算（* 一条段被赞的次数不多）✅
     · · ★★ 而它是**缓存**，* 真相在 `core_note_like` 的行（* `B146` 纪律）⚠
     · · ★ 可能改行数的地方都**同事务**维护它：* 赞 / 取消（* 本文件）·
       realign 删段（* `graph/notes.py::_recount_likes`）✅

④ ★★ 私有笔记 ⇒ ★ 只有作者能赞（* 与评论同口径：* 先可读，* 再谈登录）⚠

⑤ ★★ 写权只要登录（* UGC 写权**不依赖** can_edit）⚠

⑥ ★★ 响应形态 ①（* `{ok:true,data:{…}}`）—— * 同 `views/comments.py` ⚠

⑦ ★★★ **B站机制（* `B211` / `B212`，* 2026-10-17）**⚠
     · · ★★ **计数与状态是两套数据**：* 计数 = 聚合合并（* 可滞后）；
       * 状态 = 每用户独立（* 要准）✅
     · · ★★ `GET` 端点给**初始态**（* 「我赞过没有」+ 合并计数）✅
     · · ★★ 写路径（* 赞行 + 计数 ±1）**同一个事务**（* 本项目没有
       `ATOMIC_REQUESTS`，* ❌ 不包就是两次独立写 ⇒* 漂移）⚠
     · · ★★ 正确性红线（* `B212`①）：* 允许有界滞后（* ≤防抖窗口 / 丢一次），
       * ❌ 不许系统性漂移（* 只涨不减 / 重复计）⚠
```
"""

from __future__ import annotations

from django.http import HttpRequest
from django.views.decorators.http import require_http_methods

from core import like_cache
from core.models import Note, NoteBlock, NoteLike
from web.http import fail, ok, read_json
from web.permissions import can_like, current_user, note_readable


@require_http_methods(["GET", "POST", "DELETE"])
def collection(request: HttpRequest, note_id: int):
    """`GET/POST/DELETE /api/notes/<id>/likes/`。

    ## GET（`B211`③：* 初始态的服务端来源）

    `?anchor_kind=&block_id=` ⇒ `{liked, like_count}`

    ⚠★ 未登录 ⇒ `{liked:false, like_count}`（* 计数对**所有人**可见，
      * 状态只对登录用户有意义）✅

    ## POST（点赞）

    `{anchor_kind, block_id?}` ⇒ `{liked:true, already:bool, like_count}`

    ## DELETE（取消赞）

    `?anchor_kind=&block_id=` ⇒ `{liked:false, removed:bool, like_count}`

    ⚠★ 两者都**幂等**（* B203⑤）—— * 重复点赞不 409、* 取消没点过的也不 404 ⚠
    """
    note = Note.objects.filter(pk=note_id).select_related("node").first()
    if note is None or not note_readable(request, note):
        return fail("笔记不存在", 404, code="not_found")

    # ★★★ 2026-10-20：**段赞已下线**（* 所有者：「把章赞里的段赞字段和相关的
    #   索引和约束删掉」）⇒* 只要不是 chapter 一律 400，* 不再静默当章赞 ⚠
    if _anchor_kind(request) != "chapter":
        return fail("段赞已下线，只支持章赞", 400, code="paragraph_like_removed")

    # ★★ `B211`③：* GET 不需要登录（* 计数对所有人可见）✅
    if request.method == "GET":
        return _status(request, note)

    # ★★ `B207`⑥：* 任何登录用户可赞 ——* 判据收拢到门面（* `B209`）✅
    #   ⚠ 可读性上面刚判过 ⇒* 到这里还不过 = **没登录** ⇒* 401 ✅
    if not can_like(request, note):
        return fail("请先登录", 401, code="unauthenticated")
    user = current_user(request)

    if request.method == "POST":
        return _like(request, note, user)
    return _unlike(request, note, user)


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------

def _anchor_kind(request: HttpRequest) -> str:
    """★ 取 `anchor_kind`：* POST 读请求体，* GET / DELETE 读查询参数 ⚠"""
    if request.method == "POST":
        return str(read_json(request).get("anchor_kind") or "chapter").strip()
    return (request.GET.get("anchor_kind") or "chapter").strip()


def _status(request: HttpRequest, note: Note):
    """★★ **「我赞过没有 + 计数」**（* 章赞初始态）⚠

    ⚠ 未登录 ⇒ `liked:false`（* 计数照样给 ——* 它对所有人可见）✅
    """
    user = current_user(request)
    liked = (
        user is not None and NoteLike.objects.filter(note=note, user=user).exists()
    )
    return ok({"liked": liked, "like_count": _like_count_of(note.pk)})


def _like(request: HttpRequest, note: Note, user):
    """★ 章赞：一人一次（* `uniq_like_chapter` 唯一约束兜底）⚠"""
    from django.db import transaction

    # ★★ 只写赞行 —— **不再维护 like_count 缓存**（* 所有者：「把这两个缓存去掉」）⚠
    with transaction.atomic():
        _like_row, created = NoteLike.objects.get_or_create(note=note, user=user)

    # ★ 事务提交后再调缓存（* 只改已存在的 key，* 不存在就不管）⚠
    if created:
        like_cache.bump_note(note.pk, 1)

    return ok(
        {
            "liked": True,
            # ★★ 点过了再点 ⇒ * already:true 且**计数不变**（* B203⑤）⚠
            "already": not created,
            "like_count": _like_count_of(note.pk),
        }
    )


def _unlike(request: HttpRequest, note: Note, user):
    """★ 取消章赞（* 幂等：没点过也 200）⚠"""
    from django.db import transaction

    # ★★ 只删赞行 —— 计数的**真相**在数据库；缓存随后同步 ⚠
    with transaction.atomic():
        removed, _ = NoteLike.objects.filter(note=note, user=user).delete()

    if removed:
        like_cache.bump_note(note.pk, -1)

    return ok(
        {
            "liked": False,
            # ★★ 取消一个没点过的赞 ⇒ * removed:false，* 照样 200 ✅
            "removed": bool(removed),
            "like_count": _like_count_of(note.pk),
        }
    )


def _like_count_of(note_pk: int) -> int:
    """★ 笔记的章赞数 —— **Redis 缓存优先，miss 才 COUNT** ⚠"""
    return like_cache.note_count(
        note_pk, lambda: NoteLike.objects.filter(note_id=note_pk).count()
    )
