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
     · · ★ 所以**没有 PATCH**（* 契约里那条已删）⚠
     · · ★★ 删除必须【软删】（* `deleted_at`）—— * 硬删会让楼中楼断链
       （* 子评论的父没了，* 而 `parent` 是 SET_NULL 也救不了"已删除"的显示）⚠

④ ★★ 楼中楼 = B站口径（* B201②）——
     · · ★ 数据上 `parent_id` 成链、* **深度不限** ✅
     · · ★★ 显示上压两级（* 上级 + 可折叠回复列表）—— * 那是前端的事 ⚠
     · · ★ 本接口：* 默认只给**顶层**；* `?parent=<id>` 拉某条的回复 ✅
     · · ★★ 回复只能回**同类型**的评论（* 章评 thread / 段评 thread 不分家）⚠

⑤ ★★ 失锚评论按项目策略展示（* B189 · `note.orphan_comment_policy`）——
     · · ★ `move_to_chapter` ⇒ ★ 并入章评区、* 标 `orphaned:true` ✅
     · · ★★ `hide`（默认）⇒ ★ 默认列表**不显示**；
       * `?include_hidden=1` 且有权（* 作者/owner/staff）才可见 ⚠
     · · ★★ 数据只有一种形态 ⇒ ★ 策略改了**一条数据都不用搬** ✅

⑥ ★★ 计数冗余（* `Note.comment_count` / `NoteBlock.comment_count`）——
     · · ★ 真相在明细表；* 这里用 `F()` 原子增减，* ❌ 不先查后写 ⚠

⑦ ★★ 谁能读 / 写 / 删（* 契约 §20.2 · D74）——
     · · ★ 读 ⇒ ★ 与笔记同口径（* `permissions.note_readable`，* 只此一份）⚠
     · · ★ 写 ⇒ ★ 登录 + 可读（* UGC 写权**不依赖** can_edit）⚠
     · · ★★ 删 ⇒ ★ 评论作者本人 / 项目 owner / staff ✅

⑧ ★★ 响应形态用 ①（* `{ok:true,data:{…}}`）——
     · · ★ `http.py` 规定"新接口一律 ①"；* ⚠ 与 `views/notes.py`（* ②）不同，
       * 那是因为 notes 先写、* 而 ① 的规矩写在它后面 ⚠（* 见提交说明）⚠
```
"""

from __future__ import annotations

from django.db.models import Count, F, Q
from django.http import HttpRequest
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core import settings_table as st
from core.models import Note, NoteBlock, NoteComment
from graph.notes import project_of
from web.http import fail, ok, read_json
from web.permissions import can_edit, current_user, note_readable

#: ★ 一页最多多少条
PAGE_MAX = 100

#: ★ `quote` 快照最长（★ 与模型 `varchar(500)` 一致）
QUOTE_MAX = 500


# ---------------------------------------------------------------------------
# 列表 / 新建
# ---------------------------------------------------------------------------

@require_http_methods(["GET", "POST"])
def collection(request: HttpRequest, note_id: int):
    """`GET/POST /api/notes/<id>/comments/`。

    ## GET

    `?anchor_kind=chapter|paragraph&block_id=&parent=&include_hidden=&limit=&offset=`

    - `anchor_kind` 缺省 `chapter`；`paragraph` **必须**带 `block_id`
    - `parent` 缺省空 ⇒ 只要顶层；有值 ⇒ 只要那条的回复（楼中楼）
    - `include_hidden=1` ⇒ 失锚且被策略隐藏的段评也列出来（⚠ 仅有权者有效）

    ## POST

    `{body, anchor_kind, block_id?, parent_id?}` ⇒ `{comment, note_comment_count, block_comment_count}`

    ⚠★ `anchor_kind` **创建时定死**；`quote` 后端自动填（前端传了也不算）。
    """
    note = Note.objects.filter(pk=note_id).select_related("node").first()
    if note is None or not note_readable(request, note):
        # ⚠ 越权统一 404（与"不存在"不可区分 —— 同 notes 的口径）
        return fail("笔记不存在", 404, code="not_found")

    if request.method == "POST":
        return _create(request, note)
    return _list(request, note)


def _list(request: HttpRequest, note: Note):
    anchor = (request.GET.get("anchor_kind") or "chapter").strip()
    if anchor not in ("chapter", "paragraph"):
        return fail("anchor_kind 必须是 chapter 或 paragraph", 400, code="bad_anchor")

    # ---- 楼中楼：parent 空 = 顶层；有值 = 某条的回复 ----
    parent = None
    parent_raw = (request.GET.get("parent") or "").strip()
    if parent_raw:
        try:
            parent_pk = int(parent_raw)
        except ValueError:
            return fail("parent 必须是数字", 400, code="bad_parent")
        parent = NoteComment.objects.filter(pk=parent_pk, note=note).first()
        if parent is None:
            return fail("要查看回复的评论不存在", 404, code="parent_not_found")

    q = Q(note=note, deleted_at__isnull=True)
    q &= Q(parent=parent) if parent is not None else Q(parent__isnull=True)

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
        # ⚠★ 只有**顶层**失锚评论才进章评区 —— 楼中楼里的失锚回复
        #   仍留在自己的 thread 里（它有父，* 不对外单独成条）⚠
        if parent is None:
            orphans = Q(is_paragraph=True, block__isnull=True, parent__isnull=True)
            policy = st.get("note.orphan_comment_policy", project=project_of(note))
            if policy == "move_to_chapter":
                q |= orphans
            elif (
                policy == "hide"
                and _truthy(request.GET.get("include_hidden"))
                and _can_see_hidden(request, note)
            ):
                q |= orphans

    qs = NoteComment.objects.filter(q)
    # ⚠ 排序口径（* 与两棵偏索引的方向一致，* 免得回表排序）：
    #   · ★ 顶层列表**新的在前**（* `ix_comment_chapter` / `ix_comment_paragraph`）✅
    #   · ★★ 楼中楼**旧的在前**（* `ix_comment_parent`；* 阅读顺序）✅
    qs = qs.order_by("created_at" if parent is not None else "-created_at")

    limit = _clamp(request.GET.get("limit"), 1, PAGE_MAX, 50)
    offset = _clamp(request.GET.get("offset"), 0, 10**9, 0)

    total = qs.count()
    items = list(qs[offset:offset + limit])
    _attach_reply_counts(items)
    return ok(
        {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_comment_json(c) for c in items],
        }
    )


def _create(request: HttpRequest, note: Note):
    user = current_user(request)
    if user is None:
        return fail("请先登录", 401, code="unauthenticated")

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

    parent = None
    if body.get("parent_id") is not None:
        try:
            parent_pk = int(body.get("parent_id"))
        except (TypeError, ValueError):
            return fail("parent_id 必须是数字", 400, code="bad_parent")
        parent = NoteComment.objects.filter(
            pk=parent_pk, note=note, deleted_at__isnull=True
        ).first()
        if parent is None:
            return fail("要回复的评论不存在", 404, code="parent_not_found")
        if parent.is_paragraph != (anchor == "paragraph"):
            return fail("不能回复另一种类型的评论", 400, code="parent_kind_mismatch")

    comment = NoteComment.objects.create(
        note=note,
        is_paragraph=(anchor == "paragraph"),
        block=block,
        parent=parent,
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

    comment._reply_count = 0
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
    if not _deletable(request, comment):
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

def _deletable(request: HttpRequest, comment: NoteComment) -> bool:
    """★★ **谁能删这条评论**（* `B207`⑤：* 评论作者 ∨ owner ∨ 协作者 ∨ staff）⚠

    ⚠★ **评论只删不改**（* `B201③` 重申）——* 所以这里**没有**"能改"一说 ⚠
    ⚠★ 协作者与 owner / 管理员一样能删**别人**的评论（* 所有者原话整句：
      「协作者跟作者与管理员一样，可以删别人评论。」）✅
    ⚠★ 而"不能修改其他人的评论"也在同一段原话里 ⇒* **改不存在，* 删可以** ⚠
    """
    user = current_user(request)
    if user is None:
        return False
    if getattr(user, "is_staff", False):
        return True
    if comment.created_by_id == user.pk:
        return True
    project = project_of(comment.note)
    return project is not None and can_edit(request, project)


def _can_see_hidden(request: HttpRequest, note: Note) -> bool:
    """★★ **谁能看被隐藏的失锚段评**（* `include_hidden=1` 的权限侧）⚠

    ★★ 作者 / 项目 owner / **协作者** / staff ✅
      （* `B207`① 齐平：* 项目内访问齐平，* 协作者与 owner 同权）⚠
    """
    user = current_user(request)
    if user is None:
        return False
    if getattr(user, "is_staff", False):
        return True
    if note.created_by_id == user.pk:
        return True
    project = project_of(note)
    return project is not None and can_edit(request, project)


def _attach_reply_counts(items: list[NoteComment]) -> None:
    """★★ **一次 GROUP BY 给整页挂上 `reply_count`**（* ❌ 不要 N+1）⚠"""
    ids = [c.pk for c in items]
    if not ids:
        return
    rows = (
        NoteComment.objects.filter(parent_id__in=ids, deleted_at__isnull=True)
        .values("parent_id")
        .annotate(n=Count("pk"))
    )
    counts = {r["parent_id"]: r["n"] for r in rows}
    for c in items:
        # ⚠ 只挂内存属性（* ❌ 不 save）—— * 前端要知道"这条有几条回复" ✅
        c._reply_count = counts.get(c.pk, 0)


def _comment_json(c: NoteComment) -> dict:
    return {
        "id": c.pk,
        "note_id": c.note_id,
        "anchor_kind": c.anchor_kind,
        "block_id": c.block_id,
        "parent_id": c.parent_id,
        "body": c.body,
        "quote": c.quote,
        # ★★ 失锚标记（* `is_paragraph=True` 且 `block_id=None`）——
        #   · ★ 前端显示"原段落已变更或已删除" ✅
        "orphaned": bool(c.is_paragraph and c.block_id is None),
        "reply_count": getattr(c, "_reply_count", 0),
        "created_by": c.created_by.get_username() if c.created_by_id else "",
        "created_at": c.created_at.isoformat(),
    }


def _truthy(raw) -> bool:
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def _clamp(raw, lo: int, hi: int, default: int) -> int:
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))
