"""Astrolabe · **评论接口**（★ `B201` / `B203` · 2026-10-16）

★★★ **本文件只做一件事**：★ 把 `core_note_comment` 那张表暴露成 HTTP ⚠

## ★★ 八条口径（★ 全是已登记的决策，* ❌ 不是本文件自创）

```
① ★★ 章评与段评【同表】（* B187）——
     · · ★ `is_paragraph` **创建时定死、* 永不改变**（* B203④）⚠
     · · ★ 接口照旧收发 `anchor_kind`（* 由 `is_paragraph` 派生，* 契约不变）✅

② ★★ `quote` 由【后端】自动填快照（* B203④）——
     · · ★ 段评 ⇒ ★ 那一刻的原文（* 番茄小说口径：* 即便那段后来改了，
       * 也能显示"当时是这句"）⚠

③ ★★★ 评论【只删不改】（* B201③ · 所有者原话：「评论全都是可以删，不能改的」）——
     · · ★ 所以**没有 PATCH**（* 契约里那条已删）✅
     · · ★ 删除是【软删】（* `deleted_at`）——* 数据留着，* 只是不显示 ✅

④ ★★★ **平铺无链**（* `B214` · 2026-10-17 · ⚠ 推翻 `B201②` 的 `parent_id` 成链）⚠
     · · ★★ 所有者原话：「后端存储的评论不要做成链状了，没必要，记录回复谁就行了」
     · · ★★ 「你只要在原来的评论表里加一个类型，是回复还是@或者两个一起，就完了呗」
     · · ★ 所以：* **没有 parent**、* 没有 `?parent=`、* 没有楼中楼的「层」✅
     · · ★★ 「回复谁」记在**正文的 @** 里（* 文本即记录）⚠
     · · ★ `kind` 一列只决定**视觉**：* reply ⇒ 头部「回复 @X」·* mention ⇒ 正文 @ 高亮
       ·* both ⇒ 两者·* comment ⇒ 普通 ✅

⑤ ★★ 失锚评论按项目策略展示（* B189 · `note.orphan_comment_policy`）——
     · · ★ `move_to_chapter` ⇒ ★ 并入章评区、* 标 `orphaned:true` ✅
     · · ★★ `hide`（默认）⇒ ★ 默认列表**不显示**；
       * `?include_hidden=1` 且有权（* 作者/owner/协作者/staff）才可见 ⚠
     · · ★★ 数据只有一种形态 ⇒ ★ 策略改了**一条数据都不用搬** ✅

⑥ ★★ 计数冗余（* `Note.comment_count` / `NoteBlock.comment_count`）——
     · · ★ 真相在明细表；* 这里用 `F()` 原子增减，* ❌ 不先查后写 ⚠

⑦ ★★ 谁能读 / 写 / 删（* 契约 §20.2 · D74 · `B207`⑤）——
     · · ★ 读 ⇒ ★ 与笔记同口径（* `permissions.note_readable`，* 只此一份）⚠
     · · ★ 写 ⇒ ★ 登录 + 可读（* `permissions.can_create_comment`）⚠
     · · ★★ 删 ⇒ ★ 评论作者 ∨ 项目 owner ∨ 协作者 ∨ staff
       （* `permissions.comment_deletable`）✅

⑧ ★★ 响应形态用 ①（* `{ok:true,data:{…}}`）——
     · · ★ `http.py` 规定"新接口一律 ①"；* ⚠ 与 `views/notes.py`（* ②）不同，
       * 那是因为 notes 先写、* 而 ① 的规矩写在它后面 ⚠（* 见提交说明）⚠
```
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count, F, Q
from django.db.models.functions import Greatest
from django.http import HttpRequest
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core import like_cache
from core import settings_table as st
from core.models import Note, NoteBlock, NoteComment, NoteCommentLike
from web.http import fail, ok, ok_flat, read_json
from web.permissions import (
    can_create_comment,
    can_like,
    can_see_hidden_orphans,
    comment_deletable,
    current_user,
    note_readable,
    project_of,
)

#: ★ 一页最多多少条
PAGE_MAX = 100

#: ★ `quote` 快照最长（★ 与模型 `varchar(500)` 一致）
QUOTE_MAX = 500

#: ★★ **@ 提及的识别规则**（* `B214`④）⚠
#:   · · ★ `@` + Django 用户名允许的字符（* 字母数字 `. _ - +`）✅
#:   · · ★★ 只用来**校验"有没有 @"**（* 用户是否存在不查 ——* 文本即记录）⚠
import re as _re

MENTION_RE = _re.compile(r"@[A-Za-z0-9._+-]+")


# ---------------------------------------------------------------------------
# 列表 / 新建
# ---------------------------------------------------------------------------

@require_http_methods(["GET", "POST"])
def collection(request: HttpRequest, note_id: int):
    """`GET/POST /api/notes/<id>/comments/`。

    ## GET

    `?anchor_kind=chapter|paragraph&block_id=&include_hidden=&limit=&offset=`

    - `anchor_kind` 缺省 `chapter`；`paragraph` **必须**带 `block_id`
    - ★★ 平铺（* `B214`）：* 一个 anchor 一个列表，* **没有 `?parent=`** ✅
    - `include_hidden=1` ⇒ 失锚且被策略隐藏的段评也列出来（⚠ 仅有权者有效）

    ## POST

    `{body, anchor_kind, block_id?, kind?}` ⇒ `{comment, note_comment_count, block_comment_count}`

    - ★★ `kind` = `comment`（默认）/ `reply` / `mention` / `both`（`B214`）⚠
    - ★ `kind ∈ {reply, mention, both}` ⇒ 正文**必须**带 `@某人`（否则 400 `missing_mention`）
    - ⚠★ `anchor_kind` **创建时定死**；`quote` 后端自动填（前端传了也不算）。
    """
    note = Note.objects.filter(pk=note_id).select_related("node").first()
    if note is None or not note_readable(request, note):
        # ⚠ 越权统一 404（与"不存在"不可区分 —— 同 notes 的口径）
        return fail("笔记不存在", 404, code="not_found")

    if request.method == "POST":
        # ★★ `B207`⑤：* 任何登录用户可评论 ——* 判据收拢到门面（* `B209`）✅
        #   ⚠ 可读性上面刚判过 ⇒* 到这里还不过 = **没登录** ⇒* 401 ✅
        if not can_create_comment(request, note):
            return fail("请先登录", 401, code="unauthenticated")
        return _create(request, note, current_user(request))
    return _list(request, note)


def _list(request: HttpRequest, note: Note):
    anchor = (request.GET.get("anchor_kind") or "chapter").strip()
    if anchor not in ("chapter", "paragraph"):
        return fail("anchor_kind 必须是 chapter 或 paragraph", 400, code="bad_anchor")

    # ★★ `B214`：**平铺** —— 没有楼中楼的层，* 也就没有 `?parent=` ✅
    #   · · ★ 「回复谁」在正文的 @ 里，* `kind` 只决定视觉 ⚠
    q = Q(note=note, deleted_at__isnull=True)

    block = None
    if anchor == "paragraph":
        raw = (request.GET.get("block_id") or "").strip()
        if not raw:
            return fail("段评列表必须指定 block_id", 400, code="missing_block")
        try:
            block_pk = int(raw)
        except ValueError:
            return fail("block_id 必须是数字", 400, code="bad_block")
        block = NoteBlock.objects.filter(pk=block_pk, note=note).first()
        if block is None:
            return fail("段落不存在（或不属于这篇笔记）", 404, code="block_not_found")
        q &= Q(is_paragraph=True, block=block)
    else:
        q &= Q(is_paragraph=False)
        # ---- 失锚段评：按项目策略决定是否并入章评区（B189）----
        # ⚠★ `B214`：* 评论已**平铺无链** ⇒* 不再有「顶层 / 楼中楼」之分，
        #   失锚段评（* 段评但 block 空了）直接按策略并入章评区 ✅
        orphans = Q(is_paragraph=True, block__isnull=True)
        policy = st.get("note.orphan_comment_policy", project=project_of(note))
        if policy == "move_to_chapter":
            q |= orphans
        elif (
            policy == "hide"
            and _truthy(request.GET.get("include_hidden"))
            and can_see_hidden_orphans(request, note)
        ):
            q |= orphans

    limit = _clamp(request.GET.get("limit"), 1, PAGE_MAX, 50)
    offset = _clamp(request.GET.get("offset"), 0, 10**9, 0)

    # ⚠ 排序口径（* 与两棵偏索引的方向一致，* 免得回表排序）：**新的在前** ✅
    qs = NoteComment.objects.filter(q).order_by("-created_at")

    total = qs.count()
    items = list(qs[offset:offset + limit])

    # ★★ 赞数走 Redis 批量（* miss 的才 COUNT，* 一次 GROUP BY 回源）⚠
    ids = [c.pk for c in items]
    if ids:
        def _db_counts(missing: list[int]) -> dict[int, int]:
            rows = (
                NoteCommentLike.objects.filter(comment_id__in=missing)
                .values("comment_id")
                .annotate(c=Count("id"))
            )
            return {r["comment_id"]: r["c"] for r in rows}

        counts = like_cache.comment_counts(ids, _db_counts)
        for c in items:
            c._like_total = counts.get(c.pk, 0)

    # ★★ 一次查出「我赞过这页里的哪些评论」（* 逐条 exists 就是 N+1）⚠
    liked_ids: set[int] = set()
    me = current_user(request)
    if me is not None and items:
        liked_ids = set(
            NoteCommentLike.objects.filter(
                comment_id__in=[c.pk for c in items], user=me
            ).values_list("comment_id", flat=True)
        )

    return ok(
        {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_comment_json(c, c.pk in liked_ids) for c in items],
        }
    )


def _create(request: HttpRequest, note: Note, user):
    """★ 登录由 `collection` 的门面判过（* `can_create_comment`）——* 这里不重复判 ⚠"""
    body = read_json(request)
    text = str(body.get("body") or "").strip()
    if not text:
        return fail("评论不能为空", 400, code="empty_body")

    anchor = str(body.get("anchor_kind") or "chapter").strip()
    if anchor not in ("chapter", "paragraph"):
        return fail("anchor_kind 必须是 chapter 或 paragraph", 400, code="bad_anchor")

    block = None
    if anchor == "paragraph":
        try:
            block_pk = int(body.get("block_id"))
        except (TypeError, ValueError):
            return fail("段评必须指定 block_id", 400, code="missing_block")
        block = NoteBlock.objects.filter(pk=block_pk, note=note).first()
        if block is None:
            return fail("段落不存在（或不属于这篇笔记）", 404, code="block_not_found")
    elif body.get("block_id"):
        # ★ 章评带 block_id ⇒ ★ 前端口径乱了 ⇒ 明说，* ❌ 不静默忽略 ⚠
        return fail("章评不能指定段落", 400, code="block_not_allowed")

    # ★★ `B214`：**类型一列**替代 `parent_id`（* 回复谁在正文的 @ 里）⚠
    kind = str(body.get("kind") or NoteComment.KIND_COMMENT).strip()
    if kind not in dict(NoteComment.KIND_CHOICES):
        return fail(
            f"kind 必须是 {list(dict(NoteComment.KIND_CHOICES))} 之一",
            400,
            code="bad_kind",
        )
    # ★★ 非普通类型必须带 @（* 否则「回复 @?」渲染不出来）⚠
    if kind in NoteComment.KIND_NEEDS_AT and not MENTION_RE.search(text):
        return fail("回复 / @ 的评论正文里必须带上 @某个用户", 400, code="missing_mention")

    comment = NoteComment.objects.create(
        note=note,
        is_paragraph=(anchor == "paragraph"),
        block=block,
        kind=kind,
        body=text,
        # ★★ quote 由后端填（* B203④）—— * 前端传了也不算 ⚠
        quote=(block.text[:QUOTE_MAX] if block is not None else ""),
        created_by=user,
    )

    # ---- 计数（* F() 原子增减）----
    Note.objects.filter(pk=note.pk).update(comment_count=F("comment_count") + 1)
    block_comment_count = None
    if block is not None:
        NoteBlock.objects.filter(pk=block.pk).update(comment_count=F("comment_count") + 1)
        block_comment_count = NoteBlock.objects.filter(pk=block.pk).values_list(
            "comment_count", flat=True
        ).first()
    note_comment_count = Note.objects.filter(pk=note.pk).values_list(
        "comment_count", flat=True
    ).first()

    return ok(
        {
            "comment": _comment_json(comment),
            "note_comment_count": note_comment_count,
            "block_comment_count": block_comment_count,
        }
    )


# ---------------------------------------------------------------------------
# 单条：软删（★ 只有 DELETE —— 评论只删不改）
# ---------------------------------------------------------------------------

@require_http_methods(["DELETE"])
def detail(request: HttpRequest, comment_id: int):
    """`DELETE /api/comments/<id>/` —— ★★ **软删**（* `deleted_at`）。

    ⚠★ **幂等**：* 删过的再删 ⇒ ★ 照样 200（* 与点赞同一条口径）⚠
    ⚠★ 楼中楼**不断链**：* 子评论的 `parent_id` 还在 ⇒ * 前端显示"该评论已删除" ✅
    """
    comment = (
        NoteComment.objects.filter(pk=comment_id)
        .select_related("note", "note__node")
        .first()
    )
    if comment is None:
        return fail("评论不存在", 404, code="not_found")
    if not note_readable(request, comment.note):
        return fail("笔记不存在", 404, code="not_found")
    if not comment_deletable(request, comment):
        return fail("没有权限删除这条评论", 403, code="forbidden")

    if comment.deleted_at is None:
        NoteComment.objects.filter(pk=comment.pk).update(deleted_at=timezone.now())
        Note.objects.filter(pk=comment.note_id).update(
            comment_count=F("comment_count") - 1
        )
        if comment.block_id is not None:
            NoteBlock.objects.filter(pk=comment.block_id).update(
                comment_count=F("comment_count") - 1
            )
    return ok({"deleted": True})


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------

def _comment_json(c: NoteComment, liked: bool = False) -> dict:
    return {
        "id": c.pk,
        "note_id": c.note_id,
        "anchor_kind": c.anchor_kind,
        "block_id": c.block_id,
        # ★★ `B214`：* 类型（决定视觉）——* `parent_id` / `reply_count` 已下线 ⚠
        "kind": c.kind,
        "body": c.body,
        "quote": c.quote,
        # ★★ 失锚标记（* `is_paragraph=True` 且 `block_id=None`）——
        #   · ★ 前端显示"原段落已变更或已删除" ✅
        "orphaned": bool(c.is_paragraph and c.block_id is None),
        "created_by": c.created_by.get_username() if c.created_by_id else "",
        "created_at": c.created_at.isoformat(),
        # ★★ 评论赞：* 计数**实时数明细表**（* 已去掉 like_count 缓存）+ 我赞过没有 ⚠
        "like_count": (
            c._like_total
            if getattr(c, "_like_total", None) is not None
            else like_cache.comment_count(c.pk, lambda: c.like_rows.count())
        ),
        "liked": liked,
    }


def _truthy(raw) -> bool:
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def _clamp(raw, lo: int, hi: int, default: int) -> int:
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# 评论赞（★ `F3` 补充 · 2026-10-20）
# ---------------------------------------------------------------------------

@require_http_methods(["POST"])
def like_comment(request: HttpRequest, comment_id: int):
    """`POST /api/comments/<id>/like/` —— **设置评论赞的最终状态**。

    ## ★★ 请求体
    `{"liked": true|false}` —— ⛔ 不是 toggle，是**设成这个状态**（幂等）

    ## ★★ 为什么用「设置」而不是「切换」
    - 所有者要求：「连续点击，之后，应该等一秒，用户不再点点赞按钮后，再把用户的
      行为，即是否点赞传回后端记录呀，不要点一次就传一次，疯狂改记录呀。」
    - 前端防抖 1s 后只发**一次**，且发的是**最终状态**
    - ⚠ 若后端做成 toggle，用户点 2 次（最终 = 原来的状态）只发一次请求就会翻反
      ⇒ ★ 所以必须是幂等的「设成 true/false」⚠

    ## ★ 计数
    - **不再有 `like_count` 缓存字段**，赞数实时 `COUNT(core_notecommentlike)`
    """
    comment = (
        NoteComment.objects.filter(pk=comment_id)
        .select_related("note", "note__node")
        .first()
    )
    if comment is None:
        return fail("评论不存在", 404, code="not_found")

    # ★ 能读这篇笔记才能赞它的评论（* 私有 / 隐藏 / 软删同样挡住）⚠
    if not note_readable(request, comment.note):
        return fail("评论不存在", 404, code="not_found")
    if not can_like(request, comment.note):
        return fail("请先登录", 401, code="unauthenticated")

    user = current_user(request)
    body = read_json(request)
    want = bool(body.get("liked", True))

    was = NoteCommentLike.objects.filter(comment_id=comment_id, user=user).exists()

    with transaction.atomic():
        if want:
            NoteCommentLike.objects.get_or_create(comment_id=comment_id, user=user)
        else:
            NoteCommentLike.objects.filter(comment_id=comment_id, user=user).delete()

    # ★ 只在状态**真的变了**时动缓存（* 幂等重复请求不该让数字跳）⚠
    if want and not was:
        like_cache.bump_comment(comment_id, 1)
    elif not want and was:
        like_cache.bump_comment(comment_id, -1)

    count = like_cache.comment_count(
        comment_id, lambda: NoteCommentLike.objects.filter(comment_id=comment_id).count()
    )
    return ok_flat(liked=want, like_count=count)
