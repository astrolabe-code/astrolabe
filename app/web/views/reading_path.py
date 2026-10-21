"""★★★ 学习路径（导读路径）—— `B234` · 2026-10-18

## ★★★ 所有者设计指导规则（逐字）

> 「**这个作者可以指定展示哪些节点的，这是我设计的指导规则之一，
> 方便其他人按照作者指定的路径学习代码。**」

> 「**你直接在项目表里加一个顺序字段不就完了？按序存储节点vid按里面出现的顺序
> 展示节点……用得着新建一个表吗。而且这个顺序作者不可能一下全部标齐的，
> 是学到哪里标到哪里，与项目是强相关的。**」

## ★★ 四个端点（* 配合「学到哪里标到哪里」）

| 方法 | 作用 |
|---|---|
| `GET` | 按序返回路径（* 附带 `stale`：* 已不在图里的 vid）|
| `POST {vid}` | **追加**到队尾（* 已存在 ⇒ 幂等不动）|
| `DELETE {vid}` | 移除 |
| `PUT {items:[…]}` | **整体重排**（* 下标即新顺序）|

⚠★ `D107`：* 失效 vid **不卡站** ——* GET 如实报 `stale`，* ⛔ 不自动清理
  （* 所有者：* 等用户自己处理）✅
"""

from __future__ import annotations

from django.http import HttpRequest
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.models import Project
from graph import kinds
from graph import scope
from web.http import fail, ok, read_json
from web.permissions import can_edit, can_view, current_user, get_project

#: ★ 路径长度上限（* 一批才展示十几个，* 200 条足够）⚠
MAX_PATH_ITEMS = 200


def _readable_nodes(project: Project):
    """★ 这个项目能读的节点（* 基图版本 + 叠加层）⚠"""
    return scope.readable_nodes_of(project.project_ref)


def _payload(project: Project) -> dict:
    """★★★ 路径响应（* `D107`：* 失效项进 `stale`，* ⛔ 不卡住）⚠"""
    by_vid = {n.stable_vid: n for n in _readable_nodes(project)}
    items, stale = [], []
    for vid in project.reading_path or []:
        node = by_vid.get(int(vid))
        if node is None:
            stale.append(int(vid))
            continue
        items.append(
            {
                "ordinal": len(items),
                "vid": node.stable_vid,
                "name": node.name,
                "kind": kinds.kind_name(node.kind),
                "qname": node.qname,
                "file_path": node.file_path,
                "line": node.line,
                "line_end": node.line_end,
            }
        )
    return {"total": len(items), "items": items, "stale": stale}


def _validate(project: Project, vids) -> tuple[list[int] | None, str | None]:
    """★★ 校验 vid 列表（* `B234`④）⚠"""
    if not isinstance(vids, list):
        return None, "items 必须是数组"
    out: list[int] = []
    for v in vids:
        if isinstance(v, bool) or not isinstance(v, int):
            return None, f"vid 必须是整数：{v!r}"
        out.append(v)
    if len(out) > MAX_PATH_ITEMS:
        return None, f"一次最多 {MAX_PATH_ITEMS} 个节点"
    if len(set(out)) != len(out):
        return None, "路径里有重复的节点"
    have = set(
        _readable_nodes(project).filter(stable_vid__in=out).values_list("stable_vid", flat=True)
    )
    missing = [v for v in out if v not in have]
    if missing:
        return None, f"这些节点不在这个项目的图里：{missing[:5]}"
    return out, None


def _save(project: Project, vids: list[int]) -> None:
    """★ 整列替换（* 单行更新，* 没有删插竞争）✅"""
    Project.objects.filter(pk=project.pk).update(reading_path=vids)
    project.reading_path = vids


def _audit(*, action: str, project: Project, by, detail: dict) -> None:
    """★ 审计（* 与图修补同口径）✅"""
    from core.models import AuditLog

    AuditLog.objects.create(
        actor=by if getattr(by, "pk", None) else None,
        action=action,
        target_kind="Project",
        target_id=project.project_ref,
        detail={"by_name": getattr(by, "username", "") or "", **detail},
    )


@require_http_methods(["GET", "POST", "DELETE", "PUT"])
def collection(request: HttpRequest, project_ref: str):
    """`GET|POST|DELETE|PUT /api/projects/<ref>/reading-path/`（`B234`）"""
    project = get_project(request, project_ref)
    if project is None:
        return fail("项目不存在或无权访问", 404, code="not_found")

    # ---- GET：读（* 可读即可）----
    if request.method == "GET":
        if not can_view(request, project):
            return fail("没有阅读权限", 403, code="forbidden")
        return ok(_payload(project))

    # ---- 以下都要能编辑 ----
    user = current_user(request)
    if user is None:
        return fail("请先登录", 401, code="unauthenticated")
    if not can_edit(request, project):
        return fail("只有项目所有者或协作者能改学习路径", 403, code="forbidden")

    body = read_json(request)

    # ---- POST：追加一个（* 幂等）----
    if request.method == "POST":
        vid = body.get("vid")
        if isinstance(vid, bool) or not isinstance(vid, int):
            return fail("vid 必须是整数", 400, code="bad_vid")
        current = list(project.reading_path or [])
        if vid in current:
            return ok(_payload(project))  # ★ 已在路径里 ⇒ 幂等不动
        current.append(vid)
        clean, err = _validate(project, current)
        if err is not None:
            return fail(err, 400, code="bad_path")
        _save(project, clean)
        _audit(action="reading_path.append", project=project, by=user,
               detail={"vid": vid, "count": len(clean)})
        return ok(_payload(project))

    # ---- DELETE：移除一个 ----
    if request.method == "DELETE":
        vid = body.get("vid")
        if isinstance(vid, bool) or not isinstance(vid, int):
            return fail("vid 必须是整数", 400, code="bad_vid")
        current = [v for v in (project.reading_path or []) if int(v) != vid]
        _save(project, current)
        _audit(action="reading_path.remove", project=project, by=user,
               detail={"vid": vid, "count": len(current)})
        return ok(_payload(project))

    # ---- PUT：整体重排 ----
    clean, err = _validate(project, body.get("items"))
    if err is not None:
        return fail(err, 400, code="bad_path")
    before = len(project.reading_path or [])
    _save(project, clean)
    _audit(action="reading_path.replace", project=project, by=user,
           detail={"before": before, "after": len(clean)})
    return ok(_payload(project))
