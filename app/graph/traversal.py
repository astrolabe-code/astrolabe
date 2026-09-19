"""Astrolabe · 图遍历：邻域查询（1 跳 → **任意跳**）

★ 依据：
    `GRAPH-STORAGE.md` G0  —— 从一个节点查 1 跳 / 2 跳 / ★ **更多跳**（「发散思维」的核心交互）
    `GRAPH-STORAGE.md` G2  —— 深度决定手段；★ 3 跳以上必须「**深度硬上限 + 结果上限**」
    `GRAPH-STORAGE.md` G3  —— 邻接表 + **两个索引**
    `GRAPH-STORAGE.md` G4  —— ★★ **四个防爆炸**
    `GRAPH-STORAGE.md` G6  —— ★★ **算法接口** = 「将来可换图数据库」的**唯一预留点**

★★ G6 铁律（本模块必须守住）：
    · 接口**按「图语义」定义** —— ❌ 参数与返回值里**不得出现任何 PG 特有的东西**
      （SQL / cursor / 表名 / 索引名 / ORM 对象）
    · ★ 现在**只定「接口 + 一个实现」** —— ⚠ 一个接口 + 一个实现**不叫抽象层**，
      叫**正常的模块边界**（G6「抽象的分寸」）
    · ✅ 将来 Neo4j / Nebula / AGE 只要实现同一个 `neighborhood(...)`，
      ★ **① Web 层的调用代码一行都不用改**（换实现只改 `settings.py` 里的一行字符串）

⚠ 分层（`ARCHITECTURE.md` A1/A2）：
    · ✅ 本模块 = **① Web 的读路径**（**有界**邻域）—— 这是允许的
    · ❌ **全图算法**（环 / 聚类 / 影响面 / 最短路径）**不在这里** —— 归 **③ 计算层**（G7）

★★ 算法选择（对 `G2` 的修正，必须说明）：
    `G2` 原写「2 跳用**递归 CTE**」。实现时改为 ★ **逐层 BFS**，原因：
    ⚠ 递归 CTE 若要防环，必须携带**路径数组**（`path || node`）——
      这会让中间行数按「**简单路径条数**」增长，在菱形依赖 / 中心节点上**指数爆炸**
      （不是节点数爆炸，是**路径数**爆炸）。
    逐层 BFS 每层**只做一次索引扫描**，中间行数上限 = 该层 frontier 的相邻边数
    ⇒ ★ **O(V+E) 而非 O(路径数)**；且每层之间可检查预算 ⇒ **优雅截断**（返回标志），
      而不是被数据库杀掉。性能与递归 CTE 同量级（都是索引扫描），**安全性高一个量级**。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils.module_loading import import_string

from graph.models import Edge, Node

# ---------------------------------------------------------------------------
# 方向（★ 图语义，❌ 不是 SQL 的 join 方向）
# ---------------------------------------------------------------------------

DIRECTION_OUT = "out"      # 我指向谁（我调用了谁 / 我导入了谁）
DIRECTION_IN = "in"        # 谁指向我（★ 谁调用了我 —— 读代码时最常问的问题，G3）
DIRECTION_BOTH = "both"    # 双向（「发散思维」的默认心智模型）

_DIRECTIONS = (DIRECTION_OUT, DIRECTION_IN, DIRECTION_BOTH)


# ---------------------------------------------------------------------------
# ★ 返回值：只含画图需要的字段（G4-3）—— ❌ 不返回 ORM 对象、不 SELECT *
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class GraphNode:
    """★ 图语义的节点 —— ❌ 不含 `node_id` / ORM / 任何 PG 概念。"""

    vid: int          # 对外唯一标识（B117：一期 = node_id）
    uid: str          # 人类可读标签（⚠ 允许重复，只用于展示）
    kind: str
    name: str
    file_path: str
    line: int
    line_end: int | None
    lang: str
    depth: int        # ★ 距起点的跳数（0 = 起点自己）


@dataclass(slots=True)
class GraphEdge:
    """★ 图语义的边 —— 两端用 `vid`。"""

    src: int
    dst: int
    type: str
    line: int | None


@dataclass(slots=True)
class SubGraph:
    """邻域查询结果（G6 的 `{nodes, edges}`）。"""

    project_ref: str
    root: int | None
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    #: ★ 是否被**预算截断**（前端必须如实告诉用户"后面还有"，❌ 不能假装图就这么多）
    truncated: bool = False
    truncated_reason: str = ""
    stats: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ★★ G6 接口（唯一预留点）
# ---------------------------------------------------------------------------

class GraphReader(Protocol):
    """★ 图查询接口 —— 「将来可换图数据库」的**唯一预留点**。

    ⚠ **实现者不得暴露任何 PG 特有的东西**（SQL / cursor / 表名 / ORM 对象）。

    ★ 完整的接口契约（`G6`）后续还会加，⚠ **但只有需要时才加**：

    ```
    neighborhood(project_ref, node, depth, direction)  -> SubGraph   ✅ 本文件已实现
    shortest_path(project_ref, from, to, max_len)      -> [vid, ...]  ⚠ 归 ③ 计算层
    find_cycles(project_ref, max_len)                  -> [[vid,...]] ⚠ 归 ③ 计算层
    clusters(project_ref)                              -> [...]       ⚠ 归 ③ 计算层
    impact(project_ref, node, direction)               -> SubGraph    ⚠ 归 ③ 计算层
    ```

    ⚠ 上面四条**故意不在这里声明** —— 声明了却抛 `NotImplementedError`，
      等于**假装接口已经存在**，会误导调用方。真正实现时（③ 计算层）再加。
    """

    def neighborhood(
        self,
        project_ref: str,
        node: int | str,
        *,
        depth: int | None = None,
        direction: str = DIRECTION_OUT,
        edge_types: Sequence[str] | None = None,
        limits: Mapping[str, Any] | None = None,
    ) -> SubGraph:
        """从一个节点出发，展开 N 跳邻域。

        Args:
            node: ★ **优先传 `vid`（int）** —— 它是唯一标识（`B117`）；
                  也接受 `uid`（str）作便利，⚠ 但 uid 允许重复，命中多个时取最小 vid 并在
                  `stats["ambiguous_uid"]` 里如实标注。
            depth: 跳数。★ 会被压到 `max_depth`（超出的部分记进 `truncated_reason`）
            direction: `out` / `in` / `both`
            edge_types: 只要这些类型的边（`None` = 全部）
            limits: 覆盖默认预算（深度 / 节点数 / 边数 / 时间 / statement_timeout）

        Returns:
            SubGraph（★ 含 `truncated` 标志 —— 调用方**必须**把它透传给前端）
        """
        ...


# ---------------------------------------------------------------------------
# ★ 预算：三层合并（内置默认 → settings → 调用方覆盖）
# ---------------------------------------------------------------------------

#: ★★ 「不卡死系统」的默认刹车（`G4-2`：深度硬上限 + 结果上限**都必须有**）
_DEFAULT_LIMITS: dict[str, Any] = {
    "default_depth": 1,          # 前端点一次查一跳（G4-4）
    "max_depth": 10,             # ★ 深度硬上限（用户要"3 跳及以上"，故给到 10）
    "max_nodes": 3000,           # ★ 结果上限（节点数）
    "max_edges": 8000,           # ★ 结果上限（边数）
    "max_seconds": 3.0,          # ★ 应用层时间预算
    "statement_timeout_ms": 5000,  # ★★ 数据库层保险 —— 由 PG 强制中断
}


def resolve_limits(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """合并预算配置：★ 内置默认 → `settings.ASTROLABE_NEIGHBORHOOD` → 调用方覆盖。"""
    cfg = dict(_DEFAULT_LIMITS)
    cfg.update(getattr(settings, "ASTROLABE_NEIGHBORHOOD", None) or {})
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def _set_statement_timeout(ms: int) -> None:
    """★ 「不卡死系统」的**最后一道保险** —— 由**数据库**强制中断，而不是靠应用自我克制。

    ⚠ 用 `set_config(..., is_local=true)` 而不是 `SET LOCAL` —— 因为 `SET` **不支持参数绑定**，
      拼字符串会有注入面。`is_local=true` ⇒ 只在当前事务内有效。
    """
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('statement_timeout', %s, true)", [str(int(ms))])


# ---------------------------------------------------------------------------
# ★ 一期实现：PostgreSQL 邻接表 + 两个索引（G3）
# ---------------------------------------------------------------------------

class PostgresAdjacencyReader:
    """一期实现 —— PostgreSQL 邻接表 + 两个索引（`G3`）。

    ★ 算法：**逐层 BFS**（⚠ 不是「递归 CTE + 路径数组」—— 原因见本模块 docstring）。

    ★★ 四道刹车（`G4`）：

    | # | 刹车 | 位置 |
    |---|---|---|
    | 1 | **访问集去重**（环 / 菱形依赖不会重复访问） | `visited` |
    | 2 | **深度硬上限** + **节点 / 边上限** | `max_depth` / `max_nodes` / `max_edges` |
    | 3 | 每层查询带 **LIMIT**（⚠ 不整层拉进内存） | `[:remaining + 1]` |
    | 4 | ★★ **`statement_timeout`**（数据库强制中断） | `_set_statement_timeout` |

    ⚠ 截断一律用**【确定性】策略**（按 vid 升序）—— 否则同一个查询两次跑出不同结果，
      缓存（`G5`）和前端分页都会失真。
    """

    def neighborhood(
        self,
        project_ref: str,
        node: int | str,
        *,
        depth: int | None = None,
        direction: str = DIRECTION_OUT,
        edge_types: Sequence[str] | None = None,
        limits: Mapping[str, Any] | None = None,
    ) -> SubGraph:
        if direction not in _DIRECTIONS:
            raise ValueError(f"direction 必须是 {_DIRECTIONS} 之一，收到 {direction!r}")

        cfg = resolve_limits(limits)
        requested = cfg["default_depth"] if depth is None else int(depth)
        depth = max(0, min(requested, int(cfg["max_depth"])))
        max_nodes = int(cfg["max_nodes"])
        max_edges = int(cfg["max_edges"])
        max_seconds = float(cfg["max_seconds"])

        started = time.monotonic()
        reasons: list[str] = []
        if requested > depth:
            reasons.append(f"深度压到硬上限 {depth}（请求 {requested}）")

        root_vid, ambiguous = _resolve_node(project_ref, node)
        if root_vid is None:
            return SubGraph(
                project_ref=project_ref,
                root=None,
                stats={"error": "节点不存在", "requested_depth": requested},
            )

        visited: dict[int, int] = {root_vid: 0}   # vid → 跳数
        seen_edges: set[tuple[int, int, str]] = set()
        edge_rows: list[tuple[int, int, str, int | None]] = []
        frontier: set[int] = {root_vid}
        levels = 0
        stop = False

        with transaction.atomic():
            _set_statement_timeout(cfg["statement_timeout_ms"])

            for level in range(1, depth + 1):
                if not frontier or stop:
                    break
                if time.monotonic() - started > max_seconds:
                    reasons.append(f"时间预算 {max_seconds:g}s 用尽")
                    break

                remaining_edges = max_edges - len(edge_rows)
                if remaining_edges <= 0:
                    reasons.append(f"边数达到上限 {max_edges}")
                    break

                qs = Edge.objects.filter(project_ref=project_ref)
                if direction == DIRECTION_OUT:
                    qs = qs.filter(from_node_id__in=frontier)
                elif direction == DIRECTION_IN:
                    qs = qs.filter(to_node_id__in=frontier)
                else:
                    qs = qs.filter(
                        Q(from_node_id__in=frontier) | Q(to_node_id__in=frontier)
                    )
                if edge_types:
                    qs = qs.filter(type__in=list(edge_types))

                # ★ 刹车 3：LIMIT —— 把这一层要读的行数硬性封顶
                chunk = list(
                    qs.values_list("from_node_id", "to_node_id", "type", "line")[
                        : remaining_edges + 1
                    ]
                )
                overflow = len(chunk) > remaining_edges
                if overflow:
                    chunk = chunk[:remaining_edges]

                nxt: set[int] = set()
                for src, dst, etype, line in chunk:
                    key = (src, dst, etype)
                    if key in seen_edges:      # ★ 刹车 1：边去重
                        continue
                    seen_edges.add(key)
                    edge_rows.append((src, dst, etype, line))
                    if src not in visited:
                        nxt.add(src)
                    if dst not in visited:
                        nxt.add(dst)

                # ★ 刹车 2：节点预算 —— ⚠ 必须【确定性】截断
                room = max_nodes - len(visited)
                new_ids = sorted(nxt)
                if len(new_ids) > room:
                    new_ids = new_ids[: max(room, 0)]
                    reasons.append(f"节点数达到上限 {max_nodes}")
                    overflow = True
                for nid in new_ids:
                    visited[nid] = level
                frontier = set(new_ids)
                levels = level

                if overflow:
                    break

        # ------------------------------------------------------------------ 收尾
        allowed = set(visited)
        # ⚠ 被预算砍掉的节点不能出现在边里 —— 否则前端拿到"悬挂边"（画不出来）
        final_edges = [r for r in edge_rows if r[0] in allowed and r[1] in allowed]

        # ★ 只取画图需要的字段（G4-3）
        node_rows = list(
            Node.objects.filter(project_ref=project_ref, node_id__in=list(allowed)).values(
                "node_id", "uid", "kind", "name", "file_path", "line", "line_end", "lang"
            )
        )

        # ★ 起点不存在 —— 在这里判定（省掉了预检的那次往返）
        if not any(r["node_id"] == root_vid for r in node_rows):
            return SubGraph(
                project_ref=project_ref,
                root=None,
                stats={"error": "节点不存在", "requested_depth": requested, "root": root_vid},
            )

        nodes = [
            GraphNode(
                vid=r["node_id"],
                uid=r["uid"],
                kind=r["kind"],
                name=r["name"],
                file_path=r["file_path"],
                line=r["line"],
                line_end=r["line_end"],
                lang=r["lang"],
                depth=visited[r["node_id"]],
            )
            for r in node_rows
        ]
        nodes.sort(key=lambda n: (n.depth, n.vid))

        edges = [
            GraphEdge(src=s, dst=d, type=t, line=ln) for (s, d, t, ln) in final_edges
        ]

        per_level: dict[int, int] = {}
        for n in nodes:
            per_level[n.depth] = per_level.get(n.depth, 0) + 1

        return SubGraph(
            project_ref=project_ref,
            root=root_vid,
            nodes=nodes,
            edges=edges,
            truncated=bool(reasons),
            truncated_reason="；".join(reasons),
            stats={
                "requested_depth": requested,
                "depth": depth,
                "levels_reached": levels,
                "nodes": len(nodes),
                "edges": len(edges),
                "per_level": per_level,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "direction": direction,
                "ambiguous_uid": ambiguous,
                "budget": {
                    "max_nodes": max_nodes,
                    "max_edges": max_edges,
                    "max_seconds": max_seconds,
                    "statement_timeout_ms": cfg["statement_timeout_ms"],
                },
            },
        )


def _resolve_node(project_ref: str, node: int | str) -> tuple[int | None, bool]:
    """把 `vid`(int) 或 `uid`(str) 解析成 `vid`。

    Returns:
        `(vid | None, 是否遇到 uid 重复)`

    ⚠ `uid` **允许重复**（`B117`）—— 命中多个时取**最小 vid**（确定性），
      并把"存在歧义"如实上报，❌ 不静默猜错。

    ★ 传 `int` 时**不做存在性预检** —— 那会白白多一次数据库往返（`G2` 对一跳的目标是毫秒级）；
      "起点不存在"由**最终节点集**判断（见调用处）。
    """
    if isinstance(node, int):
        return node, False

    rows = list(
        Node.objects.filter(project_ref=project_ref, uid=str(node)).values_list(
            "node_id", flat=True
        )[:2]
    )
    if not rows:
        return None, False
    return rows[0], len(rows) > 1


def resolve_node(project_ref: str, node: int | str) -> tuple[int | None, bool]:
    """★ 公开入口：把 `vid`(int) 或 `uid`(str) 解析成 `vid`。

    ★ 缓存层也要用它 —— 否则「同一个节点用 uid 写」和「用 vid 写」
      会各自缓存一份（重复占内存，两份额度还可能不同步）。
    """
    return _resolve_node(project_ref, node)


# ---------------------------------------------------------------------------
# 注册表：★ 换图数据库只改 settings 里的一行字符串
# ---------------------------------------------------------------------------

_readers: dict[str, GraphReader] = {}


def get_reader() -> GraphReader:
    """取当前配置的图读取器（★ 已按需套上 Redis 缓存）。

    ★ 依据 `settings.ASTROLABE_GRAPH_READER`（默认 = 一期 PG 实现）。
    ✅ 将来接 Neo4j：`ASTROLABE_GRAPH_READER = "graph.neo4j.Neo4jReader"`
      —— **调用方一行都不用改**。

    ⚠ 缓存用**装饰器**套在实现外面（`graph/cache.py` 的 `CachedGraphReader`）——
      ⇒ ★ 换图库时缓存**不用重做**；关缓存只改配置，❌ 不用动这个类。
    ⚠ 延迟 import：`graph.cache` 依赖本模块的类型 ⇒ 放在函数内避免循环 import。
    """
    path = getattr(
        settings, "ASTROLABE_GRAPH_READER", "graph.traversal.PostgresAdjacencyReader"
    )
    if path not in _readers:
        inner = import_string(path)()

        from graph.cache import CachedGraphReader, cache_enabled

        _readers[path] = CachedGraphReader(inner) if cache_enabled() else inner
    return _readers[path]


def neighborhood(
    project_ref: str,
    node: int | str,
    *,
    depth: int | None = None,
    direction: str = DIRECTION_OUT,
    edge_types: Sequence[str] | None = None,
    limits: Mapping[str, Any] | None = None,
) -> SubGraph:
    """★ 便捷入口 —— ① Web 层用这个（不必关心用的是哪个实现）。

    ★★ **访问热度只在这里记**（邻域查询的**起点** = 用户点开的那个节点），
      原因：
      · ❌ 不记返回的每个节点 —— 一次点击可能带出 3000 个节点，**一记就失真**
      · ❌ 不在 `get_reader()` 上记 —— 调试命令 / 内部诊断跑遍历**不该污染热度**
    """
    sg = get_reader().neighborhood(
        project_ref,
        node,
        depth=depth,
        direction=direction,
        edge_types=edge_types,
        limits=limits,
    )

    # ★ 热度按 uid 记（跨重新解析稳定）—— 见 graph/cache.py 的说明
    if sg.root is not None:
        uid = next((n.uid for n in sg.nodes if n.vid == sg.root), "")
        if uid:
            from graph import cache as _cache

            _cache.record(project_ref, uid)

    return sg
