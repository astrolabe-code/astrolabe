"""Astrolabe · ① Web 层：图谱读接口

★ 契约：`frontend-contract.md` §2 的图谱行 + §6（`graph/edges/` 实现约束）。

★★ **一个新增端点（新设计的核心能力）**：`…/graph/neighbors/`

| 端点 | 说明 |
|---|---|
| `GET …/graph/summary/` | 概览（② 型） |
| `GET …/graph/nodes/` | 节点列表（② 型） |
| `GET …/graph/nodes/<vid>/` | 节点详情（② 型）★ **用 vid，不是 uid** |
| `GET …/graph/edges/` | 边（① 型） |
| ★ `GET …/graph/neighbors/` | ★★ **多跳邻域**（① 型）—— 本平台的立身之本 |
| `GET …/graph-rev/` | 图版本（② 型） |

⚠ **有意偏离契约的 3 处**（都记进决策日志）：

| # | 偏离 | 原因 |
|---|---|---|
| **1** | ★ 节点详情用 **`vid`**，不是 `uid` | `B117`：`uid` **允许重复** ⇒ 用它定位会**挂错节点** |
| **2** | `edges` 的 `level` / `dangling` 参数**忽略** | 我们还没有这两个概念（依赖 ③ 计算层与前置解析） |
| **3** | `edges` 的 `file=` 按 **`file_path` 前缀** | ⚠ 契约原文是「`from_uid`/`to_uid` 前缀」；我们的边两端是**主键**，按文件的路径前缀更直接 |
"""

from __future__ import annotations

from django.db.models import Count, Q
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from graph import kinds, scope
from graph.models import Edge, GraphPatch, Node
from graph.revision import current as graph_rev_of
from graph.traversal import DIRECTION_OUT, neighborhood
from jobs.models import Job
from web import permissions
from web.http import fail, ok, ok_flat
from web.serializers import count_by, edge_json, node_json, patch_json, subgraph_json

NODES_PAGE_MAX = 500        # 契约 §2：`limit=≤500`
EDGES_PAGE_DEFAULT = 500    # 契约 §6：默认 500
EDGES_PAGE_MAX = 5000       # 契约 §6：钳制上限
FILE_PREFIX_MAX = 200       # 契约 §6：前缀长度截断 200


def _clamp(value, low: int, high: int, default: int) -> int:
    try:
        got = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(got, high))


def _viewable(request: HttpRequest, project_ref: str):
    """取项目并校验可读 —— ★ 不可读**一律 404**（与"不存在"不可区分）。"""
    project = permissions.get_project(request, project_ref)
    if project is None or not permissions.can_view(request, project):
        return None
    return project


def _latest_parse_job(project_ref: str) -> Job | None:
    return (
        Job.objects.filter(project_ref=project_ref, kind=Job.KIND_PARSE)
        .order_by("-queued_at")
        .first()
    )


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
def summary(request: HttpRequest, project_ref: str) -> JsonResponse:
    """`GET …/graph/summary/` —— ② 型 `{ok, parse{…}, counts{…}}`。

    ⚠ 契约里的 `analysis(stats)` / `lang_breakdown` **暂不发** ——
      它们依赖 ③ 计算层；按 §16.3「**key 缺失 = 服务端版本低**」由前端降级处理。
    """
    if _viewable(request, project_ref) is None:
        return fail(permissions.NOT_FOUND, 404)

    # ★★★ `B179`：读的是**这个项目绑定的那份【基图】** ⚠
    #   （★ 不再是 `project_ref` 等于它的那些行 —— ★ 那现在只表示"用户自己新增的"）⚠
    #   ★★ 见 `graph/scope.py`：这个判断**只在那里决定一次** ✅
    node_qs = scope.readable_nodes_of(project_ref)
    edge_qs = scope.readable_edges_of(project_ref)
    job = _latest_parse_job(project_ref)

    return ok_flat(
        parse={
            "status": job.state if job else "none",
            "graph_rev": graph_rev_of(project_ref),
            "langs": sorted(
                {lang for lang in node_qs.values_list("lang", flat=True).distinct() if lang}
            ),
        },
        counts={
            "nodes": node_qs.count(),
            "edges": edge_qs.count(),
            # ⚠ 一律用 "pk"（★ 不依赖主键字段名：Node 的是 node_id，Edge 的是 id）
            # ★★ `B222`：* 列里是 id ⇒* 输出前换成名字 ⚠
            "by_kind": {
                kinds.kind_name(int(k)): int(v)
                for k, v in node_qs.values_list("kind").annotate(n=Count("pk"))
            },
            "by_type": count_by(edge_qs.values_list("type").annotate(n=Count("pk"))),
            "by_lang": count_by(node_qs.values_list("lang").annotate(n=Count("pk"))),
        },
    )


# ---------------------------------------------------------------------------
# 节点列表
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
def nodes(request: HttpRequest, project_ref: str) -> JsonResponse:
    """`GET …/graph/nodes/?kind=&q=&file=&lang=&limit=&offset=` —— ② 型。

    ★ 用途：画布种子 + 列表模式 + 分析清单。
    """
    if _viewable(request, project_ref) is None:
        return fail(permissions.NOT_FOUND, 404)

    # ★★ `B179`：发的是**基图那一份** —— ⚠ 用户修改是**另一个端点**发的
    #   ★（`B180` 定的：★ **服务端不做整合**，★ 由前端合并）⚠
    qs = scope.readable_nodes_of(project_ref)

    kind = (request.GET.get("kind") or "").strip()
    if kind:
        # ★★ `B222`：* 列里是 smallint，* 查询参数是名字 ⇒* 先映射（* 未登记 ⇒ 空集）⚠
        qs = qs.filter(kind=kinds.kind_id(kind))

    lang = (request.GET.get("lang") or "").strip()
    if lang:
        qs = qs.filter(lang=lang)

    file_path = (request.GET.get("file") or "").strip()[:FILE_PREFIX_MAX]
    if file_path:
        qs = qs.filter(file_path__startswith=file_path)

    query = (request.GET.get("q") or "").strip()
    if query:
        # ★ 名字 / 人类可读标签 双路匹配（⚠ 尽量走索引前缀）
        qs = qs.filter(Q(name__icontains=query) | Q(uid__icontains=query))

    # ⚠★ `B179`：`origin` **不再是一列**（★ 基图行必然是 `parsed`）⚠
    #   ★★ 用户自己新增的节点在**另一个端点**（★ 那才带 `manual`）⚠
    #   ⇒ ★ 要 `manual` ⇒ **如实返回空集**（❌ 不是忽略参数、❌ 也不是给全部）⚠
        #
    # ⚠★★ 2026-10-15（`B186`）：但那句只对【绑了基图】的项目成立 ⚠
    #   · ★ 绑了基图 ⇒ ★ 修改层在另一个端点 ⇒ ★ `manual` 给**空集** ✅
    #   · ★★ 没绑基图（笔记型）⇒ ★★ **这个项目的全部节点都是 `manual`** ⚠
    #     · ★ `origin=manual` ⇒ ★ 如实返回它们 ✅
    #     · ★ `origin=parsed` ⇒ ★★ 如实返回空集 ✅
    #     （★ 两种都不猜、都不忽略参数 ✅）
    origin = (request.GET.get("origin") or "").strip()
    manual_only = scope.is_manual_only(project_ref)
    if origin == "manual":
        if not manual_only:
                qs = qs.none()
    elif origin == "parsed":
        if manual_only:
                qs = qs.none()

    limit = _clamp(request.GET.get("limit"), 1, NODES_PAGE_MAX, 200)
    offset = _clamp(request.GET.get("offset"), 0, 10**9, 0)

    total = qs.count()
    # ★★ `B179`：基图**只查一次**，再交给序列化器 ——
    #   ⚠★★ 否则每个节点都会去查一次库（**N+1**）★ 一页几百个节点会慢一个量级 ⚠
    bg = scope.base_graph_of(project_ref)
    # ★ 固定排序（保证分页稳定）—— ❌ 不要用未排序的切片
    items = [
        node_json(n, base_graph=bg)
        for n in qs.order_by("node_id")[offset : offset + limit]
    ]

    return ok_flat(total=total, limit=limit, offset=offset, items=items)


# ---------------------------------------------------------------------------
# 节点详情
# ---------------------------------------------------------------------------

CALLERS_MAX = 200   # 契约 §2
CALLEES_MAX = 200


@require_http_methods(["GET"])
def node_detail(request: HttpRequest, project_ref: str, vid: int) -> JsonResponse:
    """`GET …/graph/nodes/<vid>/` —— ② 型。

    ⚠ 契约原文是 `<path:uid>`；★ 我们改成 **`<int:vid>`**（`B117`：uid 允许重复）。
    ⚠ `parent` / `members` **不发**（我们没有这些概念）—— 前端按 §16.3 降级。
    """
    if _viewable(request, project_ref) is None:
        return fail(permissions.NOT_FOUND, 404)

    # ★★ `B219`：* 路径里的 `vid` 现在是 **stable_vid** ⚠
    node = scope.readable_nodes_of(project_ref).filter(stable_vid=vid).first()
    if node is None:
        return fail("节点不存在", 404)

    # ⚠ 边的 from/to 仍是**内部主键** ⇒ 先换成 pk 再查 ✅
    node_pk = node.node_id
    base_edges = scope.readable_edges_of(project_ref)
    out_qs = base_edges.filter(from_node_id=node_pk)
    in_qs = base_edges.filter(to_node_id=node_pk)

    callees = list(out_qs.select_related("to_node").order_by("type", "to_node_id")[:CALLEES_MAX])
    callers = list(in_qs.select_related("from_node").order_by("type", "from_node_id")[:CALLERS_MAX])

    return ok_flat(
        node=node_json(node, base_graph=scope.base_graph_of(project_ref)),
        callees=[_brief(e.to_node, e) for e in callees],
        callers=[_brief(e.from_node, e) for e in callers],
        callee_count=out_qs.count(),
        caller_count=in_qs.count(),
    )


def _brief(other: Node, edge: Edge) -> dict:
    """邻居的**精简**表示（节点详情里的 callers / callees 用）。

    ⚠ 只给"够点一下跳过去"的字段 —— 完整字段走节点详情，❌ 不要在这里塞全集。
    """
    return {
        "vid": other.stable_vid,
        "uid": other.uid,
        "kind": kinds.kind_name(other.kind),
        "name": other.name,
        "file_path": other.file_path,
        "line": other.line,
        "type": edge.type,
        "line_at": edge.line,
    }


# ---------------------------------------------------------------------------
# 边
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
def edges(request: HttpRequest, project_ref: str) -> JsonResponse:
    """`GET …/graph/edges/` —— ★ ① 型 `{ok:true,data:{total,limit,offset,items}}`（契约 §6）。

    ⚠ 契约 §6 里还有 `level` / `dangling` 两个过滤参数 —— 我们**还没有这两个概念**，
      ⇒ **忽略它们**（❌ 不报错，前端传了也不影响）。
    """
    if _viewable(request, project_ref) is None:
        return fail(permissions.NOT_FOUND, 404)

    qs = scope.readable_edges_of(project_ref)

    types = [t.strip() for t in (request.GET.get("type") or "").split(",") if t.strip()][:10]
    if types:
        qs = qs.filter(type__in=types)

    # ⚠★ `B179`：`origin` **不再是一列**（★ 基图行必然是 `parsed`）⚠
    #   ★★ 用户自己加的边在**另一个端点**（★ 那才带 `manual`）⚠
    #   ⇒ ★ 要 `manual` ⇒ **如实返回空集**（❌ 不是忽略参数、❌ 也不是给全部）⚠
        #
    # ⚠★★ 2026-10-15（`B186`）：但那句只对【绑了基图】的项目成立 ⚠
    #   · ★ 绑了基图 ⇒ ★ 修改层在另一个端点 ⇒ ★ `manual` 给**空集** ✅
    #   · ★★ 没绑基图（笔记型）⇒ ★★ **这个项目的全部节点都是 `manual`** ⚠
    #     · ★ `origin=manual` ⇒ ★ 如实返回它们 ✅
    #     · ★ `origin=parsed` ⇒ ★★ 如实返回空集 ✅
    #     （★ 两种都不猜、都不忽略参数 ✅）
    origin = (request.GET.get("origin") or "").strip()
    manual_only = scope.is_manual_only(project_ref)
    if origin == "manual":
        if not manual_only:
                qs = qs.none()
    elif origin == "parsed":
        if manual_only:
                qs = qs.none()

    file_path = (request.GET.get("file") or "").strip()[:FILE_PREFIX_MAX]
    if file_path:
        # ★ 支撑「点开文件再取符号级边展开」——❌ 不要为一个文件拉全量边
        qs = qs.filter(
            Q(from_node__file_path__startswith=file_path)
            | Q(to_node__file_path__startswith=file_path)
        )

    limit = _clamp(request.GET.get("limit"), 1, EDGES_PAGE_MAX, EDGES_PAGE_DEFAULT)
    offset = _clamp(request.GET.get("offset"), 0, 10**9, 0)

    total = qs.count()
    # ★ 固定排序 `type, from, to`（契约 §6）—— 保证分页稳定
    # ★★ `B219`：* 边的 from/to 要发 stable_vid ⇒* 必须带出两端节点（* 否则 N+1）⚠
    page = qs.select_related("from_node", "to_node").order_by(
        "type", "from_node_id", "to_node_id"
    )[offset : offset + limit]
    items = [edge_json(e) for e in page]

    return ok({"total": total, "limit": limit, "offset": offset, "items": items})


# ---------------------------------------------------------------------------
# ★★★ 修改（**第二份数据** —— `B179` / `B180`）
# ---------------------------------------------------------------------------

PATCHES_PAGE_MAX = 10000


@require_http_methods(["GET"])
def patches(request: HttpRequest, project_ref: str) -> JsonResponse:
    """★★ `GET …/graph/patches/` —— ★★ **【第二份数据】：用户对基图的修改** ⚠

    ★★★ 所有者原话（逐字）：

    > 「**基图与用户修改存在不同模型里，请求时，直接请求这两份数据，
    > 前端负责整合**，这就要求节点索引一定要设计好，能迅速对比出修改的部分，
    > **不是在服务器上整合了，再发出去**哦。」

    ## ★★ 本端点**只发修改**（★ 这是刻意的）

    ```
    ❌ 它【不碰】基图那份数据（★ 那份由 …/graph/nodes/ 与 …/graph/edges/ 发）
    ❌ 它【不做】任何合并 —— ★★ 合并是【前端】的事 ⚠
    ✅ 它只把"改了什么"如实列出来，★ 每条带【目标 vid】⚠
    ```

    ⇒ ★★ 前端拿每条的 `target_vid` 去基图那份里**一比** ——
      ★ 哪个节点被改过 / 删过，**一比就知道** ✅
      （★ 比对靠 `(project_ref, target_node)` 那个索引 —— ★ 见 `GraphPatch.Meta.indexes`）

    ## ⚠★ 一份数据要用同一个 `rev`

    ★ 返回值里的 `graph_rev` 与基图那份**是同一个值** ——
      ★★ 前端据此判断"我手上的两份是不是**同一代**" ⚠
      （⚠ 否则会出现"修改来自新版、基图还是旧版"的错配 —— ★ 而那是**静默**的）
    """
    project = _viewable(request, project_ref)
    if project is None:
        return fail(permissions.NOT_FOUND, 404)

    # ★★ `B221`：* 补丁按 `project` 外键取（* 裸 `project_ref` 列已删）⚠
    qs = GraphPatch.objects.filter(project=project).select_related(
        "target_node", "from_node", "to_node", "created_by"
    )

    limit = _clamp(request.GET.get("limit"), 1, PATCHES_PAGE_MAX, 200)
    offset = _clamp(request.GET.get("offset"), 0, 10**9, 0)

    total = qs.count()
    items = [patch_json(p) for p in qs.order_by("pk")[offset : offset + limit]]

    return ok(
        {
            "graph_rev": graph_rev_of(project_ref),
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }
    )


# ---------------------------------------------------------------------------
# ★★ 多跳邻域（新设计的核心能力）
# ---------------------------------------------------------------------------

NEIGHBORS_DEFAULT_HOPS = 1
NEIGHBORS_MAX_HOPS = 10          # ★ 与 settings.ASTROLABE_NEIGHBORHOOD["max_depth"] 一致
NEIGHBORS_MAX_NODES_CAP = 20000


@require_http_methods(["GET"])
def neighbors(request: HttpRequest, project_ref: str) -> JsonResponse:
    """★ `GET …/graph/neighbors/?vid=&hops=&direction=&types=&max_nodes=` —— ① 型。

    ★★ 参数：

    | 参数 | 默认 | 说明 |
    |---|---|---|
    | `vid`（或 `uid`） | — | ★ **优先 `vid`**；`uid` 是便利入口（⚠ 允许重复，取最小 vid） |
    | `hops` | 1 | 跳数，**1–10**（★ 支持你要的「3 跳及以上」） |
    | `direction` | `out` | `out`（我调用了谁）/ `in`（谁调用了我）/ `both`（发散） |
    | `types` | 全部 | 逗号分隔，如 `calls,imports` |
    | `max_nodes` | 3000 | ⚠ 调大要谨慎（见下） |

    ★★ **两道保险（`graph/traversal.py`）**：

    1. **预算截断** —— 超过 `max_nodes` / `max_edges` / 时间预算就**优雅停下**，
       并在响应里如实返回 `truncated: true` + `truncated_reason`
       ⇒ ★ **前端必须把它透传给用户**（❌ 不能假装图就这么多）
    2. **`statement_timeout`** —— 由**数据库**强制中断，⚠ 这是「不卡死系统」的最后一道保险

    ⚠ 与契约 §17.7 的关系：那段写「**>2 跳走加速器（异步作业）**」。
      我们**一期把它做成同步有界查询**（实测 2 万节点全图 10 跳 **1.8 秒**），
      ★ 因为 ③ 计算层一期不做；将来接加速器时，**这个端点的形态不用改**
      （只是内部换成"排队 + 轮询"）。
    """
    if _viewable(request, project_ref) is None:
        return fail(permissions.NOT_FOUND, 404)

    raw = (request.GET.get("vid") or request.GET.get("uid") or "").strip()
    if not raw:
        return fail("缺少 vid（或 uid）参数", 400, code="missing_fields")
    node_ref: int | str = int(raw) if raw.isdigit() else raw

    hops = _clamp(request.GET.get("hops"), 0, NEIGHBORS_MAX_HOPS, NEIGHBORS_DEFAULT_HOPS)
    direction = (request.GET.get("direction") or DIRECTION_OUT).strip()
    types = [t.strip() for t in (request.GET.get("types") or "").split(",") if t.strip()] or None

    limits: dict = {}
    if request.GET.get("max_nodes"):
        limits["max_nodes"] = _clamp(
            request.GET.get("max_nodes"), 1, NEIGHBORS_MAX_NODES_CAP, 3000
        )

    try:
        # ★ 这里就是「访问热度」的记账点（`graph/traversal.py` 的 `neighborhood`）
        sg = neighborhood(
            project_ref,
            node_ref,
            depth=hops,
            direction=direction,
            edge_types=types,
            limits=limits or None,
        )
    except ValueError as exc:
        return fail(str(exc), 400, code="bad_request")

    if sg.root is None:
        return fail("节点不存在", 404)

    return ok(subgraph_json(sg, include_stats=True))


# ---------------------------------------------------------------------------
# 图版本（供前端轮询）
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
def rev(request: HttpRequest, project_ref: str) -> JsonResponse:
    """`GET …/graph-rev/` —— ② 型。

    ★ `graph_rev` 一变 ⇒ **图变过**（重新解析或维护者修补）⇒ 前端应**重新拉图**。
      ⚠ 它就是邻域缓存的命名空间代际（`graph/revision.py`）。
    """
    if _viewable(request, project_ref) is None:
        return fail(permissions.NOT_FOUND, 404)

    job = _latest_parse_job(project_ref)
    return ok_flat(
        graph_rev=graph_rev_of(project_ref),
        parse_status=job.state if job else "none",
    )


@require_http_methods(["GET"])
def meta(request: HttpRequest):
    """★★ `GET /api/graph/meta/` —— ★★ **图修补元数据**（`B230`）⚠

    ⇒ `{node_fields, edge_fields, kinds, edge_types}`

    ## ★★ 为什么要这个端点

    ```
    ★★ 前端要用下拉 / 数字框，* 就得知道「有哪些合法值」——
      · · ★ 硬编码一份 ⇒* 迟早和 `graph/kinds.py` / 模型漂移 ⚠
      · · ★★ 本端点与后端校验**同一个反射函数** ⇒* 同源、* 不漂移 ✅
    ⚠ 公开只读（* 这是元数据，* 不是业务数据）✅
    ```
    """
    from graph import patch_spec

    return ok(patch_spec.graph_meta())
