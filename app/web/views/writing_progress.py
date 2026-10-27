"""★★★ **写作进度**（`D123` 修正版 · 2026-10-27）⚠

## 所有者原话（逐字）

> 「**作者也那个进度应该是统计的意义，还有多少函数节点没写，
>   还有多少文件节点没写，写了多少之类的**」

## 为什么不是「路径站点」

```\n上一版把「导读路径有几站写了小结」当进度 ⇒ 混淆了两件事：\n  · 路径是**阅读顺序**（给读者）\n  · 进度是**覆盖率**（给作者：这本书写了多少）⚠\n```\n
## 口径

```\n分母  这个项目**可读节点**里，每种类型各有多少个\n分子  其中**已经写过「小结」**的有多少个（* 小结 = 对象视角，`D122`）\n```\n
⚠ 只认「小结」：其余四类（灵光 / 质疑 / 困惑 / 踩坑）是「我」视角，
  写了也不代表「这一块写进书里了」⚠
"""

from __future__ import annotations

from django.db.models import Count
from django.http import HttpRequest

from core.models import Note
from graph import kinds, scope
from web.http import fail, ok
from core.access import can_edit_project
from web.permissions import can_view, get_project


def _empty() -> dict:
    return {"total": 0, "file": 0, "function": 0, "type": 0, "other": 0}


def project_progress(request: HttpRequest, project_ref: str):
    """`GET /api/projects/<ref>/progress/`

    ```json
    {
      "nodes":   {"total": 137, "file": 15, "function": 93, "type": 29, "other": 0},
      "summary": {"total": 3,   "file": 1,  "function": 2,  "type": 0,  "other": 0},
      "noted":   {"total": 5}      // 有任意一类笔记的节点数（不只是小结）
    }
    ```
    """
    project = get_project(request, project_ref)
    if project is None:
        return fail("项目不存在或无权访问", 404, code="not_found")
    if not can_view(request, project):
        return fail("没有阅读权限", 403, code="forbidden")

    nodes = scope.readable_nodes_of(project.project_ref)

    # ---- 分母：每种类型多少个节点 ----
    totals = _empty()
    for row in nodes.values("kind").annotate(n=Count("stable_vid")):
        name = kinds.kind_name(row["kind"])
        key = name if name in totals else "other"
        totals[key] += row["n"]
        totals["total"] += row["n"]

    # ---- 分子：写过「小结」的**不同节点**，按节点类型分 ----
    base = Note.objects.filter(
        project=project,
        kind="summary",
        state="active",
        deleted_at__isnull=True,
        node__isnull=False,
    )
    # ⚠ 外人只数公开小结（* 和笔记列表的可见性一致）⚠
    if not can_edit_project(request.user, project):
        base = base.filter(is_public=True)

    summary = _empty()
    for row in base.values("node__kind").annotate(n=Count("node_id", distinct=True)):
        name = kinds.kind_name(row["node__kind"])
        key = name if name in summary else "other"
        summary[key] += row["n"]
        summary["total"] += row["n"]

    # ---- 有任意笔记的节点数（* 衡量"这块我动过"）⚠ ----
    noted = (
        Note.objects.filter(
            project=project,
            state="active",
            deleted_at__isnull=True,
            node__isnull=False,
        )
    )
    if not can_edit_project(request.user, project):
        noted = noted.filter(is_public=True)
    noted_n = noted.values("node_id").distinct().count()

    return ok({"nodes": totals, "summary": summary, "noted": {"total": noted_n}})
