"""★★ **项目计数与仓库信息落地**（2026-10-23 所有者裁定）⚠

## ★★★ 所有者原话（逐字）

> 「项目表补上这个项目的真实节点数和边数字段，每次现算干什么？用户每次修改节点和边，
>   项目表里的边数和节点数同步修改，同时，加上是 github 或 gitee 或自建项目字段，
>   以及拉库所用网址字段。当然，这两个 github 之类的信息字段一旦创建，无法修改，
>   不要有修改接口。」

## ★ 为什么要落成列

```
原来：列表页每次现算 —— 查绑定表 → 查基图计数 → 再按项目数叠加层（2 次聚合查询）
现在：直接读 core_project.node_count / edge_count（0 次额外查询）✅
```

## ★ 两段来源，缺一不可

```
基图节点（repo 非空）      —— 解析产物，跨版本共用，* 任何人不能改 ✅
项目自建节点（project 非空）—— 叠加层，项目维护者可增删 ✅
⇒ node_count = 基图计数 + 叠加层计数 ⚠
```

## ★ 何时刷新

| 事件 | 调用点 |
|---|---|
| 基图写完（解析作业定版） | `graph/writer.py` |
| 叠加层增 / 删 / 改 | `graph/curate.py::apply_changes` |
| 项目创建 | `core/publish.py` / `web/views/projects.py` |

⚠★ 失败**只记日志**：计数不准不影响主流程（* 下次刷新会纠正）✅
"""
from __future__ import annotations

import logging

logger = logging.getLogger("astrolabe.project_counts")

_HOSTS = {"github": "github.com", "gitee": "gitee.com"}


def repo_url_of(provider: str, repo_full_name: str) -> str:
    """★ 由平台 + `owner/repo` 拼出拉库地址（* 与 `core/publish.py::_repo_url` 同口径）⚠"""
    host = _HOSTS.get((provider or "").strip().lower())
    full = (repo_full_name or "").strip().strip("/")
    return f"https://{host}/{full}" if host and full else ""


def refresh(*, project_ref: str | None = None, base_graph_id: int | None = None) -> int:
    """★★ **重算并落库**（* 返回更新了几个项目）⚠

    ```
    refresh(project_ref="proj_…")        # 叠加层变了
    refresh(base_graph_id=12)            # 基图建成/更新 ⇒ 所有绑定它的项目
    ```
    """
    from django.db.models import Count

    from core.models import Project
    from graph.models import Edge, Node

    qs = Project.objects.select_related("base_graph")
    if project_ref:
        qs = qs.filter(project_ref=project_ref)
    if base_graph_id:
        qs = qs.filter(base_graph_id=base_graph_id)

    projects = list(qs)
    if not projects:
        return 0

    refs = [p.project_ref for p in projects]

    # ★ 叠加层：按项目 GROUP BY 一次拿全（* 不要每个项目查一次）⚠
    overlay_nodes = dict(
        Node.objects.filter(project__project_ref__in=refs)
        .values_list("project__project_ref")
        .annotate(c=Count("node_id"))   # ⚠ Node 的主键叫 node_id，不是 id
    )
    overlay_edges = dict(
        Edge.objects.filter(project__project_ref__in=refs)
        .values_list("project__project_ref")
        .annotate(c=Count("id"))
    )

    updated = 0
    for p in projects:
        bg = p.base_graph
        fields: dict = {
            # ★ 基图那部分 + 自建那部分
            "node_count": (bg.node_count if bg else 0) + overlay_nodes.get(p.project_ref, 0),
            "edge_count": (bg.edge_count if bg else 0) + overlay_edges.get(p.project_ref, 0),
        }

        # ★★ 仓库信息「**一旦落定就不再改**」：
        #    · · 只在为空时填（* 首次绑定仓库那一刻）✅
        #    · · 之后任何接口都改不了（* PATCH 只允许 name / desc）⚠
        if not p.provider and bg is not None and bg.provider:
            fields["provider"] = bg.provider[:16]
        if not p.repo_url:
            url = repo_url_of(
                fields.get("provider") or (bg.provider if bg else ""),
                bg.repo_full_name if bg else "",
            )
            if url:
                fields["repo_url"] = url[:512]

        try:
            Project.objects.filter(pk=p.pk).update(**fields)
            updated += 1
            # ★ 计数变了 ⇒ 项目索引也要更新（* 列表里显示节点数）⚠
            from search import sync

            sync.enqueue_project(p.project_ref)
        except Exception:
            logger.warning("刷新项目计数失败 %s", p.project_ref, exc_info=True)

    return updated


def mark_self_built(project) -> None:
    """★ 自建项目（不拉仓库）⇒ `provider="self"`（* 只写一次）⚠"""
    from core.models import Project

    if not project.provider:
        Project.objects.filter(pk=project.pk).update(provider="self")
