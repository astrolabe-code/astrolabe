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

from graph.models import Edge, Node


def node_json(node: Node, *, depth: int | None = None) -> dict[str, Any]:
    """单个节点 —— ★ 字段取「画图 + 节点详情」需要的（`G4-3`：❌ 不 SELECT *）。"""
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
        "origin": node.origin,
    }
    if depth is not None:
        data["depth"] = depth
    return data


def edge_json(edge: Edge) -> dict[str, Any]:
    """单条边 —— ★ **只返回边字段，不 join 节点**（契约 §6 明确要求）。

    ★ 前端拿 `graph/nodes` 的结果 + 这里的 `from` / `to` **自行关联** ——
      这样一次查询就能取几千条边，❌ 不会因为 join 退化成 N+1。

    ⚠ 契约 §6 原文说"前端自行与 `graph/nodes` 结果做 **uid** 关联" ——
      我们改成 **vid** 关联（理由见本文件顶部：uid 允许重复）。
    """
    return {
        "from": edge.from_node_id,
        "to": edge.to_node_id,
        "type": edge.type,
        "line": edge.line,
        "origin": edge.origin,
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


def count_by(rows: Iterable[tuple[str, int]]) -> dict[str, int]:
    """`values_list(x).annotate(Count(...))` 的结果 → 字典。"""
    return {str(k): int(v) for k, v in rows}
