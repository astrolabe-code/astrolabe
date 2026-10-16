"""Astrolabe · **笔记接口**（★ `B187` · 2026-10-15）

★★★ **本文件只做一件事**：★ 把 `core_note` 那张表暴露成 HTTP ⚠

## ★★ 六条口径

```
① ★★ `blocks` 由【后端】重算并返回 ⚠
     · · ★ 前端 ❌ 不自己切段落（* 否则"评论挂的段"与"看到的段"会不一致）⚠
     · · ★ 见 `graph/notes.py::realign`（* B188 的对齐算法）✅

② ★★ 段落按【空行分隔】· ★ 只有"完全相同"才续用原锚点 ⚠
     · · ★ 所有者原话（A5）：「我查了番茄小说的机制，他也是哪怕改一个字，
       段评就没了的」✅

③ ★★ 私有笔记 ⇒ ★ 只有作者能读 ⚠
     · · ★ 项目级：* 私有项目 ⇒ owner ∨ 协作者 ∨ staff（* `can_view`，* B207②）✅
     · · ★ 笔记级：* `is_public=false` ⇒ * 作者 ∨ owner ∨ 协作者 ∨ staff
       （* `note_readable` 两层判据，* B207⑦）✅
     · · ★★ 协作者能看别人的私有笔记（* 所有者原话整句：「不能看，怎么修改？」）✅

④ ★★ 删除笔记 ⇒ ★ 它的段落 / 评论 / 点赞 CASCADE 消失 ✅
     · · ★ 而**修改记录（revision）也删** —— ★ 那是这个笔记自己的历史 ⚠

⑤ ★★ `title` 允许手改，* 但保存时**拿正文首行覆盖** ⚠
     · · ★ 折中：* 建时取正文前几字；* 保存时若开头有 `#` 标题则用它 ✅
     · · ★★ 其余时候不动 ✅

⑥ ★★ `kind` 固定 5 种 ⚠
     flash / question / confuse / pitfall / summary（* B201）✅
```

"""

from __future__ import annotations

from django.http import HttpRequest
from django.views.decorators.http import require_http_methods

from core.models import Note
from core.refs import new_project_ref  # noqa: F401  （* 仅说明 ref 口径一致）
from graph import notes as note_alg
from graph import scope
from web.http import fail, ok_flat, read_json
from web.permissions import (
    can_edit,
    can_view,
    current_user,
    get_project,
    note_readable,
    note_writable,
)

#: ★★ **`kind` 固定 5 种**（★ 所有者 2026-10-15 定，* B201）⚠
#: ★ 固定枚举 ⇒ ★ ❌ 不是用户自定义字段（* 同 B190 的规矩）⚠
KINDS = ("flash", "question", "confuse", "pitfall", "summary")

#: ★ 标题最多多少字（* 与模型 `varchar(120)` 一致）
TITLE_MAX = 120
#: ★ 一页最多多少篇
NOTES_PAGE_MAX = 100


# ---------------------------------------------------------------------------
# 列表 / 新建
# ---------------------------------------------------------------------------

@require_http_methods(["GET", "POST"])
def collection(request: HttpRequest, project_ref: str):
    """`GET/POST /api/projects/<ref>/notes/`。

    ## GET

    `?kind=&limit=&offset=` ⇒ `{total, items:[note]}`

    ⚠★ **只发这个项目"可见的"笔记** ✅
      · · ★ 游客 ⇒ ★ 只看 `is_public=true` 的 ⚠
      · · ★ 作者 ⇒ ★ 看全部（* 含私有）✅
      · · ★★ 而"作者"的判据是 `created_by`（* ❌ 不是 owner）——
        ★ 因为协作者将来也要能看私有笔记（* 第 8 批）⚠

    ## POST

    `{kind, title?, body}` ⇒ `{note, blocks}`
    """
    project = get_project(request, project_ref)
    if project is None or not can_view(request, project):
        return fail("项目不存在", 404, code="not_found")

    if request.method == "POST":
        if not can_edit(request, project):
            return fail("没有权限在这个项目里写笔记", 403, code="forbidden")
        return _create(request, project)

    return _list(request, project)


def _list(request: HttpRequest, project):
    user = current_user(request)
    # ⚠★★ 2026-10-15：**不能按 `node__project_ref` 筛** ⚠
    #
    # ★★ 为什么：* `Note.node` 挂在 `graph_node` 上，* 而一个节点可能属
    #   【基图】（* 解析产物）或【项目】（* 手工新增）⚠
    #   · · ★ 只按 `project_ref` 筛 ⇒ ★★ 挂在【解析节点】上的笔记**一篇都找不到** ⚠
    #     （* 而那是静默的：* 列表看着正常，* 只是少了一部分）⚠
    #   · · ★★ 而 `scope.readable_nodes_of()` 正是"这个项目该读哪些节点"的
    #     唯一判据（* `B186` 立的，* 见 `graph/scope.py`）✅
    node_ids = scope.readable_nodes_of(project.project_ref).values_list("pk", flat=True)
    qs = Note.objects.filter(node_id__in=node_ids)
    # ⚠★ 私有笔记只有作者能看 ✅
    # ★★ `B208`⑧：* **被隐藏的笔记**（* state=hidden）对**非作者**一律不列 ✅
    #   （* 隐藏 = 只有作者能看到，* 比私有更严：* 协作者也不可）⚠
    if user is None:
        qs = qs.filter(is_public=True, state=Note.STATE_ACTIVE)
    else:
        from django.db.models import Q

        qs = qs.filter(
            Q(is_public=True, state=Note.STATE_ACTIVE) | Q(created_by=user)
        )

    kind = (request.GET.get("kind") or "").strip()
    if kind:
        qs = qs.filter(kind=kind)

    limit = _clamp(request.GET.get("limit"), 1, NOTES_PAGE_MAX, 50)
    offset = _clamp(request.GET.get("offset"), 0, 10**9, 0)

    total = qs.count()
    items = [_note_json(n) for n in qs.order_by("-created_at")[offset:offset + limit]]
    return ok_flat(total=total, limit=limit, offset=offset, items=items)


def _create(request: HttpRequest, project):
    body = read_json(request)
    kind = str(body.get("kind") or "flash").strip()
    if kind not in KINDS:
        return fail(f"kind 必须是 {KINDS} 之一", 400, code="bad_kind")

    text = str(body.get("body") or "")
    if not text.strip():
        return fail("笔记正文不能为空", 400, code="empty_body")

    # ⚠★ `node_id` 由前端传（* 笔记挂在哪个代码节点下）⚠
    #   · · ★ 而 `B117` 定了"不能重复的才用来挂"⇒ ★ 挂 node_id ✅
    node_id = body.get("node_id")
    if node_id is None:
        return fail("必须指定 node_id（笔记挂在哪个节点下）", 400, code="missing_node")

    from graph.models import Node

    node = Node.objects.filter(pk=node_id).first()
    if node is None:
        return fail("节点不存在", 404, code="node_not_found")

    # ★★ `title`：* 用户传了就用；* 否则取正文前几字 ✅
    title = str(body.get("title") or "").strip()[:TITLE_MAX] or _auto_title(text)

    note = Note.objects.create(
        node=node,
        kind=kind,
        title=title,
        body=text,
        is_public=bool(body.get("is_public", True)),
        created_by=request.user,
    )
    blocks = note_alg.realign(note)
    return ok_flat(note=_note_json(note), blocks=[_block_json(b) for b in blocks])


# ---------------------------------------------------------------------------
# 单篇
# ---------------------------------------------------------------------------

@require_http_methods(["GET", "PATCH", "DELETE"])
def detail(request: HttpRequest, note_id: int):
    """`GET/PATCH/DELETE /api/notes/<id>/`。

    ## PATCH

    `{kind?, title?, body?, card_skin?, is_public?}` ⇒ `{note, blocks}`

    ⚠★★ **改了 `body` ⇒ ★ 后端重算段落** ⚠
      · · ★ 而重算会让"改了字的段"掉锚 ⇒ ★ 它的段评按
        `note.orphan_comment_policy` 处置 ✅
      · · ★★ 前端**必须**用返回的 `blocks` 刷新锚点 ⚠

    ## DELETE

    `{deleted:true}` —— ★★ 它的段落 / 评论 / 点赞 / 版本**一并消失** ⚠
    """
    note = Note.objects.filter(pk=note_id).select_related("node").first()
    if note is None:
        return fail("笔记不存在", 404, code="not_found")

    if not note_readable(request, note):
        return fail("笔记不存在", 404, code="not_found")

    if request.method == "DELETE":
        if not note_writable(request, note):
            return fail("没有权限删除这篇笔记", 403, code="forbidden")
        note.delete()
        return ok_flat(deleted=True)

    if request.method == "PATCH":
        if not note_writable(request, note):
            return fail("没有权限修改这篇笔记", 403, code="forbidden")
        return _patch(request, note)

    return ok_flat(note=_note_json(note),
                   blocks=[_block_json(b) for b in note.blocks.order_by("ordinal")])


def _patch(request: HttpRequest, note: Note):
    body = read_json(request)
    changed = []

    if "kind" in body:
        kind = str(body.get("kind") or "").strip()
        if kind not in KINDS:
            return fail(f"kind 必须是 {KINDS} 之一", 400, code="bad_kind")
        note.kind, _ = kind, changed.append("kind")

    if "title" in body:
        # ⚠★ `title` **允许手改** ⇒ ★ 用户传了就用 ✅
        note.title = str(body.get("title") or "").strip()[:TITLE_MAX]
        changed.append("title")

    if "card_skin" in body:
        note.card_skin = str(body.get("card_skin") or "").strip()[:200]
        changed.append("card_skin")

    if "is_public" in body:
        note.is_public = bool(body.get("is_public"))
        changed.append("is_public")

    if "body" in body:
        text = str(body.get("body") or "")
        if not text.strip():
            return fail("笔记正文不能为空", 400, code="empty_body")
        note.body = text
        changed.append("body")
        # ⚠★ 保存时**顺手补标题**（* 只在用户没手改过时才覆盖）⚠
        if "title" not in body:
            auto = _auto_title(text)
            if auto and not note.title:
                note.title = auto

    if not changed:
        return fail("没有要改的字段", 400, code="nothing_to_change")

    note.save()

    # ★★ 改了正文 ⇒ ★ 重算段落 ✅
    if "body" in changed:
        blocks = note_alg.realign(note)
    else:
        blocks = note.blocks.order_by("ordinal")

    return ok_flat(note=_note_json(note), blocks=[_block_json(b) for b in blocks])


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------


def _auto_title(body: str) -> str:
    """★★ **从正文推一个标题**（* 取第一段的前几个字）✅

    ⚠★ 若开头是 markdown 标题（`# …`）⇒ ★ 优先用它 ⚠
      （* 那是用户**明写**的标题，* 比"截断正文"更准）✅
    """
    for line in (body or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            return s.lstrip("#").strip()[:TITLE_MAX]
        return s[:TITLE_MAX]
    return ""


def _note_json(n: Note) -> dict:
    return {
        "id": n.pk,
        "node_id": n.node_id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "card_skin": n.card_skin,
        "is_public": n.is_public,
        # ★★ `B208`⑦：* 状态 + 最近一次处置 ⇒* 作者要知道"为什么被隐藏" ✅
        "state": n.state,
        "moderation_reason": n.moderation_reason,
        "moderated_at": n.moderated_at.isoformat() if n.moderated_at else "",
        "like_count": n.like_count,
        "comment_count": n.comment_count,
        "created_by": n.created_by.get_username() if n.created_by_id else "",
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


def _block_json(b) -> dict:
    return {
        "id": b.pk,
        "ordinal": b.ordinal,
        "text": b.text,
        "fingerprint": b.fingerprint,
        "comment_count": b.comment_count,
    }


def _clamp(raw, lo: int, hi: int, default: int) -> int:
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))
