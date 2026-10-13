"""Astrolabe · ① Web 层：序列化

★ 依据 `frontend-contract.md` §3（`_node_json` 全集）。

★★ **与旧契约的一处**必要**偏离（`B132`）** —— `vid` vs `uid`：

| | 旧契约 §3 | ★ 新设计 |
|---|---|---|
| 节点标识 | 只用 `uid` | ★ **`vid` 是权威标识**（`B117`），`uid` 只是**人类可读标签**（⚠ 允许重复） |

⚠ **为什么必须偏离**：`uid` 允许重复 ⇒ 用它做节点详情路径 / 锚点挂载会**挂错节点**。
  ⇒ 一是**同时返回两者**（前端平滑迁移），二是**节点详情用 `vid` 定位**。
  ⚠ 契约 §3 里的 `base_uid` / `col` / `parent_uid` / `metrics` / `cluster` / `is_entry` / `is_dead` /
  `visibility` / `lifecycle` 等字段**我们还没有**（它们依赖 ③ 计算层与 UGC 层）——
  ★ 契约 §1 原则「**新增字段一律可选**」⇒ 先不发，前端按"key 缺失 = 服务端版本低"处理（§16.3 第 2 条）。

⚠ 渲染层必须转义（契约 §19.2）：`name` / `qname` / `signature` 服务端**保留原值、不净化**。
"""

from __future__ import annotations

from typing import Any, Iterable

from graph import scope
from graph.models import PATCH_ADD_NODE, Edge, Node


def node_json(
    node: Node, *, depth: int | None = None, base_graph=None
) -> dict[str, Any]:
    """单个节点 —— ★ 字段取「画图 + 节点详情」需要的（`G4-3`：❌ 不 SELECT *）。

    ## ⚠★ `B179`（2026-10-13）改了这里两件事

    | 字段 | 变化 |
    |---|---|
    | ★ `origin` | ★★ **不再是一列**（★ `B179` 把列删了）⇒ ★ **按归属算**：<br>★ 基图行 ⇒ `parsed` · ★ 叠加行（`project_ref`）⇒ `manual` ✅ |
    | ★★ `blob_url` | ★★★ **新增** —— ★ 所有者要求的那条**永久链接** ⚠<br>「点击基图上的节点，**一定要能给出正确的函数位置链接**」⚠ |

    ⚠★★ **列表端点必须把 `base_graph` 传进来** ——
      ★ 否则每个节点都会去 `node.base_graph` 查一次库（**N+1**）⚠
      ★ 而这里的兜底分支是**留给单节点场景**的（★ 节点详情只查一个 —— 可以接受）✅
    """
    data: dict[str, Any] = {
        # ★★ 权威标识（B117）—— 锚点、邻域查询、详情路径都用它
        "vid": node.node_id,
        # ★ 人类可读标签（⚠ 可能重复）—— 仅用于展示 / 搜索
        "uid": node.uid,
        "kind": node.kind,
        "name": node.name,
        "qname": node.qname,
        "file_path": node.file_path,
        "line": node.line,
        "line_end": node.line_end,
        "lang": node.lang,
        "signature": node.signature,
        # ★★ 算出来的（⚠ 不再是读列）—— ★ 归属决定它，见函数文档
        "origin": "parsed" if node.base_graph_id else "manual",
    }
    if depth is not None:
        data["depth"] = depth

    bg = base_graph
    if bg is None and node.base_graph_id:
        # ⚠ 兜底（★ 单节点场景可用；★ **列表端点别走这里** —— 那是 N+1）
        bg = node.base_graph
    blob = scope.blob_url_of(node, bg)
    if blob:
        data["blob_url"] = blob
    return data


def edge_json(edge: Edge) -> dict[str, Any]:
    """单条边 —— ★ **只返回边字段，不 join 节点**（契约 §6 明确要求）。

    ★ 前端拿 `graph/nodes` 的结果 + 这里的 `from` / `to` **自行关联** ——
      这样一次查询就能取几千条边，❌ 不会因为 join 退化成 N+1。

    ⚠ 契约 §6 原文说"前端自行与 `graph/nodes` 结果做 **uid** 关联" ——
      我们改成 **vid** 关联（理由见本文件顶部：uid 允许重复）。
    """
    return {
        # ★★★ `B180`：**边的权威标识**（★ 补丁靠它指认"我改的是哪条边"）⚠
        #   ★★ 为什么不给不行：★ `update_edge` / `remove_edge` 这些补丁带的是
        #     `target_edge`（★ 就是这条边的**主键**）⚠
        #   · ★ 而前端**只能靠 `id` 把它和边对上** —— ★ 光有 `from`/`to`/`type`
        #     **对不上**（★ 同一个调用点可以是多行、多条边共用同样的两端）⚠
        #   ⇒ ★★ 于是"前端整合"这件事对边就**做不到**了 ⚠
        #   ★ 节点那边没这个问题 —— ★ 它们本来就带 `vid` ✅
        "id": edge.pk,
        "from": edge.from_node_id,
        "to": edge.to_node_id,
        "type": edge.type,
        "line": edge.line,
        # ⚠★ `B179`：`origin` 不再是一列 ⇒ ★ 按归属算（★ 同 `node_json`）⚠
        "origin": "parsed" if edge.base_graph_id else "manual",
        "confidence": edge.confidence,
    }


def subgraph_json(sg, *, include_stats: bool = False) -> dict[str, Any]:
    """邻域查询结果（`graph/traversal.py` 的 `SubGraph`）→ JSON。"""
    data: dict[str, Any] = {
        "root": sg.root,
        "nodes": [
            {
                "vid": n.vid,
                "uid": n.uid,
                "kind": n.kind,
                "name": n.name,
                "file_path": n.file_path,
                "line": n.line,
                "line_end": n.line_end,
                "lang": n.lang,
                "depth": n.depth,
            }
            for n in sg.nodes
        ],
        "edges": [
            {"from": e.src, "to": e.dst, "type": e.type, "line": e.line}
            for e in sg.edges
        ],
        # ★★ 必须透传给前端（`G4` / `graph/traversal.py`）——
        #    ⚠ 被预算截断时前端要显示「还有更多」，❌ 不能假装图就这么多
        "truncated": sg.truncated,
        "truncated_reason": sg.truncated_reason,
    }
    if include_stats:
        data["stats"] = sg.stats
    return data


def patch_json(patch) -> dict[str, Any]:
    """★★ **一条「用户对基图的修改」**（★ `B179` —— 这是【第二份数据】）⚠

    ★★★ 所有者原话（逐字）：

    > 「**基图与用户修改存在不同模型里，请求时，直接请求这两份数据，
    > 前端负责整合**」

    ⇒ ★★ 所以这里**只把修改如实列出来** —— ★ **服务端不把它与基图合并** ⚠
      ★ 前端拿每条的 `target_vid` 去基图那份里**一比**，
      ★★ 就知道哪个节点被改过 / 删过 ✅

    ★ 每种动作给什么（★ 够前端合并就行）：

    | 动作 | 给什么 |
    |---|---|
    | ★ `add_node` | ★ `target_vid` + `node`（★ 那个新节点的完整内容）|
    | ★ `update_node` / `remove_node` | ★ `target_vid` + `payload` |
    | ★ `add_edge` | ★ `from` / `to` + `payload` |
    | ★ `update_edge` / `remove_edge` | ★ `target_edge` + `payload` |
    """
    out: dict[str, Any] = {
        "patch_id": patch.pk,
        "action": patch.action,
        "at": patch.created_at.isoformat() if patch.created_at else "",
        "by": patch.created_by.username if patch.created_by_id else "",
        "note": patch.note,
    }

    # ★ 它改的是谁（★ 前端就靠这几个 id 去基图那份里对上）⚠
    if patch.target_node_id:
        out["target_vid"] = patch.target_node_id
    if patch.target_edge_id:
        out["target_edge"] = patch.target_edge_id
    if patch.from_node_id:
        out["from"] = patch.from_node_id
    if patch.to_node_id:
        out["to"] = patch.to_node_id
    if patch.payload:
        out["payload"] = patch.payload

    # ★★ `add_node` 的内容**不重复存**（★ 它就在那个节点行里）⇒ ★ 这里一并发出去 ✅
    #   ⚠★ 那个节点是**叠加行**（`project_ref`）⇒ ★ `origin` = `manual`、
    #     ★★ 而且**不会有 `blob_url`**（★ 它不在远端任何地方 —— ❌ 不给假链接）⚠
    if patch.action == PATCH_ADD_NODE and patch.target_node_id:
        out["node"] = node_json(patch.target_node)
    return out


def count_by(rows: Iterable[tuple[str, int]]) -> dict[str, int]:
    """`values_list(x).annotate(Count(...))` 的结果 → 字典。"""
    return {str(k): int(v) for k, v in rows}
