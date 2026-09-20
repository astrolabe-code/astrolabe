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

from django.conf import settings
from django.db.models import Count
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from core import fetch, oauth, storage
from core.models import OAuthIdentity, OAuthState, Project
from graph.models import Edge, Node
from graph.revision import current as graph_rev_of
from jobs import dispatch
from jobs.models import Job
from web import permissions
from web.http import fail, ok, ok_flat, safe_next_url

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
        # ★★★ `B169` 新增：**是否已定版** —— 前端靠它决定「拉取代码」按钮的显隐：
        #   ★ 已定版（★ 代码已拉下**且**解析完成）⇒ 不给按钮（点了必然 409）
        #   ★ 未定版（含**拉取失败 / 解析失败**）⇒ **给按钮**（★ 所有者裁定：失败还允许再发起）
        # ⚠★ 为什么不用 `status` 判断：★ `status` 是**作业状态**（`Job.state`），
        #   ⚠ 而"定版"是 **`Project.is_graph_built`** —— ★ 两者不是一回事
        #   （★ 作业可能 `done` 但图未定版，⚠ 反之亦然）⇒ ★★ **必须单独给一个字段**。
        "graph_built": bool(project.is_graph_built),
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
# /api/projects/<project_ref>/fetch/      ★ 拉取代码（`B169`：**取代**原来的 parse/）
# ---------------------------------------------------------------------------

@require_http_methods(["POST"])
def start_fetch(request: HttpRequest, project_ref: str) -> JsonResponse:
    """★★★ **发起「拉取代码」授权**（`B169`）—— ★ 本视图**只负责发起**，真正的动作在 OAuth 回调里。

    ## ★ 为什么必须是两步
    ⚠★ 因为本平台**不保存 `access_token`**（`B148`）⇒ ★ 无法在这里替用户去问 GitHub
    "这个库是不是他的" ⇒ ★★ **只能让用户当场授权一次** ✅
    → ★ 与 `projects/publish/start/` **完全同构**（★ 见 `views/publish.py` 的模块文档）。

    ## ★★★ 它**取代**了什么 —— ★ 这段必须留住，否则「补投」又会被发明回来
    ★ `B169` 之前这里是 `parse/`，而且带着一个 **「补投」** 语义（★ 未定版时可重投）。
    ⚠★ **「补投」不是项目所有者要的** —— ★ `B155` 里他给的出路是「**删了项目重新建一个**」⚠
    ⇒ ★★★ **本视图不允许任何形式的「重投」**：★ **要么从头发起一次授权，要么拒绝。**

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

    # ★★ 从 `repo_url` 反推 `owner/repo` —— ⚠ 反推不出来 ⇒ **归属校验连问都问不了** ⇒ 早失败
    repo = fetch.repo_full_from_url(project.repo_url)
    if repo.count("/") != 1 or any(seg in ("", ".", "..") for seg in repo.split("/")):
        return fail(
            "项目的仓库地址无法识别（应为 owner/repo 形式），请先在项目设置里改正。",
            400,
            code="bad_repo",
        )

    # ★★ 早失败（fail fast）：★ 没绑定过这个 provider 的身份 ⇒ **归属校验一定过不了**
    #   ⚠ 所以别让用户白跑一趟 GitHub（★ 他回来只会看到"这不是你的仓库"）
    #   ★ 与 `views/publish.py::start()` 的那道检查**同一口径** ✅
    if not OAuthIdentity.objects.filter(user=request.user, provider=provider).exists():
        return fail(
            f"请先用 {provider} 登录一次，确认账号归属后再拉取。",
            400,
            code="identity_missing",
        )

    body = _body(request)
    next_url = safe_next_url(str(body.get("next_url") or ""))
    if next_url is None:
        # ★★ 放行它 = 把 token 送给攻击者 —— 见 `web/http.py::safe_next_url`
        return fail("next_url 不在允许的域名白名单内", 400, code="bad_next_url")

    # ⚠★ `source_path` 只对 staff 生效（`B152`：⚠ 它能让服务端读容器里任何目录）
    #   ★ 普通用户一律**不收**（★ 他的源码应当由作业层从 `repo_url` 拉取）
    source_path = str(body.get("source_path") or "") if request.user.is_staff else ""

    st = oauth.start(
        provider,
        action=OAuthState.ACTION_FETCH,
        # ★★ 这两个必须带过去：★ 回调时**只剩 `state` 这一条线索**（见 `OAuthState` 文档）
        project_ref=project.project_ref,
        repo=repo,
        intent={"source_path": source_path},
        next_url=next_url,
        remember=True,
        base_url=getattr(settings, "ASTROLABE_BASE_URL", "").rstrip("/"),
    )
    return ok({"authorize_url": st.url, "state": st.state.state, "repo": repo})


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
