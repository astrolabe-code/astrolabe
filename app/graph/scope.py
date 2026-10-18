"""Astrolabe · 图：**读图时的"范围"**（★ `B179` · 2026-10-13）

★★★ **本模块只回答一个问题**：

> ★★ **「这个项目，该去读哪一份图数据？」** ⚠

★★ 答案：★ **它绑定的那份【基图】**（★ 而**不是**"`project_ref` 等于它的那些行"）⚠

---

# ★★★ 为什么要单独一个模块（★ 而不是让每个视图自己写）

★ `B179` 之前，读图到处都是同一句话：

```python
Node.objects.filter(project_ref=project_ref)          # ⚠ B179 之前的写法
```

★ 那句话在 `B179` 之后**含义完全变了** —— ⚠★ `project_ref` 现在只表示
  「**用户自己新增的节点**」（★ 叠加层）★ 而**解析出来的节点挂在基图上** ⚠

⇒ ★★★ 如果让 5 个视图各改一次，就**迟早有一个漏掉** ——
  ★★ 而漏掉的后果是**静默的**：★ 那个端点会返回**空图**（❌ 不报错）⚠

⇒ ★★ 所以按本项目一贯的做法（同 `U4.8`）：★ **把判断收敛到一处** ✅
  ★ 读图的地方一律写 `scope.nodes_of(project_ref)`，
  ★★ 而"该读哪份数据"这件事**只在本文件里决定一次** ⚠

---

# ⚠★ 本模块**不做**什么（★ 这是 `B180` 定的）

★★ 所有者原话（逐字）：

> 「**基图与用户修改存在不同模型里，请求时，直接请求这两份数据，前端负责整合，
> 不是在服务器上整合了，再发出去哦。**」

⇒ ★★★ 所以本模块**只发基图那一份** ——
  ★★ **绝不在这里把"修改"合进来** ⚠
  ★ 修改是**另一份数据**，★ 由 `graph/patches.py` + 独立端点发出 ✅
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from graph.models import Edge, Node

if TYPE_CHECKING:  # pragma: no cover
    from django.db.models import QuerySet


def base_graph_of(project_ref: str):
    """★ 这个项目绑的是哪份基图（★ 没绑 / 已删 ⇒ `None`）。

    ⚠★ 单独包一层是为了**只有一个地方**去 import `binding`
      （★ 免得读路径和写路径各自 import，早晚出现两套说法）。
    """
    from graph import binding

    return binding.of(project_ref)


def nodes_of(project_ref: str) -> "QuerySet[Node]":
    """★★ **这个项目可读的【基图节点】**（★ 没绑基图 ⇒ **空集**）⚠

    ⚠★ 返回的是 `QuerySet`（❌ 不是 list）—— ★ 调用方可以继续 `.filter()` /
      `.count()` / 切片，★ **不会把整张图拉进内存** ⚠
      ★（★ 这是本项目的一贯要求：★ 大图上的任何读都不能"先取全部再过滤"）
    """
    bg = base_graph_of(project_ref)
    if bg is None:
        return Node.objects.none()
    # ★★ `B220`：* 节点跨版本共用 ⇒* 按 `versions` 数组取（* GIN 索引）⚠
    return Node.objects.filter(versions__contains=[bg.pk])


def edges_of(project_ref: str) -> "QuerySet[Edge]":
    """★★ **这个项目可读的【基图边】**（★ 同样：没绑 ⇒ 空集）⚠"""
    bg = base_graph_of(project_ref)
    if bg is None:
        return Edge.objects.none()
    # ★★ `B220`：* 同上 ——* 按 `versions` 数组取 ⚠
    return Edge.objects.filter(versions__contains=[bg.pk])


# ===========================================================================
# ⚠★★ 2026-10-15（`B186`）：**读端点专用入口** —— 「基图层 ∪ 修改层」
# ===========================================================================
#
# ## ★★ 为什么必须加（★ 这是一个**静默的坏 bug**）
#
# ```
# ★ `B186` 定了「**笔记型项目没有基图，只需要修改层的数据就行**」⚠
#   · ★ 而 `nodes_of()` / `edges_of()` 在**没绑基图时返回空集** ⚠
#   · ★★ 于是：* 笔记型项目的图**永远是空的** ⚠
#     —— * 而它**不报错**、* 前端只看到一张空白画布 ⚠
#   ⇒ ★★ **静默**（* 最难查的一类）⚠
# ```
#
# ## ★★ 为什么不直接改 `nodes_of()`
#
# ```
# ★ `nodes_of()` / `edges_of()` 还被**写路径与 diff** 用着 ⚠
#   · ★ `graph/curate.py:899` 拿它们当【基图层】去和修改层比对 ⚠
#   · ★ `graph/traversal.py` 的邻域遍历也按基图层算 ⚠
#   ⇒ ★★ 若让它们在无基图时改回修改层 ⇒ ★ **同一批节点会被算两遍** ⚠
#     （* 而那是另一个静默的错）⚠
# ```
#
# ## ★★ 口径
#
# ```
# readable_nodes_of(project_ref) =
#     ★ 绑了基图   ⇒ ★★ 基图层（* 与 nodes_of 相同）
#     ★ 没绑基图   ⇒ ★★ 修改层（* project_ref 那些行）✅
# ```
#
# ⚠★ `B180` 的口径**没有被破坏**：
#   · ★ 本函数返回的仍是**一份**数据（* 基图 **或** 修改层，* ❌ 不是两份合并）⚠
#   · ★★ 服务端依然【不做整合】—— * 前端照旧把"这一份"与"修改层那一份"合并 ⚠
#   · ★（* 绑了基图的项目 ⇒ * 修改层仍由 `patches` / `curate` 端点单独发 ✅）


def _project_of(project_ref: str):
    """★ 取项目行（* 叠加层查询用；* 不存在 ⇒ None）⚠"""
    from core.models import Project

    return Project.objects.filter(project_ref=project_ref).first()


def _overlay_nodes_of(project_ref: str) -> "QuerySet[Node]":
    """★★ 项目**自己新增**的节点（* 叠加层；`B221` 走 `project` 外键）⚠"""
    project = _project_of(project_ref)
    if project is None:
        return Node.objects.none()
    return Node.objects.filter(project=project)


def _overlay_edges_of(project_ref: str) -> "QuerySet[Edge]":
    """★★ 同上（* 叠加层边）⚠"""
    project = _project_of(project_ref)
    if project is None:
        return Edge.objects.none()
    return Edge.objects.filter(project=project)


def readable_nodes_of(project_ref: str) -> "QuerySet[Node]":
    """★★★ **读端点该发的节点**（★ `B186`：没绑基图 ⇒ 发修改层）⚠"""
    bg = base_graph_of(project_ref)
    if bg is None:
        return _overlay_nodes_of(project_ref)
    return Node.objects.filter(versions__contains=[bg.pk])


def readable_edges_of(project_ref: str) -> "QuerySet[Edge]":
    """★★★ **读端点该发的边**（★ 同上）⚠"""
    bg = base_graph_of(project_ref)
    if bg is None:
        return _overlay_edges_of(project_ref)
    return Edge.objects.filter(versions__contains=[bg.pk])


def is_manual_only(project_ref: str) -> bool:
    """★★★ **这个项目只有修改层吗**（★ 即：没绑基图 ⇒ 笔记型项目）⚠

    ★ 用途：★ 读端点据此决定 `origin` 参数怎么答 ✅
      · ★ `True`  ⇒ ★★ **所有节点都是 `manual`** ⇒
        · ★ `origin=manual` ⇒ ★ 如实返回它们 ✅
        · ★ `origin=parsed` ⇒ ★★ 如实返回空集 ✅
      · ★ `False` ⇒ ★ 修改层在**另一个端点** ⇒
        · ★ `origin=manual` ⇒ ★ 空集（* 原口径不变）✅
    """
    return base_graph_of(project_ref) is None


def blob_url_of(node: Node, base_graph) -> str:
    """★★★ **点这个节点该跳到哪**（★ 所有者要求的那条永久链接）。

    ★★★ 所有者原话（逐字）：

    > 「**基图的数据一定要锚定 github 上的版本，用 sha 之类的，也就是说点击基图上的
    > 节点，一定要能给出正确的函数位置链接，即便仓库作者已经版本迭代，
    > 重新提交好几次了。除非，作者完全删除这份源码版本。**」

    ★ 形态：★ `https://github.com/{owner}/{repo}/blob/{sha}/{path}#L{line}` ✅

    ⚠★★ `base_graph` **必须由调用方传进来**（❌ 不要在函数里 `node.base_graph`
      —— ★★ 那会变成"**每个节点查一次库**"（N+1）⚠
      ★ 而列表端点一次要发几百个节点 ⇒ ★ **那样会慢一个量级** ⚠

    ⚠★ 两点如实：
      · ★ **用户自己新增的节点 ⇒ 返回空串**（★ 它不在远端任何地方 —— ❌ 不编一个链接）⚠
      · ★★ 作者若**彻底删掉**那个版本 ⇒ 链接会 404 —— ★ 而我们**只能如实给出**它 ⚠
        ★（★ 这正是所有者那句"除非"所承认的边界）
    """
    # ★★ `B220`：* 归属判据换成 `repo_id`（* 叠加层节点没有 repo）⚠
    if node.repo_id is None or base_graph is None:
        return ""
    base = base_graph.blob_url
    if not base:
        return ""
    return f"{base}/{node.file_path}#L{node.line}"
