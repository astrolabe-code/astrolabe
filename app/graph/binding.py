"""Astrolabe · 图：**项目 ↔ 基图的绑定**（★ `B179` · 2026-10-13）

★★★ 所有者原话（逐字）：

> 「**用户拉一个图就解析一次，太浪费算力，应该是，拉去之前，看看现有的图数据里
> 有没有同样的，有同样的，就直接返回，不拉取，不解析，还快。**」

★ 本模块就是那句里的两个动作：

| 动作 | 函数 |
|---|---|
| ★★ 「**看看现有的图数据里有没有同样的**」 | `find()` / `get_or_create()` |
| ★★ 「**（有同样的，就）直接返回**」 | `bind()` —— ★ 把项目绑上去，★ **不投作业** ✅ |

---

# ★★ 为什么绑定关系单独一张表

★ 依赖方向是 **`graph` → `core`** ⚠ —— ★ 在 `core.Project` 上挂 `graph` 外键会**绕成圈** ⚠
⇒ ★★ 所以绑定由 `graph` 这边记（`ProjectBaseGraph`）✅

# ★ 一个刻意的选择：绑定时**顺手做两件事**

| 做的事 | 为什么 |
|---|---|
| ★★ `Project.graph_built_at` | ★ 那表示「**这个项目已经有可显示的图了**」—— ★★ 复用时**立刻**就该为真 ⚠<br>（★ 否则页面上会一直转圈等一个**根本不会来**的作业）⚠ |
| ★ `GraphRevision.bump()` | ★ 缓存命名空间是**按项目**的 ⇒ ★★ 图"出现"了这个时刻必须换代际 ⚠ |
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from graph import revision
from graph.models import BaseGraph, ProjectBaseGraph


def find(provider: str, repo_full_name: str, sha: str) -> BaseGraph | None:
    """★★ **按【仓库 + sha】找现成的基图** —— ★ 这就是"有没有同样的"那句。"""
    sha = (sha or "").strip()
    full = (repo_full_name or "").strip().strip("/")
    if not sha or not full:
        return None
    return BaseGraph.objects.filter(
        provider=(provider or "").strip().lower(), repo_full_name=full, sha=sha
    ).first()


def is_ready(bg: BaseGraph | None) -> bool:
    """★ 这份基图**建好了吗**（★ 只有建好的才能"直接返回"）。"""
    return bg is not None and bg.built_at is not None


def get_or_create(
    provider: str,
    repo_full_name: str,
    sha: str,
    *,
    ref: str = "",
    default_branch: str = "",
) -> tuple[BaseGraph, bool]:
    """★★ **取或建**那一条基图记录（★ 只是记录 —— ★ 图数据由作业写 ⚠）。

    ⚠★ 为什么要"先建记录、后写图"：★ 因为**解析作业**要用它当落点 ⚠
      ★★ 而"建好了没有"由 `built_at` 说了算（★ 不是"有没有这一行"）✅

    Returns: `(基图, 是否新建)`
    """
    full = (repo_full_name or "").strip().strip("/")
    bg, created = BaseGraph.objects.get_or_create(
        provider=(provider or "").strip().lower(),
        repo_full_name=full,
        sha=(sha or "").strip(),
        defaults={"ref": (ref or "")[:128], "default_branch": (default_branch or "")[:128]},
    )
    return bg, created


def of(project_ref: str) -> BaseGraph | None:
    """★ 这个项目绑的是哪份基图（★ 没绑 ⇒ `None`）。"""
    row = ProjectBaseGraph.objects.select_related("base_graph").filter(
        project_ref=project_ref
    ).first()
    return row.base_graph if row is not None else None


def bind(
    project_ref: str, base_graph: BaseGraph, *, requested_ref: str = ""
) -> ProjectBaseGraph:
    """★★ **把这个项目绑到那份基图上**（★ 并顺手把"已经有图"这件事设为真）⚠

    ★★ 关键：★ 如果这份基图**已经建好了** ⇒ ★ 绑定之后**不需要再投任何作业** ✅
      ★ 这正是「**不拉取、不解析，还快**」的落点 ⚠

    ⚠ 幂等：★ 同一个项目重复绑定**只是把关系指向最新的那份**（★ 不会报错）——
      ★ 因为"换一个分支再拉"就是**又绑一次**（★ 那时会指向另一份基图）✅
    """
    from core.models import Project

    with transaction.atomic():
        row, _ = ProjectBaseGraph.objects.update_or_create(
            project_ref=project_ref,
            defaults={"base_graph": base_graph, "requested_ref": (requested_ref or "")[:128]},
        )

        # ★★ 「这个项目已经有图了」—— ★ 复用时**立刻**为真（❌ 不靠一个不会来的作业）⚠
        if is_ready(base_graph):
            project = Project.objects.filter(project_ref=project_ref).first()
            if project is not None and project.graph_built_at is None:
                project.graph_built_at = timezone.now()
                project.save(update_fields=["graph_built_at", "updated_at"])

        # ★ 图"出现"了 ⇒ 这个项目的邻域缓存换代际（★ 见模块文档）
        revision.bump(project_ref)

    return row
