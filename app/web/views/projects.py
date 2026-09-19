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

from core import fetch, storage
from core.models import Project
from graph.models import Edge, Node
from graph.revision import current as graph_rev_of
from jobs import dispatch
from jobs.models import Job
from web import permissions
from web.http import fail, ok, ok_flat

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


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


def _counts(project_refs: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    """★ 一次查询取回所有项目的节点 / 边数量（❌ 不要每个项目查一次）。"""
    nodes = dict(
        Node.objects.filter(project_ref__in=project_refs)
        .values_list("project_ref")
        # ⚠ 用 "pk" 而不是 "node_id"/"id" —— ★ 不依赖主键的**字段名**
        #   （`Node` 的主键叫 `node_id`，`Edge` 的叫 `id`，写死任一个都会炸）
        .annotate(n=Count("pk"))
    )
    edges = dict(
        Edge.objects.filter(project_ref__in=project_refs)
        .values_list("project_ref")
        .annotate(n=Count("pk"))
    )
    return nodes, edges


def _latest_parse_job(project_ref: str) -> Job | None:
    return (
        Job.objects.filter(project_ref=project_ref, kind=Job.KIND_PARSE)
        .order_by("-queued_at")
        .first()
    )


def _project_json(project: Project, request: HttpRequest, node_n: int, edge_n: int) -> dict:
    job = _latest_parse_job(project.project_ref)
    user = getattr(request, "user", None)
    return {
        "project_ref": project.project_ref,
        "name": project.name,
        "desc": project.desc,
        "is_public": project.is_public,
        "provider": project.provider,
        "repo_url": project.repo_url,
        "commit": project.commit,
        # ⚠ `mine` —— 前端靠它决定是否渲染「设置 / 重新解析」入口
        "mine": bool(user and user.is_authenticated and project.owner_id == user.pk),
        "owner": project.owner.get_username() if project.owner_id else "",
        "status": job.state if job else "none",
        "progress": job.progress if job else 0,
        "graph_rev": graph_rev_of(project.project_ref),
        "node_count": node_n,
        "edge_count": edge_n,
        "created_at": project.created_at.isoformat(),
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
    qs = Project.objects.all()
    if not (user and user.is_authenticated):
        # ★ 游客只看公开项目（否则登录与否就没区别了）
        qs = qs.filter(is_public=True)
    elif not user.is_staff:
        # ⚠ 登录用户看：公开项目 + 自己的
        from django.db.models import Q

        qs = qs.filter(Q(is_public=True) | Q(owner=user))

    qs = qs.order_by("-created_at")[:200]
    projects = list(qs)
    nodes, edges = _counts([p.project_ref for p in projects])

    # ② 型（契约 §2：项目列表 = `{projects:[...]}`）
    return ok_flat(
        projects=[
            _project_json(p, request, nodes.get(p.project_ref, 0), edges.get(p.project_ref, 0))
            for p in projects
        ]
    )


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
    if provider not in dict(Project.PROVIDER_CHOICES):
        return fail("provider 必须是 github 或 gitee", 400, code="invalid_provider")

    project = Project.objects.create(
        name=name[:200],
        desc=str(body.get("desc") or "")[:2000],
        owner=user,
        provider=provider,
        repo_url=repo_url[:512],
        commit=commit[:64],
        is_public=bool(body.get("is_public", False)),
    )
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

    if not permissions.can_edit(request, project):
        return fail("需要项目所有者权限", 403, code="forbidden")

    if request.method == "DELETE":
        # ⚠ 一期：**物理删除**（图 / 作业随 project_ref 一起清）
        #   ⚠ 契约 §19.6 要求「删除中 = deleting 状态 + 拒绝写」，那是后续的事
        #
        # ★★ **必须先释放存储空间**（`B152`）——
        #   ⚠★ 否则磁盘上那份源码会**永远留着**（★ 而用户以为他删掉了 ⇒
        #     他会觉得"我明明删了，为什么还是满的"，⚠ 这是最难解释的一类 bug）。
        freed = storage.release(project_ref)

        Node.objects.filter(project_ref=project_ref).delete()
        Edge.objects.filter(project_ref=project_ref).delete()
        Job.objects.filter(project_ref=project_ref).delete()
        # ⚠ 审核流水**刻意保留**（`B146`：append-only —— 删项目**不得**抹掉限额流水）
        project.delete()
        return ok({"deleted": True, "storage_freed_bytes": freed})

    # PATCH
    body = _body(request)
    for field in ("name", "desc", "repo_url", "commit"):
        if field in body:
            setattr(project, field, str(body[field] or "")[:2000])
    if "provider" in body and str(body["provider"]) in dict(Project.PROVIDER_CHOICES):
        project.provider = str(body["provider"])
    if "is_public" in body:
        project.is_public = bool(body["is_public"])
    project.save()
    nodes, edges = _counts([project_ref])
    return ok(_project_json(project, request, nodes.get(project_ref, 0), edges.get(project_ref, 0)))


# ---------------------------------------------------------------------------
# /api/projects/<project_ref>/parse/     ★ 新设计的新增入口
# ---------------------------------------------------------------------------

@require_http_methods(["POST"])
def parse(request: HttpRequest, project_ref: str) -> JsonResponse:
    """★ 触发解析 —— 写 Job 记录 + 投递队列，**立刻返回**（❌ 不在请求里干活）。

    ★★★ **`B155` 之后它的语义变了：这是"补投"，不是"重新解析"**。

    | 项目状态 | 行为 |
    |---|---|
    | ★ **未定版**（图还没生成） | ✅ 允许投递（★ 正当用途：★ **作业失败/丢了，重投一次**） |
    | ★★ **已定版**（图已生成） | ★★ **409** + 引导语（★ **不重新解析**） |

    ★★ 为什么"已定版"必须挡住（用户原话）：
    > 「代码解析完成之后**应该不允许重新解析**……
    > **解释里的"几行到几行"就失效了**。你要解析另一个版本的，那就**重新建一个项目**。」

    ⇒ ★ 两条出路写进了**错误消息**里（★ 让用户看到就知道该怎么办）：
    ★ **要另一个版本 ⇒ 新建项目**；★ **质量太差 ⇒ 删了重建**。
    """
    project = permissions.get_project(request, project_ref)
    if project is None or not permissions.can_view(request, project):
        return fail(permissions.NOT_FOUND, 404)
    if not permissions.can_edit(request, project):
        return fail("需要项目所有者权限", 403, code="forbidden")

    # ★★★ **定版闸门**（`B103` / `B155`）—— ★ 见函数文档
    if project.is_graph_built:
        return fail(
            "这个项目已经解析过了，图不会重新生成。"
            "★ 需要另一个版本请【新建一个项目】；★ 想重来请【删掉本项目后重建】。",
            409,
            code="graph_immutable",
        )

    body = _body(request)
    payload: dict = {}
    # ⚠★ `source_path` 只对 staff 生效（`B152`：⚠ 它能让服务端读容器里任何目录）
    source_path = str(body.get("source_path") or "") if request.user.is_staff else ""
    if source_path:
        payload["path"] = source_path

    if not project.repo_url:
        return fail("项目还没有设置仓库地址", 400, code="missing_repo")

    # ★★ 作业自己从远端拉（`B153`）—— ★ 所以这里必须带上"拉哪儿"
    payload.update(
        {
            "project_id": project.pk,
            "provider": project.provider,
            "repo_full_name": fetch.repo_full_from_url(project.repo_url),
            "repo_url": project.repo_url,
            "commit": project.commit,
        }
    )

    job, created = dispatch.submit(
        kind=Job.KIND_PARSE,
        project_ref=project_ref,
        payload=payload,
        # ★ 幂等：同一项目 + 同一 commit 的重复点击 ⇒ **合并到已有作业**（B115 ④）
        dedup_key=f"parse:{project_ref}:{project.commit or 'head'}",
    )
    return ok(
        {
            "job_id": job.pk,
            "state": job.state,
            "created": created,
            "queue_position": dispatch.queue_position(job),
        },
        status=202,
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
