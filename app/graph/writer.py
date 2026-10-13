"""Astrolabe · 图写入方

★ 依据：
    `GRAPH-STORAGE.md` G1   —— 图不可变；★ **服务端解析作业是唯一的图写入者**
    `GRAPH-STORAGE.md` G3   —— 邻接表 + 两个索引（正向 / 反向）
    `GRAPH-STORAGE.md` G3.5 —— 三层标识（`B117`）：`node_id` 发号（= `vid`）；`uid` 只做可读标签
    `GRAPH-SCHEMA.md` S2/S3 —— 节点 / 边字段

⚠ 分层纪律（`ARCHITECTURE.md` A3）：
    ★ 本模块【**只允许 ② 作业层调用**】—— ❌ ① Web 层**不得直接写图**，
      跨层只通过【Job 表 + 队列】通信。

★★ 两条必须守住的规则：
    ① **引用最终一律落到节点主键**（`B117` / `B120`）——
      ❌ 不用 `uid` 字符串做挂载依据（`uid` 允许重复）
    ② **不认识、解析不出来的引用 —— 跳过并计数，❌ 不猜、不瞎连**
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from codeparser.base import ParseResult
from graph.models import BaseGraph, Edge, Node

#: 解析器给出的「延迟解析引用」前缀（约定见 `codeparser/base.py` 的 `ParsedEdge`）
_UNRESOLVED = "unresolved#"

#: 归属 kind（用于 `unresolved#call#` 的名字索引）
_CALLABLE_KINDS = ("function", "method")


@dataclass(slots=True)
class WriteStats:
    """写图统计 —— ★ 用于作业进度与诊断，不进图。"""

    nodes_written: int = 0
    nodes_deduped: int = 0
    edges_written: int = 0
    edges_skipped: int = 0
    #: ★ 写入后的图版本号 —— 邻域缓存的命名空间代际（G5）
    rev: int = 0
    #: 少量「解析不出来的引用」样本（便于排查，⚠ 只要样本，不要全量）
    unresolved_samples: list[str] = field(default_factory=list)


@dataclass
class _Index:
    """引用索引 —— 由已写入的节点构建，供边的引用解析使用。"""

    by_uid: dict[str, Node]
    by_name: dict[str, list[Node]]
    by_file_path: dict[str, Node]
    by_file_basename: dict[str, list[Node]]
    by_file_stem: dict[str, list[Node]]

    @classmethod
    def build(cls, nodes: dict[str, Node]) -> "_Index":
        by_name: dict[str, list[Node]] = {}
        by_file_path: dict[str, Node] = {}
        by_file_basename: dict[str, list[Node]] = {}
        by_file_stem: dict[str, list[Node]] = {}

        for node in nodes.values():
            if node.kind in _CALLABLE_KINDS:
                by_name.setdefault(node.name, []).append(node)
            elif node.kind == "file":
                by_file_path[node.file_path] = node
                base = node.file_path.rsplit("/", 1)[-1]
                by_file_basename.setdefault(base, []).append(node)
                # ★ 文件主干名 —— 用于把「模块名」对上「文件」
                #   （Python 的 `from .base import X` → 模块 base → 文件 base.py）
                by_file_stem.setdefault(base.rsplit(".", 1)[0], []).append(node)

        return cls(
            by_uid=nodes,
            by_name=by_name,
            by_file_path=by_file_path,
            by_file_basename=by_file_basename,
            by_file_stem=by_file_stem,
        )


class GraphImmutable(Exception):
    """★★ **图已定版，拒绝覆盖**（`B103` / `B155`）。

    > **用户原话**：「代码解析完成之后**应该不允许重新解析**。因为，我要求
    > **图数据不能频繁、大面积改动**，**代码也不能改动**，否则，
    > **解释里的"几行到几行"就失效了**。」

    ★ 两条出路：★ **要另一个版本 ⇒ 新建项目**；★ **质量差 ⇒ 删了重建**。
    """


def write_graph(
    base_graph: BaseGraph,
    result: ParseResult,
    *,
    replace: bool = False,
    replace_reason: str = "",
) -> WriteStats:
    """★★ **把一份解析产物写进【基图】**（★ `B179` · 2026-10-13）。

    ## ⚠★★ `B179` 改了什么（★ 这一条是本函数的全部变化）

    | | `B179` 之前 | `B179` 之后 |
    |---|---|---|
    | ★ 挂在谁身上 | ★ 一个**项目**（`project_ref`）| ★★ 一份**基图**（★ 按【仓库 + sha】—— 不属于任何用户 ⚠）|
    | ★ 一份产物几个项目用 | ★ 一个（★ 换个项目就**重新解析** ⚠）| ★★ **所有同 sha 的项目共用** ✅ |
    | ★ 定版标记 | ★ `Project.graph_built_at` | ★ `BaseGraph.built_at`（★ 项目那边在**绑定时**置）✅ |

    ⚠ **原子性**：整个过程在一个事务里 —— 要么全成功，要么全不留痕。

    ★★ **基图一经写入即【定版】（`B103` / `B155` 的口径沿用到基图）**：

    | 情况 | 行为 |
    |---|---|
    | ★ 这份基图**还没建** | ✅ 正常写入，并**钉住 `built_at`** |
    | ★★ **已经建好了** | ★★ **`raise GraphImmutable`**（❌ **不是**"先删后写"） |

    ⚠★ **为什么默认"拒绝"而不是"覆盖"**：★ 图一旦生成，**解释 / 提问 / 阅读路径
      全挂在「文件 + 行区间」上**（`B98` 的 L0）；⚠ 重新解析会让那些行号**全部错位**
      —— ★★ 而**没有任何机制能自动发现**。

    ⚠★★ **`replace=True` 的杀伤面变大了**（★ 如实说明）：★ 以前它只影响**一个项目**；
      ★★ 现在它影响**所有绑在这份基图上的项目** ⚠ ⇒ ★★ **生产路径上绝不能用** ⚠
      （★ 只留给调试，★ 且必须给 `replace_reason` —— ★ 让"谁覆盖过"留得下痕迹）

    Args:
        base_graph: ★ 要写哪一份基图（★ 由调用方按【仓库 + sha】取好 —— 见 `jobs/tasks.py`）
        result: 解析产物（可能来自多个文件，已汇总）
        replace: ⚠★ **仅供调试** —— 见上（★ 生产路径一律用默认值 `False`）
        replace_reason: ★ `replace=True` 时必填（⚠ 会写进审计日志）
    """
    stats = WriteStats()

    with transaction.atomic():
        # ---------------------------------------------------------- ⓪ ★★★ 定版闸门
        #   ⚠★ **已经建好 ⇒ 拒绝**（❌ 不是"先删后写"）——
        #     ★ 见函数文档：重新解析会让**解释里的行区间全部错位**，⚠ 而没人能发现。
        #   ⚠ 用 `select_for_update` 锁住**基图**那一行 ⇒ ★ **两个并发的解析作业
        #     不会双双通过**（⚠ 典型的 check-then-use）——
        #     ★ 与 `B149` 的 `claim_job` 是同一类问题、同一类解法。
        bg = BaseGraph.objects.select_for_update().filter(pk=base_graph.pk).first()
        if bg is None:
            raise GraphImmutable("这份基图已经不在了（可能被并发删掉了）。")

        if Node.objects.filter(base_graph=bg).exists():
            if not replace:
                raise GraphImmutable(
                    "这份基图已经建好了，不会重新生成。"
                    "★ 要看别的版本，请换一个分支 / tag 再拉一次。"
                )
            if not (replace_reason or "").strip():
                # ★★ 强制留痕 —— ⚠ 否则"图被覆盖过"这件事**事后查不出来**
                raise ValueError("replace=True 必须给出 replace_reason（⚠ 会写进审计日志）")
            Edge.objects.filter(base_graph=bg).delete()
            Node.objects.filter(base_graph=bg).delete()

        # ---------------------------------------------------------- ① 节点
        seen: dict[str, Node] = {}
        for pn in result.nodes:
            if pn.uid in seen:
                # ⚠ 同一批里 uid 重复（例如宏重定义）—— 归为一个逻辑节点，
                #   这样边引用才不会有歧义（B117：uid 允许重复，但要能稳定匹配）
                stats.nodes_deduped += 1
                continue
            seen[pn.uid] = Node(
                # ★★ `B179`：挂【基图】—— ★ 不再挂项目、也不再有 `origin` 列 ⚠
                #   （★ 基图行【必然】是"解析出来的"，★ 不需要一列去记它）
                base_graph=bg,
                uid=pn.uid,
                kind=pn.kind,
                name=pn.name[:512],
                qname=(pn.qname or "")[:512],
                file_path=pn.file_path[:1024],
                line=pn.line,
                line_end=pn.line_end,
                lang=pn.lang,
                signature=(pn.signature or "")[:512],
                # ⚠★ `B176`：此处曾写 `doc=pn.doc or ""` —— ★ 随 `ParsedNode.doc` 一并删除 ✅
                extra=pn.extra or {},
            )

        # ★ PostgreSQL 上 bulk_create 会回填主键 —— 这就是 vid（B117）
        Node.objects.bulk_create(list(seen.values()), batch_size=1000)
        stats.nodes_written = len(seen)

        index = _Index.build(seen)

        # ---------------------------------------------------------- ② 边
        # ★★★ `B176` ④：**传染性许可（GPL 等）⇒ 只出节点、不自动生成调用关系** ⚠
        #   ★ 所有者原话：「**GPL 项目不解析，但生成节点图，不生成调用关系**」⚠
        #   ★★ 判据写在**基图**上（★ 作业在许可核验时置好 —— ★ 见 `jobs/tasks.py`）⚠
        #   ★ 这样做是刻意的：★ 边是"对**代码结构**的提取"，★ 而那正是那条争议最大的一块 ⚠
        edges: list[Edge] = []
        if not bg.edges_generated:
            # ⚠ 如实计数（★ 不静默丢掉）：★ 前端要能解释"为什么没有连线" ⚠
            stats.edges_skipped += len(result.edges)
        else:
            for pe in result.edges:
                from_node = _resolve(pe.from_uid, index, stats)
                to_node = _resolve(pe.to_uid, index, stats)
                if from_node is None or to_node is None:
                    stats.edges_skipped += 1
                    continue
                if from_node.pk == to_node.pk:
                    # 自环对"发散思维"没有价值，且多半是解析噪声
                    stats.edges_skipped += 1
                    continue
                edges.append(
                    Edge(
                        base_graph=bg,
                        from_node=from_node,
                        to_node=to_node,
                        type=pe.type,
                        line=pe.line,
                        confidence=(pe.confidence or "")[:16],
                        extra=pe.extra or {},
                    )
                )

            Edge.objects.bulk_create(edges, batch_size=1000)
        stats.edges_written = len(edges)

        # ---------------------------------------------------------- ★★★ 定版
        #   ★★ **与写图同一个事务** —— ⚠ 分开做就会出现"图写了、标记没置"的窗口，
        #     ★ 那个窗口里再投一次作业 ⇒ **图被覆盖**（★ 正是这一条要防的事）。
        from django.utils import timezone

        bg.node_count = stats.nodes_written
        bg.edge_count = stats.edges_written
        bg.built_at = timezone.now()
        bg.save(update_fields=["node_count", "edge_count", "built_at", "updated_at"])

        if replace:
            # ⚠ 覆盖是**例外** ⇒ ★ 必须留痕（★ 见函数文档）
            from core.models import AuditLog

            AuditLog.objects.create(
                action="base_graph.replaced",
                target_kind="BaseGraph",
                target_id=str(bg.pk),
                detail={
                    "repo": f"{bg.provider}:{bg.repo_full_name}@{bg.sha[:12]}",
                    "reason": replace_reason[:500],
                    "nodes": len(result.nodes),
                },
            )

        # ⚠★★ 邻域缓存的失效**挪到了"项目绑定基图"那一步**（★ `B179`）——
        #   ★ 缓存命名空间是【按项目】的（`GraphRevision.project_ref`）⚠
        #   ★★ 而基图是**共享**的 ⇒ ★ 在这里 bump 会**不知道该 bump 谁** ⚠
        #   ★ 绑定时 bump 一次即可（★ 见 `graph/binding.py`）✅

    return stats


# ---------------------------------------------------------------------------
# 引用解析
# ---------------------------------------------------------------------------

def _note(stats: WriteStats, ref: str) -> None:
    """记一条「解析不出来的引用」样本（⚠ 只要样本，避免刷爆内存）。"""
    if len(stats.unresolved_samples) < 50:
        stats.unresolved_samples.append(ref)


def _resolve(ref: str, index: _Index, stats: WriteStats) -> Node | None:
    """把一个引用解析成节点；解析不出来返回 None（★ 不猜）。

    约定（见 `codeparser/base.py`）：

    | 引用形态 | 含义 | 解析方式 |
    |---|---|---|
    | `<kind>#<path>#<name>` | 真实 uid | 直接查索引 |
    | `unresolved#call#<name>` | 调用目标 | ★ 按函数名匹配（同名取**路径最短**者，保证确定性） |
    | `unresolved#include#<target>` | 包含 / 导入 | 按文件名匹配 file 节点 |
    | `unresolved#in#<path>` | 回落的归属文件（旧写法） | 按路径匹配 file 节点 |
    """
    if not ref:
        return None

    if not ref.startswith(_UNRESOLVED):
        return index.by_uid.get(ref)

    parts = ref.split("#", 2)
    what = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""

    if what == "call":
        candidates = index.by_name.get(value) or []
        if not candidates:
            _note(stats, ref)
            return None
        # ★ 同名多个（重载 / 跨文件同名）⇒ 取路径最短的，保证同一输入结果稳定
        return min(candidates, key=lambda n: (len(n.file_path), n.file_path, n.line))

    if what == "include":
        raw = value.strip().strip('<>"').strip()
        if raw:
            last = raw.rsplit("/", 1)[-1]
            # ★ 分层匹配 —— 依次是 C 的头文件名 / 路径末段 / 模块名 / 末段去扩展名
            for candidates in (
                index.by_file_basename.get(raw),                  # stdio.h
                index.by_file_basename.get(last),                 # sys/stat.h → stat.h
                index.by_file_stem.get(raw.rsplit(".", 1)[-1]),   # .base → base · java.util.List → List
                index.by_file_stem.get(last.rsplit(".", 1)[0]),   # 兜底：末段去扩展名
            ):
                if candidates:
                    return min(candidates, key=lambda n: (len(n.file_path), n.file_path))
        _note(stats, ref)
        return None

    if what == "in":
        node = index.by_file_path.get(value)
        if node is None:
            _note(stats, ref)
        return node

    _note(stats, ref)
    return None
