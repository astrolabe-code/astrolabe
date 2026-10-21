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

④ ★★ 删除笔记 ⇒ ★★ **软删**（* `B210`）⚠
     · · ★ 只写 `deleted_at` / `deleted_by` 两列，* 段落 / 评论 / 点赞**原样留着** ✅
     · · ★★ 从回收站可恢复（* `GET /api/me/notes/deleted/` + `POST .../undelete/`）✅
     · · ★★ 而**管理员删 = 物理删**（* `moderate` 的 `take_down`，* 无恢复）⚠
     · · ★ 软删的笔记对**所有人**不可见（* 含作者，* `can_read_note` 顶部判定）✅

⑤ ★★ `title` 允许手改，* 但保存时**拿正文首行覆盖** ⚠
     · · ★ 折中：* 建时取正文前几字；* 保存时若开头有 `#` 标题则用它 ✅
     · · ★★ 其余时候不动 ✅

⑥ ★★ `kind` 固定 5 种 ⚠
     flash / question / confuse / pitfall / summary（* B201）✅
```

"""

from __future__ import annotations

from urllib.parse import quote

from django.http import HttpResponse, HttpRequest
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core import like_cache
from core import search_cache
from core.models import Note, NoteLike
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
    project_of,
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
    # ★★★ `B226`：* 笔记**绑项目** ⇒* 直接按项目筛（* 不再用「可读节点」反推）⚠
    #   · · ★ 这也顺带保证「**不跨版本**」—— * 项目不可换绑（`B227`）✅
    # ★★ `B210`：* 软删的笔记不进任何列表（* 它在回收站里）⚠
    qs = Note.objects.filter(project=project, deleted_at__isnull=True)
    # ⚠★ 私有笔记的可见范围（* 与 `can_read_note` **保持一致**）：
    #   · · ★ 公开且在生效中 ⇒ 所有人可见 ✅
    #   · · ★ 作者本人 ⇒ 自己的笔记（* 含私有 / 隐藏）✅
    #   · · ★★ 项目 owner / 协作者 ⇒ 项目内**所有非隐藏**笔记（* 含别人写的私有）⚠
    #   · · ★ 隐藏（`state=hidden`）⇒ **只有作者**（* 比私有更严）✅
    # ⚠ 2026-10-20 修：* 之前只写了「公开 | 作者」⇒* 项目 owner 把自己项目里
    #   别人写的笔记设为私有后，* 自己在列表里也看不见它了 ⚠
    if user is None:
        qs = qs.filter(is_public=True, state=Note.STATE_ACTIVE)
    else:
        from django.db.models import Q

        from core.models import Collaborator

        visible = Q(is_public=True, state=Note.STATE_ACTIVE) | Q(created_by=user)

        is_manager = project.owner_id == user.pk or Collaborator.objects.filter(
            project=project, user=user
        ).exists()
        if is_manager:
            # ★ 管理员/协作者：* 看得到私有，* 但隐藏的仍只有作者 ✅
            visible |= Q(state=Note.STATE_ACTIVE)

        qs = qs.filter(visible)

    kind = (request.GET.get("kind") or "").strip()
    if kind:
        qs = qs.filter(kind=kind)

    limit = _clamp(request.GET.get("limit"), 1, NOTES_PAGE_MAX, 50)
    offset = _clamp(request.GET.get("offset"), 0, 10**9, 0)

    total = qs.count()
    page = list(qs.order_by("-created_at")[offset:offset + limit])

    # ★★ 章赞数走 Redis 批量（* miss 的才 COUNT，* 一次 GROUP BY 回源）⚠
    ids = [n.pk for n in page]
    if ids:
        from django.db.models import Count

        def _db_counts(missing: list[int]) -> dict[int, int]:
            rows = (
                NoteLike.objects.filter(note_id__in=missing)
                .values("note_id")
                .annotate(c=Count("id"))
            )
            return {r["note_id"]: r["c"] for r in rows}

        counts = like_cache.note_counts(ids, _db_counts)
        for n in page:
            n._like_total = counts.get(n.pk, 0)

    items = [_note_json(n) for n in page]
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

    from graph import kinds, scope

    # ★★ `B219`/`B220`：* `node_id` 现在是 **stable_vid** ⇒
    #   * 必须在本项目**可读节点**里找（* 防跨项目 / 跨仓库撞号）⚠
    try:
        want_vid = int(node_id)
    except (TypeError, ValueError):
        return fail("node_id 必须是数字", 400, code="bad_node")

    node = scope.readable_nodes_of(project.project_ref).filter(stable_vid=want_vid).first()
    if node is None:
        return fail("节点不存在", 404, code="node_not_found")

    # ★★ `title`：* 用户传了就用；* 否则取正文前几字 ✅
    title = str(body.get("title") or "").strip()[:TITLE_MAX] or _auto_title(text)

    note = Note.objects.create(
        # ★★ `B226`：* 笔记**绑项目**（版本由「项目 → 基图」查得）⚠
        project=project,
        node=node,
        # ★★★ `B218`：**锚定时刻的节点快照** —— 节点行没了，* 笔记仍能自描述 / 导出 / 重挂 ⚠
        node_vid=node.stable_vid,
        node_name=node.name[:512],
        node_kind=kinds.kind_name(node.kind)[:32],
        node_qname=(node.qname or "")[:512],
        node_file_path=node.file_path[:1024],
        node_line=node.line,
        node_line_end=node.line_end if node.line_end is not None else -1,
        kind=kind,
        title=title,
        body=text,
        is_public=bool(body.get("is_public", True)),
        created_by=request.user,
    )
    blocks = note_alg.realign(note)
    # ★ 新建会影响搜索结果 ⇒ 清缓存（* TTL 只是兜底）⚠
    search_cache.invalidate(search_cache.NS_NOTES)
    return ok_flat(note=_note_json(note), blocks=[_block_json(b) for b in blocks])


# ---------------------------------------------------------------------------
# 单篇
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
def search(request: HttpRequest):
    """`GET /api/notes/search/?q=` —— **全局笔记搜索**（首页搜索框用）。

    ⚠ 所有者原话：「你这现在只能搜索项目名称。无法搜索用户和笔记标题吗？」

    ## ★★ 匹配范围
    - 标题（`title`）+ 正文（`body`）⇒ `icontains`（大小写不敏感）✅

    ## ★★ 可见范围（与项目内笔记列表同一套判据）
    ```
    游客              ⇒ 公开且生效中的笔记
    登录用户          ⇒ 公开 ∨ 自己写的 ∨ 项目 owner / 协作者可见的（含私有）
    ```

    ## ★ 返回
    `{total, items:[note…]}`，每篇额外带 `project` 三件套
    （`project_ref` / `project_name` / `version_label`）⇒ 前端能链回项目 ✅
    """
    from django.db.models import Q

    kw = (request.GET.get("q") or "").strip()
    if not kw:
        return ok_flat(total=0, items=[])

    user = current_user(request)
    uid = getattr(user, "pk", 0) or 0

    # ★★ 先查 Redis（* 频繁搜索的词直接命中，* 不打数据库）⚠
    cached = search_cache.get(search_cache.NS_NOTES, uid, kw)
    if cached is not None:
        return ok_flat(total=len(cached), items=cached)

    qs = Note.objects.filter(deleted_at__isnull=True, state=Note.STATE_ACTIVE)

    if user is None:
        qs = qs.filter(is_public=True)
    else:
        visible = Q(is_public=True) | Q(created_by=user)
        # ★ 项目 owner / 协作者 ⇒ 看得到项目内的私有笔记 ✅
        visible |= Q(project__owner=user) | Q(project__collaborators__user=user)
        qs = qs.filter(visible)

    # ⚠ LIKE 通配符转义（* 用户输入 % / _ 不该当通配符用）⚠
    like = kw.replace("%", "").replace("_", "")
    qs = qs.filter(Q(title__icontains=like) | Q(body__icontains=like)).distinct()
    qs = qs.order_by("-created_at")

    limit = _clamp(request.GET.get("limit"), 1, 50, 20)
    items = list(qs[:limit])

    out = []
    for n in items:
        d = _note_json(n)
        d["project"] = _project_label(n)
        out.append(d)

    # ★ 回源后写缓存（* TTL 兜底 + 写入时主动失效）⚠
    search_cache.put(search_cache.NS_NOTES, uid, kw, out)
    return ok_flat(total=len(out), items=out)


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

    `{deleted:true}` —— ★★ **软删**（* `B210`）：* 进回收站，* **可恢复** ⚠
      · · ★ 段落 / 评论 / 点赞**原样留着**（* 恢复即全文回来）✅
      · · ★★ 管理员删是另一条路：* `POST /api/admin/notes/<id>/moderate/`
        `{action: take_down}` = **物理删、* 无恢复**（* `B208` / `B210`）⚠
    """
    note = Note.objects.filter(pk=note_id).select_related("node").first()
    if note is None:
        return fail("笔记不存在", 404, code="not_found")

    if not note_readable(request, note):
        return fail("笔记不存在", 404, code="not_found")

    if request.method == "DELETE":
        if not note_writable(request, note):
            return fail("没有权限删除这篇笔记", 403, code="forbidden")
        # ★★ `B210`：**软删** ——* 只写两列，* 行还在，* 从回收站可恢复 ✅
        #   ⚠★ 谁删的记在 `deleted_by`（* 所有者要求「分清管理员删的还是
        #     其他用户删的」；* 而管理员删的是物理删，* 行都没了 ⇒* 软删行
        #     必然是非管理员删的）⚠
        note.deleted_at = timezone.now()
        note.deleted_by = current_user(request)
        note.save(update_fields=["deleted_at", "deleted_by"])
        search_cache.invalidate(search_cache.NS_NOTES)
        return ok_flat(deleted=True)

    if request.method == "PATCH":
        if not note_writable(request, note):
            return fail("没有权限修改这篇笔记", 403, code="forbidden")
        return _patch(request, note)

    return ok_flat(note=_note_json(note),
                   blocks=[_block_json(b) for b in note.blocks.order_by("ordinal")])


# ---------------------------------------------------------------------------
# 回收站 / 恢复（★ `B210` · 2026-10-16）
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
def deleted_bin(request: HttpRequest):
    """`GET /api/me/notes/deleted/` —— ★★ **我的回收站**（* `B210`⑥）⚠

    ⇒ `{items, total, limit, offset}`（* 与笔记列表同一种 ② 型扁平 ✅）

    ## ★★ 装什么（* 三条口径）

    ```
    ① ★★ `deleted_at` 非空（* 软删的）✅
    ② ★★ 且"我"能恢复它 ⇒* 我是作者 ∨ 项目 owner ∨ 项目协作者 ✅
       · · ★★ 所以**协作者删的自己的笔记也看得见**（* 所有者要求的效果）✅
    ③ ★★ 管理员删的不在这里 ——* 那是物理删（* take_down），* 行都没了 ⚠
    ```

    ⚠★ 列表**不含正文**（* 同 D86①：* 先看元信息，* 要看正文另调详情）⚠
      · · ★ 详情也打不开（* 软删的对所有人不可见）⇒* 恢复后再看 ✅
    """
    user = current_user(request)
    if user is None:
        return fail("请先登录", 401, code="unauthenticated")

    from django.db.models import Q

    # ⚠★ `node__project__collaborators__user` ——* `Collaborator` 挂在项目上，
    #   而笔记的节点可能属项目（* 外键）✅
    # ★★ `B226` 之后笔记**绑项目** ⇒ 协作者 / owner 的判断改走 `project__`
    #   （* 原来只能靠 `node__project`，* 挂在基图节点上的笔记就漏了）⚠
    qs = (
        Note.objects.filter(deleted_at__isnull=False)
        .filter(
            Q(created_by=user)
            | Q(project__owner=user)
            | Q(project__collaborators__user=user)
        )
        .distinct()
        .select_related("node", "project", "project__base_graph")
    )

    limit = _clamp(request.GET.get("limit"), 1, NOTES_PAGE_MAX, 50)
    offset = _clamp(request.GET.get("offset"), 0, 10**9, 0)
    total = qs.count()
    items = []
    for n in qs.order_by("-deleted_at")[offset:offset + limit]:
        item = _note_json(n)
        # ★★ `D86`①：* 列表**不含正文** ⚠
        #   · · ★ 回收站只要"哪一篇、谁删的、何时删的"——* 正文是草稿，* ❌ 不往列表漏 ⚠
        #   · · ★ 而且软删笔记的详情对**所有人** 404 ⇒* 想预览也打不开，* 恢复后再看 ✅
        item.pop("body", None)
        # ★★★ `B231`：**项目维度三件套** ——* 前端据此按项目分组 ✅
        #   · · ★ 有快照（* 项目已删）⇒* 用快照；* 否则查活着的项目 ✅
        item.update(_project_label(n))
        items.append(item)
    return ok_flat(total=total, limit=limit, offset=offset, items=items)


@require_http_methods(["POST"])
def undelete(request: HttpRequest, note_id: int):
    """`POST /api/notes/<id>/undelete/` —— ★★ **从回收站恢复**（* `B210`⑥）⚠

    ⇒ `{note, blocks}`（* 与 PATCH 同形 ✅）

    ## ★★ 三条口径

    ```
    ① ★★ 谁能恢复 = 谁能删（* `note_writable`：* 作者 ∨ 协作者 ∨ owner）✅
    ② ★★ 恢复 ⇒* 清 `deleted_at` / `deleted_by` 两列，* 内容一根毛都不动 ✅
    ③ ★★ 段落按 realign 重算（* `D86`②）——* 与 PATCH 同一条路径 ✅
    ```

    ⚠★ 软删期间**没有**任何人改过它的段落（* 它对所有人不可见）⇒
      realign 实际上是空转；* 照 `D86`② 走同一条路，* ❌ 不在这里抄近路 ⚠
    """
    note = Note.objects.filter(pk=note_id).select_related("node").first()
    # ⚠ 不在回收站里（* 或根本没这篇）⇒* 404 ✅
    if note is None or note.deleted_at is None:
        return fail("笔记不存在（或不在回收站里）", 404, code="not_found")

    if not note_writable(request, note):
        return fail("没有权限恢复这篇笔记", 403, code="forbidden")

    note.deleted_at = None
    note.deleted_by = None
    search_cache.invalidate(search_cache.NS_NOTES)
    note.save(update_fields=["deleted_at", "deleted_by"])
    blocks = note_alg.realign(note)
    # ★ 新建会影响搜索结果 ⇒ 清缓存（* TTL 只是兜底）⚠
    search_cache.invalidate(search_cache.NS_NOTES)
    return ok_flat(note=_note_json(note), blocks=[_block_json(b) for b in blocks])


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
    search_cache.invalidate(search_cache.NS_NOTES)

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


def _project_label(n: Note) -> dict:
    """★★★ **项目维度三件套**（`B231`②）——* 回收站按项目分组就靠它 ⚠

    ① 有快照（* 项目已被删）⇒* 用快照 ✅
    ② 否则查活着的项目（* `Note.project` 或节点归属）✅
    """
    if n.project_ref:
        return {
            "project_ref": n.project_ref,
            "project_name": n.project_name,
            "version_label": n.version_label,
        }
    project = n.project or project_of(n)
    if project is None:
        return {"project_ref": "", "project_name": "", "version_label": ""}
    bg = project.base_graph
    return {
        "project_ref": project.project_ref,
        "project_name": project.name,
        "version_label": (
            f"{bg.provider}:{bg.repo_full_name}@{bg.sha}" if bg is not None else ""
        ),
    }


def _note_export_text(n: Note) -> str:
    """★★★ **一篇笔记 = 一个 Markdown 文件**（`B231`②ⓐ）⚠

    ```
    ★★ 文件头一小段 YAML front matter（* 恢复所需信息**只写在这一处**）✅
      · · ★ 下面是正文 ——* ⛔ 不把一篇笔记拆成多个文件 ⚠
    ```
    """
    label = _project_label(n)
    head = {
        "title": n.title,
        "kind": n.kind,
        "created_at": n.created_at.isoformat() if n.created_at else "",
        "is_public": n.is_public,
        "project_ref": label["project_ref"],
        "project_name": label["project_name"],
        "version_label": label["version_label"],
        # ★★ 锚点快照（* 恢复就靠 `vid` = `stable_vid`）⚠
        "node": {
            "vid": n.node_vid if n.node_vid is not None else 0,
            "name": n.node_name,
            "kind": n.node_kind,
            "qname": n.node_qname,
            "file_path": n.node_file_path,
            "line": n.node_line,
            "line_end": n.node_line_end,
        },
    }
    text = "---\n"
    for key, value in head.items():
        if key == "node":
            text += "node:\n"
            for nk, nv in value.items():
                text += f"  {nk}: {nv}\n"
        else:
            text += f"{key}: {value}\n"
    text += "---\n\n"
    return text + (n.body or "")



def _parse_front_matter(text: str) -> tuple[dict, str]:
    """★★ 解析导出文件的 front matter（* 自研小解析器，* 无 yaml 依赖）⚠

    格式见 `_note_export_text()`：* 顶层 `key: value` + 一段两空格缩进的 `node:` 块。
    Returns: `(元信息字典, 正文)`
    """
    meta: dict = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            node: dict = {}
            in_node = False
            for line in head.splitlines():
                if not line.strip():
                    continue
                if line.startswith("node:"):
                    in_node = True
                    continue
                if in_node and line.startswith("  "):
                    key, _, value = line.strip().partition(":")
                    node[key.strip()] = value.strip()
                    continue
                in_node = False
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
            if node:
                meta["node"] = node
    return meta, body


def _slug(text: str) -> str:
    """★ 文件名用的标题片段（* 只留安全字符，* 截断）⚠"""
    keep = []
    for ch in (text or "")[:40]:
        keep.append(ch if (ch.isalnum() or ch in "-_") else "-")
    slug = "".join(keep).strip("-")
    return slug or "note"


def _note_json(n: Note) -> dict:
    return {
        "id": n.pk,
        # ★★ `B219`：* 对外发 stable_vid（* 内部主键不出门）；* 节点没了仍可从快照读 ✅
        "node_id": n.node_vid if n.node_vid is not None else 0,
        # ★★★ `B218`：* 节点快照（* 回收站显示「原节点：name @ file:line」用）⚠
        "node_snapshot": {
            "vid": n.node_vid if n.node_vid is not None else 0,
            "name": n.node_name,
            "kind": n.node_kind,
            "qname": n.node_qname,
            "file_path": n.node_file_path,
            "line": n.node_line,
            "line_end": n.node_line_end,
        },
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "card_skin": n.card_skin,
        "is_public": n.is_public,
        # ★★ `B208`⑦：* 状态 + 最近一次处置 ⇒* 作者要知道"为什么被隐藏" ✅
        "state": n.state,
        "moderation_reason": n.moderation_reason,
        "moderated_at": n.moderated_at.isoformat() if n.moderated_at else "",
        # ★★ `B210`：* 软删两列 ——* 回收站靠它们显示"谁删的、何时删的" ✅
        #   （* 正常笔记两项都是空串）✅
        "deleted_at": n.deleted_at.isoformat() if n.deleted_at else "",
        "deleted_by": n.deleted_by.get_username() if n.deleted_by_id else "",
        # ★★ 章赞数：* 列表已批量查好（`_like_total`）；* 单篇走 Redis 缓存 ⚠
        "like_count": (
            n._like_total
            if getattr(n, "_like_total", None) is not None
            else like_cache.note_count(n.pk, lambda: n.likes.count())
        ),
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


@require_http_methods(["POST"])
def export_deleted(request: HttpRequest):
    """★★ `POST /api/me/deleted/export/` —— ★★ **导出所选笔记**（`B231`）⚠

    Body: `{note_ids: [1, 2, 3]}`

    ⇒ `application/octet-stream`（`.astrolabe-backup`，* 见 `core/backup.py`）

    ## ★★ 打包内容（`B231`②）

    ```
    ⓐ 每篇笔记一个 Markdown：* 文件头 front matter（* 含 node 快照）+ 正文
       · · ⛔ 不把一篇笔记拆成多个文件 ✅
    ⓑ manifest.json：* **只记项目级信息** + 文件名清单
       · · ⛔ 不重复每篇的 node 快照（* 文件头已经有了）⚠
    ```

    ⚠★ 权限与回收站列表**同一条判据**（* 只能导自己看得见的）✅
    """
    user = current_user(request)
    if user is None:
        return fail("请先登录", 401, code="unauthenticated")

    body = read_json(request)
    ids = body.get("note_ids")
    if not isinstance(ids, list) or not ids:
        return fail("note_ids 不能为空", 400, code="empty_ids")
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return fail("note_ids 必须是数字数组", 400, code="bad_ids")
    if len(ids) > 500:
        return fail("一次最多导出 500 篇", 400, code="too_many")

    from django.db.models import Q

    qs = (
        Note.objects.filter(pk__in=ids, deleted_at__isnull=False)
        .filter(
            Q(created_by=user)
            | Q(project__owner=user)
            | Q(project__collaborators__user=user)
        )
        .distinct()
        .select_related("project", "project__base_graph")
    )
    notes = list(qs)
    if not notes:
        return fail("没有可导出的笔记（或无权导出）", 404, code="nothing")

    # ---- ⓐ 每篇一个文件 ----
    files: dict[str, bytes] = {}
    manifest_notes = []
    for n in notes:
        name = f"notes/{n.pk:03d}-{n.kind}-{_slug(n.title)}.md"
        files[name] = _note_export_text(n).encode("utf-8")
        label = _project_label(n)
        manifest_notes.append(
            {
                "file": name,
                "note_id": n.pk,
                "kind": n.kind,
                "title": n.title,
                "created_at": n.created_at.isoformat() if n.created_at else "",
                "node": {
                    "vid": n.node_vid if n.node_vid is not None else 0,
                    "name": n.node_name,
                    "kind": n.node_kind,
                    "file_path": n.node_file_path,
                    "line": n.node_line,
                    "line_end": n.node_line_end,
                },
                "project_ref": label["project_ref"],
                "project_name": label["project_name"],
                "version_label": label["version_label"],
            }
        )

    # ---- ⓑ manifest（* 项目级 + 文件名清单，* 不重复 node 快照）----
    first = _project_label(notes[0])
    manifest = {
        "project_ref": first["project_ref"],
        "project_name": first["project_name"],
        "version_label": first["version_label"],
        "exported_at": timezone.now().isoformat(),
        "exported_by": user.get_username(),
        "note_count": len(notes),
        "files": sorted(files),
        "notes": manifest_notes,
    }

    from core import backup

    blob = backup.pack(backup.build_zip(files, manifest))
    filename = f"{_slug(first['project_name'] or 'notes')}-笔记备份.backup"
    resp = HttpResponse(blob, content_type="application/octet-stream")
    resp["Content-Disposition"] = (
        f'attachment; filename*=UTF-8''{quote(filename)}'
    )
    return resp


@require_http_methods(["POST"])
def import_notes(request: HttpRequest):
    """★★ `POST /api/notes/import/` —— ★★ **从导出包恢复笔记**（`B231` / `B232`）⚠

    Form: `file=<.astrolabe-backup>` + `project_ref=<目标项目>`

    ## ★★ 流程（* 顺序不能乱）

    ```
    ① ★★ **先验签**（`B232`）——* 不通过 ⇒ 拒绝（* 文件被篡改）⚠
    ② 解包 ⇒* 逐篇读文件头的 `node.vid`
    ③ ★ 在**目标项目可读的节点**里按 `stable_vid` 找锚点
       · · 命中 ⇒* 原样挂回 ✅
       · · ★★ 没命中（* 代码变了 / 版本不同）⇒* 笔记仍建（* 带快照），
         * 但列入「未能挂回」，* 如实告诉用户 ⚠
    ```

    ⚠★ 权限：* 目标项目要能编辑（* owner ∨ 协作者）✅
    """
    user = current_user(request)
    if user is None:
        return fail("请先登录", 401, code="unauthenticated")

    upload = request.FILES.get("file")
    project_ref = (request.POST.get("project_ref") or "").strip()
    if upload is None:
        return fail("缺少文件（file）", 400, code="missing_file")
    if not project_ref:
        return fail("缺少 project_ref（要恢复到哪个项目）", 400, code="missing_project")

    project = get_project(request, project_ref)
    if project is None:
        return fail("项目不存在或无权访问", 404, code="not_found")
    if not can_edit(request, project):
        return fail("只有项目所有者或协作者能恢复笔记", 403, code="forbidden")

    # ---- ① 验签（* `B232`：* 先验签再解包）----
    from core import backup

    blob = upload.read()
    zip_bytes, err = backup.unpack(blob)
    if err is not None:
        return fail(err, 400, code="bad_signature")

    files, manifest, err = backup.read_zip(zip_bytes)
    if err is not None:
        return fail(err, 400, code="bad_zip")

    # ---- ② 逐篇恢复 ----
    from graph import scope

    readable = scope.readable_nodes_of(project_ref)
    restored, unanchored = [], []

    for name in sorted(files):
        if not name.endswith(".md"):
            continue
        meta, body = _parse_front_matter(files[name].decode("utf-8"))
        node_info = meta.get("node") or {}

        try:
            want_vid = int(node_info.get("vid") or 0)
        except (TypeError, ValueError):
            want_vid = 0
        node = (
            readable.filter(stable_vid=want_vid).first() if want_vid else None
        )

        title = str(meta.get("title") or "")[:120] or _auto_title(body)
        kind = str(meta.get("kind") or "flash").strip()
        if kind not in KINDS:
            kind = "flash"

        note = Note.objects.create(
            project=project,
            node=node,
            node_vid=want_vid or None,
            node_name=str(node_info.get("name") or "")[:512],
            node_kind=str(node_info.get("kind") or "")[:32],
            node_qname=str(node_info.get("qname") or "")[:512],
            node_file_path=str(node_info.get("file_path") or "")[:1024],
            node_line=int(node_info.get("line") or -1),
            node_line_end=int(node_info.get("line_end") or -1),
            kind=kind,
            title=title,
            body=body,
            is_public=str(meta.get("is_public", "True")).lower() != "false",
            created_by=user,
        )
        blocks = note_alg.realign(note)

        row = {"note_id": note.pk, "file": name, "title": title}
        if node is None:
            row["unanchored"] = True
            unanchored.append(row)
        else:
            restored.append(row)


    return ok_flat(
        restored_count=len(restored),
        unanchored_count=len(unanchored),
        restored=restored,
        unanchored=unanchored,
        manifest_project=manifest.get("project_name", ""),
        message=(
            f"已恢复 {len(restored)} 篇"
            + (f"；{len(unanchored)} 篇没能挂回原节点（代码可能已变）" if unanchored else "")
        ),
    )
