"""Astrolabe · ① Web 层：项目（CRUD + 解析触发 + 进度）

★ 契约：`frontend-contract.md` §2 的项目相关行。

⚠ 两处**有意偏离**（都记进决策日志）：

| # | 偏离 | 原因 |
|---|---|---|
| **1** | ★ **不提供 `upload/`（传 zip）** | `B109`：源码**只能由服务端从托管平台获取** ⇒ 新设计里**没有 zip 上传**这条路 |
| **2** | ★ **新增 `parse/`** | 旧站是上传后自动解析；新设计的入口是「贴仓库地址 → 触发解析」 |
"""

from __future__ import annotations

import json

from django.db.models import Count
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from core import search_cache
from core import fetch, oauth, storage
from core import publish as publish_core
# ★★ `F2`：* `_project_json` 要现算 `can_edit` / `can_manage` ⇒* 直接调内核 ⚠
#   · ★ 而**不走门面**（* 门面收 request；* 这里手上已经有 user 对象了）✅
from core import access
# ⚠★ `B176` ①：`OAuthIdentity` / `OAuthState` **不再需要** ——
#   ★ 「拉取代码」已不走 OAuth（★ 不再要求绑定身份、不再建 state）✅
from core.models import Project
# ★★ `B179`：`GraphPatch` 也要用到 ——
#   ★ 删除项目时要清掉"它自己的修改"与"它的绑定"（⚠ 但**不碰共享基图**）⚠
from graph.models import BaseGraph, Edge, GraphPatch, Node
from graph.revision import current as graph_rev_of
from jobs import dispatch
from jobs.models import Job
from web import permissions
from web.http import fail, ok, ok_flat

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def purge_project(project_ref: str, *, by=None) -> int:
    """★★ **物理删除一个项目自己的全部数据**（★ `B208`③：* 下架 = 彻底删除）⚠

    ★★ 所有者原话整句：「**下架是彻底从服务器上删除数据。**」✅

    ## ★★ 删什么（* `B179` 的口径，* 一字未改）

    ```
    · ★ 这个项目**自己的**修改层（* GraphPatch）· 节点 · 边 · 作业 ✅
    · ★★★ **绝不删基图** ——* 基图是**共享**的，* 删掉它 = 别的项目当场变空 ⚠
    · ★ 审核流水**刻意保留**（* `B146`：* append-only，* 删项目不得抹掉限额流水）✅
    ```

    ⚠★ **先释放存储空间**（`B152`）——* 否则磁盘上那份源码会**永远留着**
      （* 而用户以为他删掉了 ⇒* "我明明删了，为什么还是满的"）⚠

    Returns:
        ★ 释放的存储字节数 ✅

    ⚠★ 两个调用方（* 2026-10-16 抽出，* `B208`）：
      · ★ `projects.detail` 的 DELETE（* **owner 删自己的项目**）✅
      · · ★ `moderate.moderate_project` 的 `take_down`（* **管理员下架**）✅
      · · ★★ 同一套级联、* 同一句"绝不删基图"，* ❌ 不写两遍 ⚠
    """
    # ★★ 先释放存储空间（* `B152`）✅
    freed = storage.release(project_ref)

    # ⚠★★ `B179`：这里删的**只是这个项目自己的东西** ⚠
    #   ★ `project_ref` 的那些节点 / 边 = **用户自己新增的**（★ 叠加层）⚠
    #   ★★★ **绝不删基图** —— ★ 基图是**共享**的 ⚠
    #   ★ 顺序：★ **先删修改**（它指着叠加层的节点）⇒ 再删节点 / 边 ✅
    # ★★ `B221`：* 叠加层按 `project` 外键（* 裸 `project_ref` 列已删）⚠
    project = Project.objects.filter(project_ref=project_ref).first()
    if project is not None:
        # ★★★ `B228`（所有者裁定）：**笔记是最重要的数据 —— 不删，只软删进回收站** ⚠
        #   · · ★ 项目没了，* 笔记行**留着**（* `Note.project` = `SET_NULL`）✅
        #   · · ★★ 作者从回收站（* 按 `created_by` 列）就能看到并导出 ✅
        from django.utils import timezone

        from core.models import Note

        # ★★★ `B231`：**项目快照写进笔记**（项目行即将消失 ⇒ 现在不写就永远查不到）⚠
        #   · · ★ 该项目**全部**笔记都写（* 含已在回收站里的）⇒* 导出时归到同一张卡片 ✅
        bg = project.base_graph
        Note.objects.filter(project=project).update(
            project_ref=project.project_ref,
            project_name=project.name[:200],
            # ★ 快照回写也是一次"改动" ⇒ 刷 updated_at（* 搜索缓存据此作废）⚠
            updated_at=timezone.now(),
            version_label=(
                f"{bg.provider}:{bg.repo_full_name}@{bg.sha}" if bg is not None else ""
            ),
        )
        # ★★ `B228`：还没删的 ⇒ 软删进回收站（* 上面的 update 已覆盖它们）
        Note.objects.filter(project=project, deleted_at__isnull=True).update(
            # ★★ 批量软删**不走 `save()`** ⇒ 必须显式带上 updated_at，
            #   * 否则搜索缓存看不出来（项目都删了，笔记还挂在搜索结果里）⚠
            deleted_at=timezone.now(),
            deleted_by=by,
            updated_at=timezone.now(),
        )
        GraphPatch.objects.filter(project=project).delete()
        Node.objects.filter(project=project).delete()
        Edge.objects.filter(project=project).delete()
    Job.objects.filter(project_ref=project_ref).delete()
    Project.objects.filter(project_ref=project_ref).delete()
    # ⚠★★ 2026-10-21（所有者裁定）：**基图是宝贵数据，只能管理员在后台删** ⚠
    #   · · ★ 本项目**绝不碰基图**（* 包括它的 Redis 映射）——
    #     * 删项目 ≠ 删基图：* 同一个基图被多个项目 / 多个版本共用，
    #     * 在这里清映射只会让下次绑定白跑一次，* 没有任何好处 ⚠
    #   · · ★★ 映射只允许在「基图行本身被管理员删掉」时清
    #     （* `graph.binding.forget_base_graph`，* 目前只由管理命令调用）✅
    return freed


def _cascade_private(project) -> int:
    """★★★ **项目转私有 ⇒ 它下面的笔记全部转私有**（* 2026-10-21）⚠

    ## ★★★ 所有者原话（逐字）

    > 「项目变为私有，那其下的笔记和图谱之类的全部内容都要变成私有的，这是一个级联，
    >   隐藏也一样。**改为公开或没有隐藏时，就不用级联修改了，笔记这些，原来是什么样，
    >   就什么样。**」

    ## ★★ 口径

    ```
    私有 / 隐藏  ⇒ ★ **单向级联**：把项目下的笔记改成私有 / 隐藏 ✅
    改回公开     ⇒ ⛔ **不回滚**：笔记保持当前状态（避免"记住原来是什么"）⚠
    ```

    ⚠★ 为什么要级联：* 笔记是**独立可查**的（详情页 / 我参与的笔记 / 将来的列表），
      * 光把项目设私有，笔记自己的 `is_public=True` 还留着 ⇒ 谁都能直接看 ⚠
    """
    from django.utils import timezone

    from core.models import Note

    n = Note.objects.filter(project=project, deleted_at__isnull=True).update(
        is_public=False,
        # ★ 必须是 `.update()` 里显式带 —— 批量更新不走 `save()` ⚠
        updated_at=timezone.now(),
    )
    return n


def _cascade_hidden(project) -> int:
    """★★★ **项目被隐藏 ⇒ 它下面的笔记也隐藏**（* 同上，单向）⚠

    · · `state=hidden` 是比私有更严的一档：* 只有作者本人看得到 ✅
    """
    from django.utils import timezone

    from core.models import Note

    return Note.objects.filter(project=project, deleted_at__isnull=True).update(
        state=Note.STATE_HIDDEN,
        updated_at=timezone.now(),
    )


def _body(request: HttpRequest) -> dict:
    """⚠ 解析失败一律返回**错误响应**而不是抛异常（契约 §12：`400 bad_json`）。"""
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _clamp(value, low: int, high: int, default: int) -> int:
    try:
        got = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(got, high))


def _built_flags(project_refs: list[str]) -> dict[str, bool]:
    """★★ 一次查询取回所有项目的「图建好了没」（❌ 不要每个项目查一次）。

    ⚠★ 2026-10-14（`B197`）：★ `Project.graph_built_at` 那一列**已删** ⚠
      ★★ 定版判据改为**派生**（★ 见 `core/models.py::is_graph_built`）⚠
      · ★ 它经 `binding.of()` 读 `BaseGraph.built_at`
      · ★★ 而那是**每个项目一次查询** ⇒ ★ 列表页会 N+1 ⚠

    ⇒ ★★ 所以这里**同一趟**把绑定与 `built_at` 都查出来 ✅

    ⚠★ 与 `_counts()` 是**两趟**查询（★ 不是一趟）——
      · ★ `_counts` 要的是**聚合**（★ 按基图分组数节点/边）
      · ★ 本函数要的是**每个项目一个布尔值**
      ★★ 合成一趟会让两边都变难读，* 而查询次数从 2 次变成 1 次
        ★ 在 200 个项目的量级上**不值得** ⚠
    """
    # ⚠★★ 2026-10-14（`B179` 第二步）：**绑定已并入项目表** ⚠
    #   ★★ 所以一趟 `select_related` 就够 —— ★ 不再经 `ProjectBaseGraph` ✅
    bound = dict(
        Project.objects.filter(project_ref__in=project_refs)
        .exclude(base_graph=None)
        .values_list("project_ref", "base_graph_id")
    )
    if not bound:
        return {}
    built_ids = set(
        BaseGraph.objects.filter(
            id__in=list(bound.values()), built_at__isnull=False
        ).values_list("id", flat=True)
    )
    return {ref: (bg_id in built_ids) for ref, bg_id in bound.items()}


def _counts(project_refs: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    """★★ 一次查询取回所有项目的节点 / 边数量（❌ 不要每个项目查一次）。

    ⚠★★ `B179`（2026-10-13）：数量**不再按 `project_ref` 数** ⚠ ——
      ★ 图数据现在挂在【**基图**】上；★ 而 `project_ref` 那些行只表示
        「★ 用户自己新增的节点」（★ 那是**另一份数据**）⚠
      ⇒ ★★ 所以先查【项目 → 基图】的绑定，★ 再按基图数 ⚠
      ★ 多个项目可能绑**同一份**基图 ⇒ ★ 它们数量相同 ——
        ★★ 而这正是 `B179` 要的：★ **同一份源码版本只解析一次** ✅
    """
    # ⚠★★ 2026-10-14（`B179` 第二步）：**绑定已并入项目表** ⚠
    binds = dict(
        Project.objects.filter(project_ref__in=project_refs)
        .exclude(base_graph=None)
        .values_list("project_ref", "base_graph_id")
    )
    bg_ids = list(binds.values())
    if not bg_ids:
        return {}, {}

    # ★★ `B220`：* 节点跨版本共用 ⇒* 不能再按 `base_graph_id` 数 ⚠
    #   · · ★ 直接用基图行上的**每版本计数**（* 写图时落的 `node_count` / `edge_count`）✅
    by_bg_nodes = dict(
        BaseGraph.objects.filter(pk__in=bg_ids).values_list("pk", "node_count")
    )
    by_bg_edges = dict(
        BaseGraph.objects.filter(pk__in=bg_ids).values_list("pk", "edge_count")
    )

    nodes = {ref: by_bg_nodes.get(bg, 0) for ref, bg in binds.items()}
    edges = {ref: by_bg_edges.get(bg, 0) for ref, bg in binds.items()}
    return nodes, edges


def _latest_parse_job(project_ref: str) -> Job | None:
    return (
        Job.objects.filter(project_ref=project_ref, kind=Job.KIND_PARSE)
        .order_by("-queued_at")
        .first()
    )


def _project_json(
    project: Project,
    request: HttpRequest,
    node_n: int,
    edge_n: int,
    *,
    # ⚠★ 2026-10-14（`B197`）：**允许调用方预载「有没有图」** ⚠
    #   ★★ 否则列表页会 **N+1**（★ 每个项目都要查一次绑定表）⚠
    #   · ★ 调用方不传 ⇒ ★ 自己查（★ 单项目视图走这条）✅
    #   · ★ 传了 ⇒ ★ 用预载值（★ 列表页走这条）✅
    graph_built: bool | None = None,
) -> dict:
    job = _latest_parse_job(project.project_ref)
    user = getattr(request, "user", None)
    return {
        "project_ref": project.project_ref,
        "name": project.name,
        "desc": project.desc,
        "is_public": project.is_public,
        # ★★ `B208`⑧：* 状态 + 最近一次处置 ⇒* owner 要知道"为什么被隐藏" ✅
        #   （* `B196`：* 作者来问"为什么"必须答得出 ⇒* 详情里直接给）⚠
        "state": project.state,
        "moderation_reason": project.moderation_reason,
        "moderated_at": project.moderated_at.isoformat() if project.moderated_at else "",
        "provider": project.provider,
        "repo_url": project.repo_url,
        "commit": "",
        # ⚠ `mine` —— 前端靠它决定是否渲染「设置 / 重新解析」入口
        "mine": bool(user and user.is_authenticated and project.owner_id == user.pk),
        # ★★ `F2`（联调摸底，2026-10-17）：**当前用户对这个项目的写权限** ⚠
        #   · ★★ 为什么必须有：* 没有它，* 前端分不清「协作者」与「外人」——
        #     · · ★ 给所有人渲染写入口 ⇒* 外人点击得 403（* 差体验）⚠
        #     · · ★ 只给 owner 渲染 ⇒* 协作者被藏掉入口（* 更错 ——* 他们有权）⚠
        #   · ★★ 判据走内核（* `core/access.can_edit_project`，* `B209` 收束）✅
        "can_edit": access.can_edit_project(user, project),
        # ★★ `F4` 预留：* 能不能管理协作者（* owner/staff）——* 协作者管理页入口显隐 ⚠
        "can_manage": access.can_manage_members(user, project),
        "owner": project.owner.get_username() if project.owner_id else "",
        "status": job.state if job else "none",
        "progress": job.progress if job else 0,
        # ★★★ `B169` 新增：**是否已定版** —— 前端靠它决定「拉取代码」按钮的显隐：
        #   ★ 已定版（★ 代码已拉下**且**解析完成）⇒ 不给按钮（点了必然 409）
        #   ★ 未定版（含**拉取失败 / 解析失败**）⇒ **给按钮**（★ 所有者裁定：失败还允许再发起）
        # ⚠★ 为什么不用 `status` 判断：★ `status` 是**作业状态**（`Job.state`），
        #   ⚠ 而"定版"是 **`Project.is_graph_built`** —— ★ 两者不是一回事
        #   （★ 作业可能 `done` 但图未定版，⚠ 反之亦然）⇒ ★★ **必须单独给一个字段**。
        "graph_built": (
            # ⚠★ `B197`：定版判据已改为派生（★ 经绑定表读 `BaseGraph.built_at`）⚠
            bool(project.is_graph_built) if graph_built is None else bool(graph_built)
        ),
        "graph_rev": graph_rev_of(project.project_ref),
        "node_count": node_n,
        "edge_count": edge_n,
        "created_at": project.created_at.isoformat(),
        # ★★ `updated_at`（* 所有者：「项目也加上updated_at 字段，具体改了项目的
        #   什么，就更新时间」）——* Redis 搜索缓存靠它判断数据是否改过 ⚠
        "updated_at": project.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# /api/projects/
# ---------------------------------------------------------------------------

@require_http_methods(["GET", "POST"])
def collection(request: HttpRequest) -> JsonResponse:
    """`GET` 列表 / `POST` 新建。"""
    if request.method == "POST":
        return _create(request)

    user = getattr(request, "user", None)
    authed = bool(user and user.is_authenticated)
    qs = Project.objects.all()

    if request.GET.get("mine") == "1":
        # ★★★ `B172`：**我的工作区** —— ★★ 只给【自己的项目】。
        #
        # ⚠★ 改之前的口径是：★ 游客 ⇒ 公开 · ★ 登录 ⇒ 公开 + 自己的 · ★ staff ⇒ **完全不过滤** ⚠
        #   ⇒ ★★ 后果：★ 工作区里**混着别人的公开项目**（★ 实测：那 15 张卡片全是 `smoke_*` 的），
        #      ★ 而 staff（所有者）看到的是**全部 84 个** ⚠
        #   ★★ 用户原话：「**用户的项目工作区只显示他的项目，不要把所有人的项目都显示了**」
        #
        # ⚠★ **staff 也照样按 `owner` 过滤** —— ★ 否则"我的工作区"对他就不成立 ⚠
        # ★ 未登录 ⇒ **空列表**（❌ 不是 401）—— ★ 工作区对游客开放，★ 只是"他还没有项目" ✅
        # ★★ 而「别人的公开项目」去哪看：★ **`Home`（首页探索页）** ——
        #    ★ 它调的是**不带 `mine` 的**同一个端点 ⇒ ★★ 两个页面从此用**不同参数** ✅
        if not authed:
            return ok_flat(projects=[])
        qs = qs.filter(owner=user)
    elif not authed:
        # ★ 游客只看公开项目（否则登录与否就没区别了）
        # ★★ `B208`⑧：* 且只要 `active` ——* **被隐藏的**项目不列 ✅
        qs = qs.filter(is_public=True, state=Project.STATE_ACTIVE)
    else:
        # ★★ `B208`①：* **去掉 staff 的"完全不过滤"分支** ⚠
        #   （* 原口径：* staff 在列表里能看到**所有**项目，* 含别人的私有项目；
        #     * 管理员没有额外读权限 ⇒* 他与普通登录用户看到的一样）⚠
        # ★★ `B208`⑧：* 隐藏项目只有 **owner** 能在列表里看到 ✅
        from django.db.models import Q

        qs = qs.filter(
            Q(is_public=True, state=Project.STATE_ACTIVE) | Q(owner=user)
        )

    # ★★ `?q=` 关键词（* 名称 / 简介 / 作者名）⇒ 命中 pg_trgm 表达式索引 ⚠
    kw = (request.GET.get("q") or "").strip()
    if kw:
        from django.db.models import Q

        # ★★★ 首页搜索**只搜公开项目**（* 所有者：「不要让私有项目或者笔记能被搜索，
        #   不管对哪个用户都一样」）⚠
        #   · · `mine=1` 那条路（工作区）不受影响 —— 那本来就是"我的项目"
        if request.GET.get("mine") != "1":
            qs = qs.filter(is_public=True, state=Project.STATE_ACTIVE)

        qs = qs.filter(
            Q(name__icontains=kw)
            | Q(desc__icontains=kw)
            | Q(owner__username__icontains=kw)
        )

    qs = qs.order_by("-created_at")[:200]
    projects = list(qs)

    # ★★ 带关键词 ⇒ 走 Redis 缓存（* 结果含 per-user 字段 ⇒ key 带 uid）⚠
    me = getattr(request, "user", None)
    uid = getattr(me, "pk", 0) or 0
    if kw:
        cached = search_cache.get(search_cache.NS_PROJECTS, uid, kw)
        if cached is not None:
            # ★★ 发出前核对数据库（* 项目被删 / 改名 / 换作者都要发现）⚠
            checked = _verify_project_cache(cached)
            if checked is not None:
                return ok_flat(projects=checked)

    nodes, edges = _counts([p.project_ref for p in projects])
    # ⚠★ 2026-10-14（`B197`）：**同一趟把「有没有图」也查出来** ⚠
    #   ★★ 否则 `is_graph_built` 会对每个项目各查一次绑定表 ⇒ **N+1** ⚠
    built = _built_flags([p.project_ref for p in projects])

    # ② 型（契约 §2：项目列表 = `{projects:[...]}`）
    payload = [
        _project_json(
            p,
            request,
            nodes.get(p.project_ref, 0),
            edges.get(p.project_ref, 0),
            graph_built=built.get(p.project_ref, False),
        )
        for p in projects
    ]

    if kw:
        search_cache.put(search_cache.NS_PROJECTS, uid, kw, payload)

    return ok_flat(projects=payload)


def _verify_project_cache(cached: list):
    """★★ **核对缓存里的项目是否还对得上**（* 2026-10-21）⚠

    Returns:
        - `None` ⇒ 有项目被删 / 被改 ⇒ 调用方重新全查并重写缓存
        - `list` ⇒ 全部核对无误，* 可以直接发

    ⚠★ 比什么：**行还在吗** + **名称 / 简介 / 作者 / 公开性 / 状态**变了吗
      （* `_project_json` 没有 updated_at，* 所以按这些业务字段逐项比）⚠
    """
    if not cached:
        return []

    refs = [it["project_ref"] for it in cached if it.get("project_ref")]
    rows = Project.objects.filter(project_ref__in=refs).values(
        "project_ref",
        "name",
        "desc",
        "state",
        "is_public",
        # ⚠★ 2026-10-21：**不查 owner** —— 项目创建后 owner 不可变
        #   （* 所有者：「项目缓存比作者也去掉，同事检查网站前后端有没有改作者的代码，
        #     有就去掉。作者只能后台，我这个管理员改。」）
        #   ⇒ 省掉一次 `auth_user` JOIN ✅
        # ★★ `updated_at` 是主判据（* 所有者：「redis 也可以根据更新时间确定
        #   数据是否改过没了」）——* 任何写路径都会刷新它 ⚠
        "updated_at",
    )
    by_ref = {r["project_ref"]: r for r in rows}

    for it in cached:
        r = by_ref.get(it.get("project_ref"))
        if r is None:
            return None
        # ★★ **唯一判据：`updated_at`**（* 2026-10-21 实测确认足够）
        #   · · 实测（core_project 的写路径）：
        #     · 改名 / 改简介 / 改公开性 ⇒ 走 `Project.save()` ⇒ 刷新 ✅
        #     · 管理员隐藏 / 恢复       ⇒ 同上（* 模型层 `save()` 补了 updated_at）✅
        #     · 换绑基图               ⇒ `.update(..., updated_at=now())` ✅
        #   · · ⛔ 原「老缓存没有 updated_at 时按业务字段比」的兜底已删 ——
        #     * `_project_json` 现在必带 `updated_at` ⇒ 那个分支**永远不执行**；
        #     * 万一读到老缓存（无该字段），这里会直接判为不一致 ⇒ 重查重写 ✅
        if r["updated_at"].isoformat() != it.get("updated_at"):
            return None
    return cached


def _create(request: HttpRequest) -> JsonResponse:
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return fail("请先登录", 401, code="unauthenticated")

    body = _body(request)
    name = str(body.get("name") or "").strip()
    repo_url = str(body.get("repo_url") or "").strip()
    provider = str(body.get("provider") or "").strip().lower()
    commit = str(body.get("commit") or "").strip()

    if not name:
        return fail("缺少项目名称", 400, code="missing_fields")
    if not repo_url:
        return fail("缺少仓库地址", 400, code="missing_fields")
    # ★ B109：源码只能服务端拉取 ⇒ **必须**指明托管平台
    # ⚠★ 2026-10-14（`B197`）：**`Project.PROVIDER_CHOICES` 已随列删除** ⚠
    #   ★★ 所以这里改用**模块级常量**（★ `BaseGraph._HOSTS` 就是同一组键）⚠
    #   · ★ 而它俩必须**一致** —— ★ 否则这里放行、* 那边却拼不出地址 ⚠
    if provider not in {"github", "gitee"}:
        return fail("provider 必须是 github 或 gitee", 400, code="invalid_provider")

    # ⚠★★ 2026-10-17 修：`provider` / `repo_url` / `commit` 已随 `B197` 删列
    #   （现在是**派生于基图**的只读属性）⇒ 再传就 `AttributeError` ⇒ 500 ⚠
    #   · ★ 图与仓库的绑定走 `publish/start/`（会投解析作业）；本端点只建空项目壳 ✅
    project = Project.objects.create(
        name=name[:200],
        desc=str(body.get("desc") or "")[:2000],
        owner=user,
        is_public=bool(body.get("is_public", False)),
    )
    search_cache.invalidate(search_cache.NS_PROJECTS)
    return ok(
        {"project_ref": project.project_ref, "name": project.name},
        status=201,
    )


# ---------------------------------------------------------------------------
# /api/projects/<project_ref>/
# ---------------------------------------------------------------------------

@require_http_methods(["GET", "PATCH", "DELETE"])
def detail(request: HttpRequest, project_ref: str) -> JsonResponse:
    project = permissions.get_project(request, project_ref)
    # ★ 越权与不存在**一律 404**（契约 §5 / §19.3）
    if project is None or not permissions.can_view(request, project):
        return fail(permissions.NOT_FOUND, 404)

    if request.method == "GET":
        nodes, edges = _counts([project_ref])
        return ok(_project_json(project, request, nodes.get(project_ref, 0), edges.get(project_ref, 0)))

    if request.method == "DELETE":
        # ★★ `B207`②：**删项目单开一道判据** ——* 协作者**不能**删项目 ⚠
        #   （* 所有者原话整句：「协作者不能删项目。」）✅
        #   · ★ 而 PATCH（* 改名 / 改描述 / 改公开性）仍走 `can_edit` ✅
        if not permissions.can_delete(request, project):
            return fail("只有项目所有者能删除项目", 403, code="forbidden")
        freed = purge_project(project_ref, by=permissions.current_user(request))
        return ok({"deleted": True, "storage_freed_bytes": freed})

    # PATCH —— ★ 改内容 ⇒ `can_edit`（owner ∨ 协作者，`B207`②；⚠ staff 已切，`B208`①）✅
    if not permissions.can_edit(request, project):
        return fail("需要项目所有者权限", 403, code="forbidden")

    body = _body(request)
    # ⚠★★ 2026-10-14（`B197`）：**`repo_url` / `commit` / `provider` 三项【已删】** ⚠
    #   ★★ 它们与基图重复 ⇒ ★ 只留基图那份（★ 所有者裁定）⚠
    #   · ★ `repo_url` / `provider` ⇒ ★ 现在从 `base_graph` **派生**（★ 只读属性）⚠
    #   · ★★ 所以这里**不再收这三个字段** —— ★ 收也写不进去
    #     （★ 没有 setter ⇒ `AttributeError`）⚠
    #   · ★ 要改源码地址 ⇒ ★ 重新拉一份（★ 那是建一条新绑定，★ 不是改这一行）✅
    dirty: list[str] = []
    for field in ("name", "desc"):
        if field in body:
            v = str(body[field] or "")[:2000]
            if getattr(project, field) != v:
                setattr(project, field, v)
                dirty.append(field)
    cascaded = 0
    if "is_public" in body and project.is_public != bool(body["is_public"]):
        was_public = project.is_public
        project.is_public = bool(body["is_public"])
        dirty.append("is_public")
        # ★★★ 公开 → 私有：**级联**把项目下的笔记也转私有（⛔ 反向不级联）⚠
        if was_public and not project.is_public:
            cascaded = _cascade_private(project)

    # ★★ 只有**真的改了**才 save ⇒ `Project.save()` 会自动补上 `updated_at`；
    #   · · 什么都没改就不要戳时间（* 所有者：「具体改了项目的什么，就更新时间」）⚠
    if dirty:
        project.save(update_fields=dirty)
        # ★★★ 2026-10-21 补：**项目改名 / 改公开性 ⇒ 两个缓存都要清** ⚠
        #   · · 改公开性：* 私有 ⇒ 公开后，项目里的公开笔记**立刻可搜**；
        #     而搜索缓存里的"空结果"没有条目可校验 ⇒ ⛔ 不清就搜不到 ⚠
        #   · · 改名：* 笔记搜索结果里带着 `project_name` 快照 ⇒ 也要清 ✅
        search_cache.invalidate_all()
    nodes, edges = _counts([project_ref])
    return ok(_project_json(project, request, nodes.get(project_ref, 0), edges.get(project_ref, 0)))


# ---------------------------------------------------------------------------
# /api/projects/<project_ref>/fetch/   ★ 拉取代码（`B169` 确立；★ `B176` ① 改为【一步】）
# ---------------------------------------------------------------------------

@require_http_methods(["POST"])
def start_fetch(request: HttpRequest, project_ref: str) -> JsonResponse:
    """★★★ **开始拉取代码**（★ `B176` ① 之后：**不再需要任何第三方授权**）。

    ## ★★ 它现在做什么
    ★ 校验通过之后 ★ **直接投递一个 `parse` 作业** ✅ —— ★ 作业会自己
      ★ 从 `repo_url` 拉源码 → ★ 核验许可 → ★ 解析 → ★ 写图 → ★ **然后立刻删掉源码**（`B176` ②）⚠

    ## ★★★ `B176` ① 之前它是什么样（★ 这段必须留住，否则"绕两步"会被重新发明）
    ★ 以前这里**只负责"发起授权"**：★ 返回一个授权 URL ⇒
      ⚠ 用户**整页跳走** ⇒ ★ 回到 OAuth 回调里**才真正开始拉取** ⚠
    ★★ 之所以要那么绕，只有一个原因：★ 平台要拿 `access_token` 去
      **当场校验"这库是不是你的"** ⚠
    ★★★ **所有者裁定**（原话）：「**我以前说用 github 验证库是不是属于本人，
      我觉得不行，删掉这个，有风险。现在改为，只拉下来解析，解析之后就删掉**」
    ⇒ ★ **归属校验退役** ⇒ ★★ 于是「拉取」变成**一步**：★ **点一下就开始**，
      ★ ❌ 不跳转、❌ 不授权 ✅

    ## ★★★ 它**不允许任何形式的「重投」**（★ `B169` 立的规矩）
    ★ `B169` 之前这里是 `parse/`，带着一个 **「补投」** 语义 ⚠
    ⚠★ **「补投」不是所有者要的** —— ★ `B155` 里他给的出路是「**删了项目重新建一个**」⚠
    ⇒ ★★ **要么从头发起一次拉取，要么拒绝。**

    ## ★ 闸门（★ 所有者裁定 · `B169`）
    | 项目状态 | 行为 |
    |---|---|
    | ★ **未定版**（拉取失败 / 解析失败 / 还没跑过） | ✅ **允许再发起** |
    | ★★ **已定版**（★ 代码已拉下**且**解析完成） | ★★ **409** + 引导语 |

    ⚠★ 判据是 **`Project.is_graph_built`**（❌ 不是作业状态）—— ★ 见 `_project_json` 的说明。
    """
    project = permissions.get_project(request, project_ref)
    if project is None or not permissions.can_view(request, project):
        return fail(permissions.NOT_FOUND, 404)
    if not permissions.can_edit(request, project):
        return fail("需要项目所有者权限", 403, code="forbidden")

    # ★★★ **定版闸门**（`B103` / `B155` / `B169`）—— ⚠★ 注意：**这里没有「补投」这条路**
    if project.is_graph_built:
        return fail(
            "这个项目已经拉取并解析过了，图不会重新生成。"
            "★ 需要另一个版本请【新建一个项目】；★ 想重来请【删掉本项目后重建】。",
            409,
            code="graph_immutable",
        )

    if not project.repo_url:
        return fail("项目还没有设置仓库地址", 400, code="missing_repo")

    provider = (project.provider or "").strip().lower()
    if provider not in oauth.PROVIDERS:
        return fail("项目的托管平台必须是 github 或 gitee", 400, code="invalid_provider")

    # ★★ 从 `repo_url` 反推 `owner/repo` —— ⚠ 反推不出来 ⇒ **作业就不知道该拉哪个库** ⇒ 早失败
    #   ★（`B176` ① 之前这一步的理由是"归属校验连问都问不了"；★ 现在理由变了，
    #     ★★ 但**它依然必要** —— ★ 见 `core/fetch.py::fetch_archive()`）✅
    repo = fetch.repo_full_from_url(project.repo_url)
    if repo.count("/") != 1 or any(seg in ("", ".", "..") for seg in repo.split("/")):
        return fail(
            "项目的仓库地址无法识别（应为 owner/repo 形式），请先在项目设置里改正。",
            400,
            code="bad_repo",
        )

    # ⚠★★ 2026-10-14（`B184`）：**不再收 `source_path`** ⚠

    # ★★★ `B176` ①：**直接投递作业** —— ★★ 与 `publish_project()` /
    #   `approve_and_resume()` **共用同一处投递逻辑** ⚠
    #   （⚠★ payload 只在那里构造一份 —— ❌ 绝不在本视图里再写一遍）
    #
    # ⚠★★ `B179`：它现在会**先问一句"有没有现成的基图"** ⚠
    #   ★★ 所有者原话：「**拉去之前，看看现有的图数据里有没有同样的，
    #     有同样的，就直接返回，不拉取，不解析，还快**」
    #   ⇒ ★★ 所以返回值**有三种结局**（`DispatchOutcome`）：
    #     · ★ 投出去了 ⇒ 有 `job_id`，前端照旧轮询进度
    #     · ★★ **复用了** ⇒ **没有 `job_id`**，但这是**成功** ⇒ 另一种文案 ⚠
    #     · ★ 失败 ⇒ 如实报原因（私有 / 限流 / 分支不存在）
    out = publish_core.dispatch_parse(
        project, commit="", priority=0,
        # ⚠★★ `B182`：**前端已经算好的 commit sha** ⚠
        #   ★★ 所有者原话：「**这个过程应该发生在前端，不是用我服务器的IP地址查询的，
        #     只有拉源码，才是我服务器做的吧？**」
        #   · ★ 有它 ⇒ ★★ 服务端【一次 GitHub API 都不发】✅
        #   · ★ 没有 ⇒ ★ 服务端自己解析（★ 兜底）✅
        #   ⚠★ 这里用 `_body(request)`（★ 本视图没有 `body` 变量）——
        #     ★★ 而它【不抛坏 JSON】（★ 与 `source_path` 同一口径）✅
        sha=str(_body(request).get("sha") or ""),
    )

    if out.failed:
        # ★★ 解析不出 sha ⇒ ★★ **把真实原因给用户** ⚠
        #   ★ 以前这里一律"投递失败"—— ★ 而真实原因常常是**传了私有仓库** ⚠
        #     （★ 所有者原话：「**没有公开的仓库，去拉他干什么？……直接拒了他**」）
        return fail(
            out.fail_message or "拉取失败，请稍后再试。", 400, code=out.fail_code or "dispatch_failed"
        )

    if out.reused:
        # ★★★ **这个版本已经有人解析过了** ⇒ ★★ 不拉取、不解析，直接就能看 ⚠
        #   ⚠★ **刻意不给 `job_id`** —— ★ 真的没有作业（★ 给了前端就会去轮询一个不存在的东西）⚠
        return ok(
            {
                "project_ref": project.project_ref,
                "job_id": None,
                "job_state": "reused",
                "created": False,
                "reused": True,
                "sha": out.reused_sha,
                "repo": repo,
                "message": "这个仓库的同一个版本已经解析过了，直接就能看，不用再拉一次。",
            }
        )

    if out.job is None:
        # ★ 入队失败已在 `jobs/dispatch.py` 留痕，★ 这里只负责**如实上报**
        return fail("投递作业失败，请稍后再试。", 500, code="dispatch_failed")

    return ok(
        {
            "project_ref": project.project_ref,
            "job_id": out.job.pk,
            "job_state": out.job.state,
            "created": out.created,
            # ★★ `B179`：把 sha 回给前端（★ 前端可显示"对应 commit ea42736…"）✅
            "sha": out.job.payload.get("sha", ""),
            "repo": repo,
        }
    )


# ---------------------------------------------------------------------------
# /api/projects/<project_ref>/progress/
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
def progress(request: HttpRequest, project_ref: str) -> JsonResponse:
    """解析进度 —— ★ 供上传弹窗与项目主页轮询。"""
    project = permissions.get_project(request, project_ref)
    if project is None or not permissions.can_view(request, project):
        return fail(permissions.NOT_FOUND, 404)

    job = _latest_parse_job(project_ref)
    if job is None:
        return ok({"status": "none", "progress": 0, "stage": "", "job_id": None})

    return ok(
        {
            "status": job.state,
            "progress": job.progress,
            "stage": job.stage,
            "job_id": job.pk,
            "queue_position": dispatch.queue_position(job),
            # ⚠ 只有本人 / 管理员才看得到错误详情
            "error": job.error_msg
            if (permissions.can_edit(request, project) and job.error_msg)
            else "",
            "graph_rev": graph_rev_of(project_ref),
        }
    )
