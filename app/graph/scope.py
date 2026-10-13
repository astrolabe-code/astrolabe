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
    return Node.objects.filter(base_graph=bg)


def edges_of(project_ref: str) -> "QuerySet[Edge]":
    """★★ **这个项目可读的【基图边】**（★ 同样：没绑 ⇒ 空集）⚠"""
    bg = base_graph_of(project_ref)
    if bg is None:
        return Edge.objects.none()
    return Edge.objects.filter(base_graph=bg)


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
    if node.base_graph_id is None or base_graph is None:
        return ""
    base = base_graph.blob_url
    if not base:
        return ""
    return f"{base}/{node.file_path}#L{node.line}"
