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

from django.db.models import F
from django.http import HttpRequest
from django.views.decorators.http import require_http_methods

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

def _status(request: HttpRequest, note: Note):
    """★★ **「我赞过没有 + 合并计数」**（* `B211`③：* 初始态的服务端来源）⚠

    ## ★★ 为什么必须有它（* 所有者三次纠正后的定论）

    ```
    ★★ 前端**不**本地 ±1 计数（* `B211`⑥：* 合并数不是 UI 能动的数字）⚠
      · · ★ 那就必须有个地方回答「**合并计数里有没有含着我的赞**」✅
    ★★ 对应 B站架构（* 2023 公开分享）：
      · · ★ 计数 = 内存聚合一齐写（* 可滞后）· * 状态 = 每用户独立（* 要准）✅
    ```

    ⚠ 未登录 ⇒ `liked:false`（* 计数照样给 ——* 它对所有人可见）✅
    """
    anchor = (request.GET.get("anchor_kind") or "chapter").strip()
    is_paragraph, block, err = _anchor_of(
        note, anchor, request.GET.get("block_id"), source="查询参数"
    )
    if err is not None:
        return err

    user = current_user(request)
    liked = False
    if user is not None:
        qs = NoteLike.objects.filter(note=note, user=user, is_paragraph=is_paragraph)
        if is_paragraph:
            qs = qs.filter(block=block)
        liked = qs.exists()

    return ok({"liked": liked, "like_count": _like_count_of(note.pk)})


def _like(request: HttpRequest, note: Note, user):
    body = read_json(request)
    anchor = str(body.get("anchor_kind") or "chapter").strip()
    is_paragraph, block, err = _anchor_of(
        note, anchor, body.get("block_id"), source="请求体"
    )
    if err is not None:
        return err

    # ★★ `B211`②：**赞行写入与计数 ±1 必须是同一个事务** ⚠
    #   · ★ 本项目**没有** `ATOMIC_REQUESTS` ⇒* ❌ 不显式包起来就是两次独立写，
    #     中间挂掉即漂移（* 而漂移是 `B212`① 明令不许的）⚠
    from django.db import transaction

    with transaction.atomic():
        if is_paragraph:
            like, created = NoteLike.objects.get_or_create(
                note=note, user=user, is_paragraph=True, block=block
            )
        else:
            # ⚠ 章赞：block 恒 NULL —— * 由 `uniq_like_chapter` 偏索引保证一人一次 ✅
            like, created = NoteLike.objects.get_or_create(
                note=note, user=user, is_paragraph=False, block=None
            )

        if created:
            Note.objects.filter(pk=note.pk).update(like_count=F("like_count") + 1)

    return ok(
        {
            "liked": True,
            # ★★ 点过了再点 ⇒ * already:true 且**计数不变**（* B203⑤）⚠
            "already": not created,
            "like_count": _like_count_of(note.pk),
        }
    )


def _unlike(request: HttpRequest, note: Note, user):
    # ⚠ DELETE 用**查询参数**带锚点（* 请求体对 DELETE 不礼貌，* 且容易被代理剥掉）⚠
    anchor = (request.GET.get("anchor_kind") or "chapter").strip()
    is_paragraph, block, err = _anchor_of(
        note, anchor, request.GET.get("block_id"), source="查询参数"
    )
    if err is not None:
        return err

    qs = NoteLike.objects.filter(note=note, user=user, is_paragraph=is_paragraph)
    if is_paragraph:
        qs = qs.filter(block=block)

    # ★★ `B211`②：**删赞行与计数 −1 同一个事务**（* 同 `_like` 的理由）⚠
    from django.db import transaction

    with transaction.atomic():
        removed, _ = qs.delete()
        if removed:
            Note.objects.filter(pk=note.pk).update(like_count=F("like_count") - 1)

    return ok(
        {
            "liked": False,
            # ★★ 取消一个没点过的赞 ⇒ * removed:false，* 照样 200 ✅
            "removed": bool(removed),
            "like_count": _like_count_of(note.pk),
        }
    )


def _anchor_of(note: Note, anchor: str, raw_block, *, source: str):
    """★★ **把 `anchor_kind` + `block_id` 解析成 `(is_paragraph, block)`** ⚠

    Returns:
        `(is_paragraph, block, err)` —— * `err` 非 None 时**直接返回它** ✅
    """
    if anchor not in ("chapter", "paragraph"):
        return (
            False,
            None,
            fail("anchor_kind 必须是 chapter 或 paragraph", 400, code="bad_anchor"),
        )
    if anchor == "chapter":
        if raw_block:
            return (
                False,
                None,
                fail("章赞不能指定段落", 400, code="block_not_allowed"),
            )
        return False, None, None

    # ---- 段赞：必须给一个**属于这篇笔记**的段落 ----
    if raw_block in (None, ""):
        return (
            True,
            None,
            fail(f"段赞必须指定 block_id（{source}）", 400, code="missing_block"),
        )
    try:
        block_pk = int(raw_block)
    except (TypeError, ValueError):
        return True, None, fail("block_id 必须是数字", 400, code="bad_block")
    block = NoteBlock.objects.filter(pk=block_pk, note=note).first()
    if block is None:
        return (
            True,
            None,
            fail("段落不存在（或不属于这篇笔记）", 404, code="block_not_found"),
        )
    return True, block, None


def _like_count_of(note_pk: int) -> int:
    """★ 笔记级点赞总数（* 章赞 + 段赞，* 见口径 ③）✅"""
    return Note.objects.filter(pk=note_pk).values_list("like_count", flat=True).first() or 0
