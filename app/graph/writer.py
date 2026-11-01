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
from codeparser.postpass import reparent_contains
from graph import identity, kinds
from graph.models import BaseGraph, Edge, Node, Repo

#: 解析器给出的「延迟解析引用」前缀（约定见 `codeparser/base.py` 的 `ParsedEdge`）
_UNRESOLVED = "unresolved#"

#: 归属 kind（用于 `unresolved#call#` 的名字索引）
_CALLABLE_KINDS = (kinds.KIND_IDS["function"], kinds.KIND_IDS["method"])


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
    #: ★ 作用域归位：把多少条 contains 边从"词法父级"改挂到"名字所指的类"下
    scope_moved: int = 0


@dataclass
class _Index:
    """引用索引 —— 由已写入的节点构建，供边的引用解析使用。"""

    by_uid: dict[str, Node]
    by_qname: dict[str, list[Node]]
    by_name: dict[str, list[Node]]
    by_file_path: dict[str, Node]
    by_file_basename: dict[str, list[Node]]
    by_file_stem: dict[str, list[Node]]

    @classmethod
    def build(
        cls, nodes: dict[str, Node], qname_by_uid: dict[str, str] | None = None
    ) -> "_Index":
        """★ 建索引 —— `qname` 优先取**本次解析产物**（`qname_by_uid`）⚠

        ⛔ 不取 `Node.qname`：那是"基准值"，可能属于别的版本；
          用它建名字索引会让跨版本的限定调用接错节点。
        """
        by_qname: dict[str, list[Node]] = {}
        by_name: dict[str, list[Node]] = {}
        by_file_path: dict[str, Node] = {}
        by_file_basename: dict[str, list[Node]] = {}
        by_file_stem: dict[str, list[Node]] = {}

        qname_by_uid = qname_by_uid or {}
        for uid, node in nodes.items():
            qname = qname_by_uid.get(uid) or node.qname
            if qname:
                by_qname.setdefault(qname, []).append(node)
            if node.kind in _CALLABLE_KINDS:
                by_name.setdefault(node.name, []).append(node)
            elif node.kind == kinds.KIND_IDS["file"]:
                by_file_path[node.file_path] = node
                base = node.file_path.rsplit("/", 1)[-1]
                by_file_basename.setdefault(base, []).append(node)
                # ★ 文件主干名 —— 用于把「模块名」对上「文件」
                #   （Python 的 `from .base import X` → 模块 base → 文件 base.py）
                by_file_stem.setdefault(base.rsplit(".", 1)[0], []).append(node)

        return cls(
            by_uid=nodes,
            by_qname=by_qname,
            by_name=by_name,
            by_file_path=by_file_path,
            by_file_basename=by_file_basename,
            by_file_stem=by_file_stem,
        )


def _canonical(pn) -> str:
    """★ 规范串（* 唯一实现见 `graph/identity.py`）⚠"""
    return identity.canonical(pn.kind, pn.file_path, pn.name, pn.line, pn.line_end)


class EmptyGraph(Exception):
    """★★ **解析出 0 个节点** ⇒ 不能做基图 ⚠

    ## ★★★ 所有者裁定（2026-10-17，* 逐字）

    > 「**节点为零，还要什么基图，空的还能叫基图吗？解析出节点为零的，不能做基图。**」

    ```
    ★★ 所以：* `stats.nodes_written == 0` ⇒ **直接抛**（* 不置 `built_at`）⚠
      · · ★ 事务回滚 ⇒* 什么都没写（* 没有半张空图）✅
      · · ★★ 作业层接住后**把这份基图行也删掉**（* 它还没被任何项目绑定）✅
    ```
    """


class GraphImmutable(Exception):
    """★★ **图已定版，拒绝覆盖**（`B103` / `B155`）。

    > **用户原话**：「代码解析完成之后**应该不允许重新解析**。因为，我要求
    > **图数据不能频繁、大面积改动**，**代码也不能改动**，否则，
    > **解释里的"几行到几行"就失效了**。」

    ★ 两条出路：★ **要另一个版本 ⇒ 新建项目**；★ **质量差 ⇒ 删了重建**。
    """


def write_graph(base_graph: BaseGraph, result: ParseResult) -> WriteStats:
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

    ⚠★★ **没有"重新解析"这条路**（2026-11-01 所有者重申：「**我说了，不允许重新解析**」）：
      曾经的 `replace=True`（"仅调试"后门）**已整段删除** ——
      ★ 它一按下去就把**所有绑在这份基图上的项目**的行区间全部打错，且没人能发现 ⚠
      ★ 要另一个版本 ⇒ **新建基图/项目**；质量差 ⇒ **删了重建**。

    Args:
        base_graph: ★ 要写哪一份基图（★ 由调用方按【仓库 + sha】取好 —— 见 `jobs/tasks.py`）
        result: 解析产物（可能来自多个文件，已汇总）
    """
    # ★★ 类外定义归位（`void C::f(){}` 应挂在 C 下，而不是词法父级）⚠
    #   ⚠ 与个人版 `parser_bridge` 调的是**同一份规则**（app/codeparser/postpass.py），
    #     避免两版各写一套、结果不一致
    scope_stats = reparent_contains(result)

    stats = WriteStats()
    stats.scope_moved = scope_stats["moved"]

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

        # ★★★ 定版闸门（`B220` 之后节点不再挂基图 ⇒* 用 `built_at` 判）⚠
        #
        # ⚠★★ **没有 replace / force 这条路**（2026-11-01 所有者重申：
        #   「**我说了，不允许重新解析**」）——
        #   曾经的 `replace=True`（"仅调试"）已**整段删除**：
        #   · ★ 它是一扇"一不小心就把整份基图换掉"的后门，而且换掉之后
        #     **解释里的行区间全部错位，没人能发现** ⚠
        #   · ★ 要另一个版本 ⇒ **新建项目/新基图**；质量差 ⇒ 删了重建
        if bg.built_at is not None:
            raise GraphImmutable(
                "这份基图已经建好了，不会重新生成。"
                "★ 要看别的版本，请换一个分支 / tag 再拉一次。"
            )

        # ---------------------------------------------------------- ⓪-1 ★★ 仓库（`B220`）
        repo, _ = Repo.objects.get_or_create(
            provider=bg.provider, repo_full_name=bg.repo_full_name
        )

        # ---------------------------------------------------------- ① 节点
        seen: dict[str, Node] = {}
        parsed = []
        for pn in result.nodes:
            if pn.uid in seen:
                # ⚠ 同一批里 uid 重复（宏重定义等）⇒ 归为一个逻辑节点，边引用才无歧义
                stats.nodes_deduped += 1
                continue
            parsed.append(pn)
            seen[pn.uid] = None  # 占位（下面填真对象）

        vids = identity.assign_vids([_canonical(p) for p in parsed])
        existing = {
            n.stable_vid: n
            for n in Node.objects.filter(repo=repo, stable_vid__in=list(vids.values()))
        }

        to_create: list[Node] = []
        for pn in parsed:
            vid = vids[_canonical(pn)]
            node = existing.get(vid)
            if node is None:
                node = Node(
                    repo=repo,
                    stable_vid=vid,
                    versions=[bg.pk],
                    uid=pn.uid,
                    kind=kinds.kind_id(pn.kind),
                    name=pn.name[:512],
                    qname=(pn.qname or "")[:512],
                    file_path=pn.file_path[:1024],
                    line=pn.line,
                    line_end=(pn.line_end if pn.line_end is not None else -1),
                    lang=pn.lang,
                    signature=(pn.signature or "")[:512],
                    extra=pn.extra or {},
                )
                to_create.append(node)
                existing[vid] = node
            else:
                # ★★ 复用：* 这个版本里也有同一个节点（* 内容身份相同）⇒ 共用一行，省存储 ⚠
                #
                # ★★★ 会随版本变的东西**一律进 `version_attrs`**（`{bg_id: {...}}`）⚠
                #   为什么不能直接改 `signature` / `qname` 这两列：
                #   · 这两列是**基准值**（最早写这个节点的那份），其它版本都靠它兜底
                #   · 改了基准 ⇒ 先写的那个版本（它没有 map 键）会显示后写版本的值
                #     ⇒ 看起来合理、其实是串版本，最难发现的那种错
                fields: list[str] = []
                if bg.pk not in node.versions:
                    node.versions = sorted(set(node.versions) | {bg.pk})
                    fields.append("versions")

                new_sig = (pn.signature or "")[:512]
                new_qname = (pn.qname or "")[:512]

                # 老数据：基准是空的 ⇒ 用本次值补上（这不算"差异"）
                if not (node.signature or "") and new_sig:
                    node.signature = new_sig
                    fields.append("signature")
                if not (node.qname or "") and new_qname:
                    node.qname = new_qname
                    fields.append("qname")

                # 再把"与基准不同"的部分记进这个版本的键里（相同就不写，省存储）
                diff: dict[str, str] = {}
                if new_sig and new_sig != (node.signature or ""):
                    diff["sig"] = new_sig
                if new_qname and new_qname != (node.qname or ""):
                    diff["qname"] = new_qname

                attrs = dict(node.version_attrs or {})
                key = str(bg.pk)
                if diff:
                    attrs[key] = diff
                else:
                    attrs.pop(key, None)   # 与基准相同 ⇒ 不留空壳
                if (node.version_attrs or {}) != attrs:
                    node.version_attrs = attrs
                    fields.append("version_attrs")

                if fields:
                    node.save(update_fields=[*fields, "updated_at"])
            seen[pn.uid] = node

        # ★ PostgreSQL 上 bulk_create 会回填主键（* 边解析要用）✅
        Node.objects.bulk_create(to_create, batch_size=1000)
        stats.nodes_written = len(parsed)

        # ★★ 名字索引必须用**本次解析产物**的 qname ⚠
        #   ⛔ 不能读 `Node.qname`：那是基准值，可能属于别的版本
        #   ⇒ 用错的话，跨版本的限定调用（`self.f()` / `A.f()`）会接到错的节点上
        index = _Index.build(seen, qname_by_uid={pn.uid: pn.qname for pn in parsed})

        # ---------------------------------------------------------- ② 边
        # ★★★ `B176` ④：**传染性许可（GPL 等）⇒ 只出节点、不生成调用关系** ⚠
        edges_to_create: list[Edge] = []
        version_edges = 0

        if not bg.edges_generated:
            # ⚠ 如实计数（不静默丢掉）：前端要能解释「为什么没有连线」
            stats.edges_skipped += len(result.edges)
        else:
            pks = [n.node_id for n in seen.values() if n is not None and n.pk]
            existing_edges: dict[tuple, Edge] = {}
            if pks:
                for e in Edge.objects.filter(
                    repo=repo, from_node_id__in=pks, to_node_id__in=pks
                ):
                    existing_edges[(e.from_node_id, e.to_node_id, e.type, e.line)] = e

            for pe in result.edges:
                from_node = _resolve(pe.from_uid, index, stats)
                to_node = _resolve(pe.to_uid, index, stats)
                if from_node is None or to_node is None:
                    stats.edges_skipped += 1
                    continue
                if from_node.pk == to_node.pk:
                    # 自环对「发散思维」没价值，且多半是解析噪声
                    stats.edges_skipped += 1
                    continue

                line = pe.line if pe.line is not None else -1
                key = (from_node.pk, to_node.pk, pe.type, line)
                edge = existing_edges.get(key)
                if edge is None:
                    edge = Edge(
                        repo=repo,
                        versions=[bg.pk],
                        from_node=from_node,
                        to_node=to_node,
                        type=pe.type,
                        line=line,
                        confidence=(pe.confidence or "")[:16],
                        extra=pe.extra or {},
                    )
                    edges_to_create.append(edge)
                    existing_edges[key] = edge
                elif bg.pk not in edge.versions:
                    edge.versions = sorted(set(edge.versions) | {bg.pk})
                    edge.save(update_fields=["versions", "updated_at"])
                version_edges += 1

            Edge.objects.bulk_create(edges_to_create, batch_size=1000)

        stats.edges_written = version_edges

        # ---------------------------------------------------------- ★★★ 空图拒收
        #   ★★ 所有者裁定（2026-10-17）：「**节点为零，还要什么基图，空的还能叫
        #      基图吗？解析出节点为零的，不能做基图。**」
        #   ⇒ ★ 0 节点**不置 `built_at`**、直接抛 ⇒ 事务回滚（* 什么都没写）⚠
        if stats.nodes_written == 0:
            raise EmptyGraph(
                "没有解析出任何代码节点 —— 这个仓库可能没有支持的源文件"
                "（或解析器不支持这种语言）。"
            )

        # ---------------------------------------------------------- ★★★ 定版
        #   ★★ **与写图同一个事务** —— ⚠ 分开做就会出现"图写了、标记没置"的窗口，
        #     ★ 那个窗口里再投一次作业 ⇒ **图被覆盖**（★ 正是这一条要防的事）。
        from django.utils import timezone

        bg.node_count = stats.nodes_written
        bg.edge_count = stats.edges_written
        bg.built_at = timezone.now()
        bg.save(update_fields=["node_count", "edge_count", "built_at", "updated_at"])

        # ★★ 基图变了 ⇒ 绑定它的项目计数都要重算（`2026-10-23` 所有者要求落列）⚠
        try:
            from core import project_counts

            project_counts.refresh(base_graph_id=bg.pk)
        except Exception:
            pass

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

    if what in ("qcall", "type"):
        # ★★ 限定调用（`a.run` / `ns::f`）与基类（`extends` / `implements`）⚠
        #   ⚠ 这两种引用以前**只有个人版认识**（`parser_bridge`），网页版走到这里
        #     会落到 `_note(stats, ref)` 被丢掉 ⇒ 网页版一条限定调用、一条继承边都没有（踩到）
        #   判准与个人版一致：限定名精确唯一 ⇒ 连；否则退到"名字唯一"；再不行就不连。
        exact = index.by_qname.get(value) or []
        if len(exact) == 1:
            return exact[0]
        plain = index.by_name.get(value.rsplit("::", 1)[-1].rsplit(".", 1)[-1]) or []
        if len(plain) == 1:
            return plain[0]
        _note(stats, ref)
        return None

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
