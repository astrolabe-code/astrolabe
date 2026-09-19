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

from graph.models import Edge, Node
from graph.revision import current as graph_rev_of
from graph.traversal import DIRECTION_OUT, neighborhood
from jobs.models import Job
from web import permissions
from web.http import fail, ok, ok_flat
from web.serializers import count_by, edge_json, node_json, subgraph_json

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

    node_qs = Node.objects.filter(project_ref=project_ref)
    edge_qs = Edge.objects.filter(project_ref=project_ref)
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
            "by_kind": count_by(node_qs.values_list("kind").annotate(n=Count("pk"))),
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

    qs = Node.objects.filter(project_ref=project_ref)

    kind = (request.GET.get("kind") or "").strip()
    if kind:
        qs = qs.filter(kind=kind)

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

    origin = (request.GET.get("origin") or "").strip()
    if origin in ("parsed", "manual"):
        qs = qs.filter(origin=origin)

    limit = _clamp(request.GET.get("limit"), 1, NODES_PAGE_MAX, 200)
    offset = _clamp(request.GET.get("offset"), 0, 10**9, 0)

    total = qs.count()
    # ★ 固定排序（保证分页稳定）—— ❌ 不要用未排序的切片
    items = [node_json(n) for n in qs.order_by("node_id")[offset : offset + limit]]

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

    node = Node.objects.filter(project_ref=project_ref, node_id=vid).first()
    if node is None:
        return fail("节点不存在", 404)

    out_qs = Edge.objects.filter(project_ref=project_ref, from_node_id=vid)
    in_qs = Edge.objects.filter(project_ref=project_ref, to_node_id=vid)

    callees = list(out_qs.select_related("to_node").order_by("type", "to_node_id")[:CALLEES_MAX])
    callers = list(in_qs.select_related("from_node").order_by("type", "from_node_id")[:CALLERS_MAX])

    return ok_flat(
        node=node_json(node),
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
        "vid": other.node_id,
        "uid": other.uid,
        "kind": other.kind,
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

    qs = Edge.objects.filter(project_ref=project_ref)

    types = [t.strip() for t in (request.GET.get("type") or "").split(",") if t.strip()][:10]
    if types:
        qs = qs.filter(type__in=types)

    origin = (request.GET.get("origin") or "").strip()
    if origin in ("parsed", "manual"):
        qs = qs.filter(origin=origin)

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
    items = [edge_json(e) for e in qs.order_by("type", "from_node_id", "to_node_id")[offset : offset + limit]]

    return ok({"total": total, "limit": limit, "offset": offset, "items": items})


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
