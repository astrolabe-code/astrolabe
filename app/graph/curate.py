"""Astrolabe · 图：**维护者手工修补**（`GRAPH-STORAGE.md` G1 · 主文 `§2.3.12`）

---

# ★★★ 谁可以修补 —— ★ **项目创建者自己**，❌ 不是管理员代劳

> **用户原话（`B157`）**：「**修补节点是项目创建者自己修补，不是我这个管理员帮他修补。**
> 所以，**必须在网页上能操作**。」

★ 主文 `§2.3.11` 的权限矩阵：

| 角色 | 能否修补图 |
|---|---|
| ★★ **项目维护者**（`can_edit` = **owner** + `share_user_ids`） | ✅ **可以** —— ★ **这是主路径** |
| ⚠ **网站管理员**（`is_staff`） | ⚠ 也可以（`§2.3.11`：「可删 / 修**任何**项目下的」）—— ★ **但那是「平台介入」，性质与前者不同** |
| ❌ 其他任何用户 | ❌ **`403`**（★ 但可**提勘误建议**，`§2.3.12` 的「轻」通道） |

## ★★ 一期口径：`can_edit` = **owner**（或 `is_staff`），❌ 不做协作者

⚠★ 这里有个**真实的口径冲突**，如实记录并裁定：

| 出处 | 说法 |
|---|---|
| 主文 `§2.3.11` / `§2.3.12` | `can_edit = owner + share_user_ids`（**可多人**） |
| `web/permissions.py`（**现行代码**） | ⚠ **一期没有协作者** ⇒ `can_edit` = **仅 owner**（或 staff） |

★★ **一期按「仅 owner」**（★ 与 `web/permissions.py` 及 `PRODUCT-VERSIONS` 一致），
★ 而 `share_user_ids` 是**将来**的事 —— ⚠ 但 `can_curate()` 的**签名与语义不变**，
将来加协作者**只改这一个函数** ✅

## ★★ 「管理员代改」必须在审计里**看得出来**

★ 两者的**性质不同**：★ owner 改自己的图是**行使所有权**；★ `is_staff` 改别人的图是**平台介入**。
⇒ ★★ 所以 `via_admin` 会**写进审计** —— ⚠ 否则事后分不清"是他自己改的"还是"我们改的"。

---

# ★★ 批量：一次操作 = **一个事务 + 一条审计 + bump 一次**

★ 契约（`frontend-contract.md` §2）定的是：

```
POST /api/projects/<project_ref>/graph/edit/
body: {base_graph_rev?, changes: [ {action, ...}, ... ]}
resp: {ok, data: {graph_rev, applied}}
```

★★★ 为什么**必须**是"一批"而不是"一条一条发"：

| | 一条一发 | ★★ 一批 |
|---|---|---|
| ★ 事务 | ⚠ N 个事务 ⇒ **改到一半失败 = 半个修补** | ✅ **要么全成、要么全不成** |
| ★ 审计 | ⚠ N 条记录 ⇒ ⚠ **看不出是一件事** | ✅ **一条**，看得出"他一次干了什么" |
| ★★ `graph_rev` | ⚠★ **跳 N 次** ⇒ 邻域缓存**反复失效** | ✅ **只 +1** |

⇒ ★ 所以单条函数（`add_node` / …）都是 `apply_changes(changes=[一条])` 的**薄包装**
  —— ★★ **只有一条路径**（⚠ 两套逻辑早晚会不一致）。

---

# ★★★ 四条规则（`§2.3.12`）

| # | 规则 | 本条如何落实 |
|---|---|---|
| **1** | ★ **直接改图**，不做「叠加层」 | ★ 直接 `Node` / `Edge` 的增删改 ✅ |
| **2** | ★ 带 `origin = parsed ｜ manual`，**UI 上人工项有视觉标记** | ★ 每条写入都标 `manual` ✅（★ 数据已备好，前端直接看 `origin`） |
| **3** | ★ **零并发控制**：LWW，无 CAS、无租约、无合并 | ★ **不加锁**（⚠ 与 `write_graph` 的 `select_for_update` **刻意不同**） |
| **4** | ★★★ **但必须有全量审计**：谁 / 何时 / 加了删了什么 / **为什么** | ★ 见下 |

★★★ 第 4 条的理由，是本模块**最重要的一句话**（主文 `§2.3.12` 原文）：

> **「用户全权负责」的技术前提就是「可追溯」——**
> **没有审计，「全权负责」就变成「没人负责」。**

⇒ ★★ 这就是 `by` 与 `reason` **必填**的立法理由，★ 而不是"流程规定"。

---

# ★★ `base_graph_rev`：**可选**，且**不是强一致保证**

★ 契约明确「**由必需降为可选**」（缺省 = LWW，不做冲突协商）。
★★ 所以：★ 传了 ⇒ 开头比对一次，不匹配就 `409 stale_rev`（★ 让前端提示"图变了，请重读"）；
  ★ 不传 ⇒ ★ **直接照做**（★ 因为 `§2.3.11` 说并发概率 ≈ 0）。

⚠★ 如实说明：★ 这个比对**没有加锁** ⇒ ★ **它不是 CAS，是善意提示**。
  ★★ 真要强一致就得锁行 —— ⚠ 而那是 `§2.3.11` 明确不要的（「**为不存在的前提付保费**」）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.utils import timezone

from graph import revision
from graph.models import ORIGIN_MANUAL, Edge, Node

#: ★ 允许修补的节点字段（★ **白名单**，❌ 不是"传什么改什么"）——
#: ⚠ `node_id` / `project_ref` / `origin` / 时间戳**不在其中**（★ 它们不是"内容"）
_NODE_FIELDS: tuple[str, ...] = (
    "kind", "name", "qname", "file_path", "line", "line_end",
    "lang", "signature", "doc", "extra",
)

#: ★ 允许修补的边字段
_EDGE_FIELDS: tuple[str, ...] = ("type", "line", "confidence", "extra")

#: ★★ **六类动作**（★ 契约 `changes[].action` 的取值）
ACTION_ADD_NODE = "add_node"
ACTION_UPDATE_NODE = "update_node"
ACTION_REMOVE_NODE = "remove_node"
ACTION_ADD_EDGE = "add_edge"
ACTION_UPDATE_EDGE = "update_edge"
ACTION_REMOVE_EDGE = "remove_edge"

ACTIONS: tuple[str, ...] = (
    ACTION_ADD_NODE, ACTION_UPDATE_NODE, ACTION_REMOVE_NODE,
    ACTION_ADD_EDGE, ACTION_UPDATE_EDGE, ACTION_REMOVE_EDGE,
)

#: ★ 一批最多多少条（⚠ 防止一次请求塞一万条把库拖住）—— ★ 可调
MAX_CHANGES = 200


class _BatchFailed(Exception):
    """★★★ **内部信号：整批回滚** —— ⚠★ 为什么需要一个异常，而不是 `return`。

    ★★★ 这是一个**很隐蔽、但后果很严重**的坑：

    ```python
    with transaction.atomic():
        ...
        if not r.ok:
            return CurateBatchResult(ok=False, ...)   # ❌ **会 COMMIT！**
    ```

    ★★ 因为 `transaction.atomic()` **只在【抛出异常】时回滚**；
      ★ `return` 是**正常退出** ⇒ ★ **照样提交** —— 于是"回滚"**根本没发生**，
      前面那几条**真的写进了库**（★ 实测抓到的：整批报失败，第 1 条却生效了）。

    ⇒ ★★ 所以必须**抛**出去，★ 且 `except` 要写在 **`with` 的外面**
      （⚠ 在 `with` 内接住 = 又变成正常退出 = 又提交了）。
    """

    def __init__(self, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


# ===========================================================================
# 权限
# ===========================================================================


@dataclass
class CanCurate:
    """★ 修补权限的判定结果。

    ⚠★ 注意 `via_admin` —— ★ 它**必须**被写进审计（见模块文档）。
    """

    allowed: bool = False
    #: ★ 机器可读原因（`not_found` / `forbidden` / `ok`）
    code: str = "forbidden"
    message: str = ""
    is_owner: bool = False
    #: ★★ **`is_staff` 代改** —— ⚠ 与"owner 自己改"**性质不同**
    via_admin: bool = False
    project: Any = None


def can_curate(project_ref: str, user) -> CanCurate:
    """★★★ **谁能修补这个项目的图** —— ★ 这是本模块的**唯一权限入口**。

    ★★ 与 `web/permissions.can_edit` 是**同一条规则**，且由它**调用本函数**
      （★ 方向是 `web → graph`，符合 `ARCHITECTURE.md` A3 的分层 ✅）
      —— ⚠ 反过来的话 `graph/` 就要 import `web/`，**越层**了。

    ⚠ 越权**统一按"找不到"处理**（同 `web/permissions.NOT_FOUND`）——
      ★ 否则 `403` 会告诉攻击者"这个项目存在"。
    """
    from core.models import Project

    project = Project.objects.filter(project_ref=project_ref).first()
    if project is None:
        return CanCurate(allowed=False, code="not_found", message="项目不存在或无权访问")

    if user is None or not getattr(user, "pk", None):
        return CanCurate(allowed=False, code="forbidden", message="请先登录")

    if project.owner_id == user.pk:
        # ★★ **主路径**：项目创建者自己修补（★ 用户原话）
        return CanCurate(
            allowed=True, code="ok", is_owner=True, project=project,
            message="你是这个项目的创建者",
        )

    if getattr(user, "is_staff", False):
        # ⚠ **平台介入** —— 允许，但审计里必须区分开
        return CanCurate(
            allowed=True, code="ok", via_admin=True, project=project,
            message="站点管理员（代项目方修补）",
        )

    # ⚠★ **不区分"不存在"与"无权"**（`frontend-contract.md` §5 / §19.3）
    return CanCurate(
        allowed=False, code="not_found", message="项目不存在或无权访问", project=project
    )


# ===========================================================================
# 结果
# ===========================================================================


@dataclass
class CurateResult:
    """★ 一次修补的结果 —— ⚠★ **业务失败不抛异常**（同 `submission` 的口径）。"""

    ok: bool = False
    action: str = ""
    message: str = ""
    node: Node | None = None
    edge: Edge | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def vid(self) -> int | None:
        return self.node.node_id if self.node is not None else None


@dataclass
class CurateBatchResult:
    """★★ 一批修补的结果（★ 契约的 `{ok, data:{graph_rev, applied}}`）。

    ★ `applied` = **每条动作干了什么**（★ 前端据此逐条确认，★ 而不是只知道"请求成功"）。
    """

    ok: bool = False
    message: str = ""
    graph_rev: int = 0
    applied: list[dict] = field(default_factory=list)
    #: ★ `409 stale_rev` 时带上**当前** rev（★ 前端据此提示"图变了，请重读"）
    stale: bool = False
    current_rev: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def applied_count(self) -> int:
        return len(self.applied)


# ===========================================================================
# 内部：留痕三件套
# ===========================================================================


def _audit(*, action: str, project_ref: str, by, reason: str, detail: dict) -> None:
    """★ 写审计（`G1`：**全量审计**）—— ⚠★ **含"改前"**（★ 删除操作唯一的墓碑）。"""
    from core.models import AuditLog

    AuditLog.objects.create(
        actor=by if getattr(by, "pk", None) else None,
        action=action,
        target_kind="Graph",
        target_id=project_ref,
        detail={
            "reason": (reason or "")[:500],
            "by_name": getattr(by, "username", "") or "",
            **detail,
        },
    )


def _node_snapshot(node: Node) -> dict:
    """★ 节点快照 —— ★★ **审计里的"改前"**（⚠ 只留关键字段，别把整个对象塞进去）。"""
    return {
        "vid": node.node_id,
        "uid": node.uid,
        "kind": node.kind,
        "name": node.name,
        "file_path": node.file_path,
        "line": node.line,
        "line_end": node.line_end,
        "origin": node.origin,
    }


def _edge_snapshot(edge: Edge) -> dict:
    return {
        "edge_id": edge.pk,
        "type": edge.type,
        "from_vid": edge.from_node_id,
        "to_vid": edge.to_node_id,
        "line": edge.line,
        "origin": edge.origin,
    }


def _from_or_to(vid: int):
    """⚠ 小工具：`Q(from_node_id=vid) | Q(to_node_id=vid)`。"""
    from django.db.models import Q

    return Q(from_node_id=vid) | Q(to_node_id=vid)


def _check_ref(project_ref: str) -> str:
    from core.refs import is_valid_project_ref

    if not is_valid_project_ref(project_ref):
        raise ValueError(f"非法的 project_ref：{project_ref!r}")
    return project_ref


def _require(by, reason: str) -> str:
    """★★★ **强制留痕**（但不阻拦操作）。

    ★ 见模块文档：★ 这不是"流程规定"，★★ 而是**「用户全权负责」的技术前提**
      —— ⚠ **没有审计，「全权负责」就变成「没人负责」**。
    """
    if by is None or not getattr(by, "pk", None):
        raise ValueError("手工修补必须记录【操作者】（by=…）—— 图数据要能追溯到人")
    if not (reason or "").strip():
        raise ValueError(
            "手工修补必须写【理由】（reason=…）—— "
            "这是给半年后的你自己看的（⚠ 删掉的东西在别处再也查不到）"
        )
    return reason.strip()


# ===========================================================================
# 内部：逐条执行（★ **不**在此 bump、**不**在此写审计 —— 那两个是"批"级别的）
# ===========================================================================


def _do_add_node(project_ref: str, c: dict) -> CurateResult:
    uid, kind = c.get("uid") or "", c.get("kind") or "function"
    name, file_path = c.get("name") or "", c.get("file_path") or ""
    line = c.get("line")
    if not name or not file_path or not line:
        return CurateResult(ok=False, action=ACTION_ADD_NODE,
                            message="add_node 需要 uid/kind/name/file_path/line")
    if int(line) < 1:
        return CurateResult(ok=False, action=ACTION_ADD_NODE, message="line 必须 >= 1")

    node = Node.objects.create(
        project_ref=project_ref,
        # ★★ `uid` 不给就按**解析器的同一形态**兜：`<kind>#<path>#<name>`
        #   （`codeparser/base.py::ParsedNode.uid`）—— ⚠ 格式不一致会让同一逻辑节点**对不上**
        uid=(uid or f"{kind}#{file_path}#{name}")[:512],
        kind=(kind or "")[:32],
        name=name[:512],
        qname=(c.get("qname") or "")[:512],
        file_path=file_path[:1024],
        line=int(line),
        line_end=int(c["line_end"]) if c.get("line_end") else None,
        lang=(c.get("lang") or "")[:32],
        signature=(c.get("signature") or "")[:512],
        doc=c.get("doc") or "",
        extra=c.get("extra") or {},
        origin=ORIGIN_MANUAL,      # ★ 规则 2
    )
    return CurateResult(
        ok=True, action=ACTION_ADD_NODE, node=node,
        message=f"已补上节点 {node.name}（vid={node.node_id}）",
        # ★★ **每个动作都必须回带自己的 id** —— ⚠ 原先这里漏了 `vid`，
        #   而单条包装 `_one()` 要拿它取回 `Node` ⇒ **KeyError**
        #   （★ 冒烟抓出来的：它只在**单条路径**上暴露，`apply_changes` 不读这个字段）
        detail={"before": None, "after": _node_snapshot(node), "vid": node.node_id},
    )


def _do_update_node(project_ref: str, c: dict) -> CurateResult:
    fields = c.get("fields") or {}
    vid = c.get("vid")
    unknown = [k for k in fields if k not in _NODE_FIELDS]
    if unknown:
        return CurateResult(ok=False, action=ACTION_UPDATE_NODE,
                            message=f"不允许修改这些字段：{', '.join(sorted(unknown))}")
    if not fields:
        return CurateResult(ok=False, action=ACTION_UPDATE_NODE, message="没有要改的字段")

    node = Node.objects.filter(project_ref=project_ref, node_id=vid).first()
    if node is None:
        return CurateResult(ok=False, action=ACTION_UPDATE_NODE, message=f"节点不存在（vid={vid}）")

    before = _node_snapshot(node)
    for k, v in fields.items():
        setattr(node, k, v)
    node.origin = ORIGIN_MANUAL          # ★ 规则 2：改过就是"人写的"
    node.save(update_fields=[*fields.keys(), "origin", "updated_at"])

    return CurateResult(
        ok=True, action=ACTION_UPDATE_NODE, node=node,
        message=f"已修改节点 {node.name}（{', '.join(sorted(fields))}）",
        detail={"before": before, "after": _node_snapshot(node),
                "changed": sorted(fields), "vid": node.node_id},
    )


def _do_remove_node(project_ref: str, c: dict) -> CurateResult:
    """★★ 删节点。

    > **用户原话**：「他**删除错了，是他的事**。」⇒ ★ **不阻拦**（只要求记理由）。

    ⚠★ 两个连带影响：
      **1** ★★ **会连带删掉它的所有边**（`Edge` 是 `CASCADE`）⇒ ★ **必须报告删了几条**；
      **2** ★★★ **不删挂在它上面的解释**（`§2.3.12`）：★ 锚是 `uid` 字符串，
        图里查不到该 `uid` ⇒ 渲染为「**该节点已被维护者移除**」
        —— ★ **不需要 `orphaned` 状态机、不迁移、不删任何人的内容** ✅
    """
    vid = c.get("vid")
    node = Node.objects.filter(project_ref=project_ref, node_id=vid).first()
    if node is None:
        return CurateResult(ok=False, action=ACTION_REMOVE_NODE,
                            message=f"节点不存在（vid={vid}）")

    before = _node_snapshot(node)
    # ★★ 先**数**再删（删完就数不出来了）—— ★ 影响面必须报告
    edges = list(
        Edge.objects.filter(project_ref=project_ref)
        .filter(_from_or_to(vid))
        .values("id", "type", "from_node_id", "to_node_id")
    )
    node.delete()

    return CurateResult(
        ok=True, action=ACTION_REMOVE_NODE,
        message=(f"已删除节点 {before['name']}（vid={vid}）"
                 + (f"，连带 {len(edges)} 条边" if edges else "")),
        detail={
            # ★★ 删除的审计**就是它唯一的墓碑** —— 别处再也查不到这个节点了
            "before": before, "after": None,
            "cascaded_edges": edges, "cascaded_edge_count": len(edges), "vid": vid,
        },
    )


def _do_add_edge(project_ref: str, c: dict) -> CurateResult:
    from_vid, to_vid = c.get("from_vid"), c.get("to_vid")

    nodes = {
        n.node_id: n
        for n in Node.objects.filter(
            project_ref=project_ref, node_id__in=(from_vid, to_vid)
        )
    }
    missing = [v for v in (from_vid, to_vid) if v not in nodes]
    if missing:
        # ⚠ 端点不存在**和**端点属于别的项目都会走到这里 —— ★ 文案要覆盖两种可能
        return CurateResult(ok=False, action=ACTION_ADD_EDGE,
                            message=f"端点不存在，或不属于这个项目：vid={missing}")

    edge = Edge.objects.create(
        project_ref=project_ref,
        from_node=nodes[from_vid],
        to_node=nodes[to_vid],
        type=(c.get("type") or "calls")[:32],
        line=int(c["line"]) if c.get("line") else None,
        confidence=(c.get("confidence") or "")[:16],
        extra=c.get("extra") or {},
        origin=ORIGIN_MANUAL,
    )
    return CurateResult(
        ok=True, action=ACTION_ADD_EDGE, edge=edge,
        message=f"已补上边 {nodes[from_vid].name} -[{edge.type}]-> {nodes[to_vid].name}",
        detail={"before": None, "after": _edge_snapshot(edge), "edge_id": edge.pk},
    )


def _do_update_edge(project_ref: str, c: dict) -> CurateResult:
    fields = c.get("fields") or {}
    edge_id = c.get("edge_id")
    unknown = [k for k in fields if k not in _EDGE_FIELDS]
    if unknown:
        return CurateResult(ok=False, action=ACTION_UPDATE_EDGE,
                            message=f"不允许修改这些字段：{', '.join(sorted(unknown))}")
    if not fields:
        return CurateResult(ok=False, action=ACTION_UPDATE_EDGE, message="没有要改的字段")

    edge = Edge.objects.filter(project_ref=project_ref, id=edge_id).first()
    if edge is None:
        return CurateResult(ok=False, action=ACTION_UPDATE_EDGE, message=f"边不存在（edge_id={edge_id}）")

    before = _edge_snapshot(edge)
    for k, v in fields.items():
        setattr(edge, k, v)
    edge.origin = ORIGIN_MANUAL
    edge.save(update_fields=[*fields.keys(), "origin", "updated_at"])

    return CurateResult(
        ok=True, action=ACTION_UPDATE_EDGE, edge=edge, message="已修改边",
        detail={"before": before, "after": _edge_snapshot(edge),
                "changed": sorted(fields), "edge_id": edge.pk},
    )


def _do_remove_edge(project_ref: str, c: dict) -> CurateResult:
    """★ 删一条边（★ **不**连带删节点 —— ★ 边只是"关系"，节点还在）。"""
    edge_id = c.get("edge_id")
    edge = Edge.objects.filter(project_ref=project_ref, id=edge_id).first()
    if edge is None:
        return CurateResult(ok=False, action=ACTION_REMOVE_EDGE, message=f"边不存在（edge_id={edge_id}）")

    before = _edge_snapshot(edge)
    edge.delete()
    return CurateResult(
        ok=True, action=ACTION_REMOVE_EDGE, message="已删除边",
        detail={"before": before, "after": None, "edge_id": edge_id},
    )


_DISPATCH = {
    ACTION_ADD_NODE: _do_add_node,
    ACTION_UPDATE_NODE: _do_update_node,
    ACTION_REMOVE_NODE: _do_remove_node,
    ACTION_ADD_EDGE: _do_add_edge,
    ACTION_UPDATE_EDGE: _do_update_edge,
    ACTION_REMOVE_EDGE: _do_remove_edge,
}


# ===========================================================================
# ★★★ 对外唯一入口：批量修补
# ===========================================================================


def apply_changes(
    project_ref: str,
    *,
    by,
    reason: str,
    changes: list[dict],
    base_graph_rev: int | None = None,
) -> CurateBatchResult:
    """★★★ **一次修补（一批 changes）** —— ★ 契约 `POST …/graph/edit/` 的实现。

    ★★ 一次调用 = **一个事务 + 一条审计 + `graph_rev` 只 +1**（见模块文档）：
      · ⚠ **任一条失败 ⇒ 整批回滚**（★ 不留"半个修补"）
      · ★ **一条审计**里含**全部** changes（★ 看得出"他一次干了什么"）
      · ★ 只 bump **一次**（⚠ 否则一次修补让邻域缓存反复失效）

    ⚠★ **权限**：★ 由 `can_curate()` 判（owner 或 `is_staff`）——
      ⚠ **本函数不做权限判定**（★ 那是调用方的事吗？**不** —— 见下）。

    ⚠⚠ 本函数**自己**调 `can_curate()` ⇒ ★ **无法绕过**（★ 这是有意的：
      权限判定**必须在数据层旁边**，❌ 不能指望每个调用方都记得判）。

    Args:
        base_graph_rev: ★ 可选 —— 传了就比对一次，不匹配返回 `stale_rev`
            ⚠★ **这不是 CAS**（没有加锁）—— ★ 见模块文档那一节
    """
    _check_ref(project_ref)
    why = _require(by, reason)

    # ---- ① 权限（★ 本函数自己判，❌ 不外包给调用方）----
    perm = can_curate(project_ref, by)
    if not perm.allowed:
        return CurateBatchResult(ok=False, message=perm.message, detail={"code": perm.code})

    if not changes:
        return CurateBatchResult(ok=False, message="没有要应用的内容（changes 为空）")
    if len(changes) > MAX_CHANGES:
        return CurateBatchResult(
            ok=False, message=f"一次最多 {MAX_CHANGES} 条（收到 {len(changes)} 条）"
        )

    # ---- ② `base_graph_rev`（可选；⚠ 不是 CAS，是善意提示）----
    if base_graph_rev is not None:
        cur = revision.current(project_ref)
        if int(base_graph_rev) != cur:
            return CurateBatchResult(
                ok=False, stale=True, current_rev=cur, graph_rev=cur,
                message="图在你编辑期间发生了变化，请重新载入后再试",
                detail={"code": "stale_rev"},
            )

    # ---- ③ 一个事务里逐条执行（⚠ 任一条失败 ⇒ **整批回滚**）----
    #
    # ★★★ 注意这里为什么用 `try/except` 包住整个 `with`：
    #   ⚠★ **失败时必须【抛】出去，❌ 不能 `return`** ——
    #   `transaction.atomic()` 只在抛异常时回滚，`return` 会**正常提交**
    #   ⇒ ★ 那就成了"报失败、但前面几条已经写进去了"（★ 实测抓到的坑，见 `_BatchFailed`）。
    #   ★ 而 `except` 必须在 **`with` 外面**（⚠ 在里面接住 = 又变成正常退出 = 又提交）。
    applied: list[dict] = []
    try:
        with transaction.atomic():
            for idx, raw in enumerate(changes):
                action = (raw or {}).get("action") or ""
                fn = _DISPATCH.get(action)
                if fn is None:
                    raise _BatchFailed(
                        f"第 {idx + 1} 条的动作不认识：{action!r}",
                        {"failed_index": idx, "action": action},
                    )
                r = fn(project_ref, raw or {})
                if not r.ok:
                    raise _BatchFailed(
                        f"第 {idx + 1} 条失败：{r.message}",
                        {"failed_index": idx, "action": action},
                    )
                applied.append({"action": action, "message": r.message, **r.detail})

            # ---- ④ 一条审计，含全部 changes ----
            _audit(
                action="graph.curate.apply",
                project_ref=project_ref, by=by, reason=why,
                detail={
                    "count": len(applied),
                    "manual_nodes": sum(1 for a in applied if a["action"] == ACTION_ADD_NODE),
                    "manual_edges": sum(1 for a in applied if a["action"] == ACTION_ADD_EDGE),
                    # ★★ 管理员代改**必须看得出来**（⚠ 与"owner 自己改"性质不同）
                    "via_admin": perm.via_admin,
                    "is_owner": perm.is_owner,
                    "applied": applied,
                },
            )

            # ---- ⑤ bump **一次**（★ 不是每条一次）----
            rev = revision.bump(project_ref)
    except _BatchFailed as exc:
        # ★ 事务已回滚（★ 因为异常穿过了 `atomic()` 的边界）
        return CurateBatchResult(ok=False, message=exc.message, detail=exc.detail)

    return CurateBatchResult(
        ok=True, graph_rev=rev, applied=applied,
        message=f"已应用 {len(applied)} 项修改（graph_rev → {rev}）",
        detail={"via_admin": perm.via_admin},
    )


# ===========================================================================
# 单条操作 —— ★ 都是 `apply_changes` 的**薄包装**（★ 只有一条路径）
# ===========================================================================


def _one(project_ref: str, *, by, reason: str, change: dict) -> CurateResult:
    """★ 把批量结果收敛成单条的 `CurateResult`（★ 给 CLI / 内部调用方用）。"""
    b = apply_changes(project_ref, by=by, reason=reason, changes=[change])
    if not b.ok:
        return CurateResult(ok=False, action=change.get("action", ""), message=b.message,
                            detail={"code": b.detail.get("code", ""), "stale": b.stale})

    d = b.applied[0]
    action = d["action"]
    out = CurateResult(ok=True, action=action, message=d["message"], detail=d)
    if action == ACTION_ADD_NODE:
        out.node = Node.objects.filter(project_ref=project_ref, node_id=d["vid"]).first()
    elif action == ACTION_ADD_EDGE:
        out.edge = Edge.objects.filter(project_ref=project_ref, id=d["edge_id"]).first()
    return out


def add_node(project_ref: str, *, by, reason: str, **fields) -> CurateResult:
    """★ **补一个解析漏掉的节点**（★ 这是手工修补**最主要**的用途）。"""
    return _one(project_ref, by=by, reason=reason,
                change={"action": ACTION_ADD_NODE, **fields})


def update_node(project_ref: str, vid: int, *, by, reason: str, **fields) -> CurateResult:
    """★ **改一个节点**（★ 解析给错了：名字 / 行号 / 签名…）。"""
    return _one(project_ref, by=by, reason=reason,
                change={"action": ACTION_UPDATE_NODE, "vid": vid, "fields": fields})


def delete_node(project_ref: str, vid: int, *, by, reason: str) -> CurateResult:
    """★ 删一个不该在的节点（★ 连带删边，**会报告条数**）。"""
    return _one(project_ref, by=by, reason=reason,
                change={"action": ACTION_REMOVE_NODE, "vid": vid})


def add_edge(project_ref: str, *, by, reason: str, **fields) -> CurateResult:
    """★ 补一条解析漏掉的边（⚠ 两个端点必须**同属本项目**）。"""
    return _one(project_ref, by=by, reason=reason,
                change={"action": ACTION_ADD_EDGE, **fields})


def update_edge(project_ref: str, edge_id: int, *, by, reason: str, **fields) -> CurateResult:
    """★ 改一条边（★ 通常是 `type` 认错了）。"""
    return _one(project_ref, by=by, reason=reason,
                change={"action": ACTION_UPDATE_EDGE, "edge_id": edge_id, "fields": fields})


def delete_edge(project_ref: str, edge_id: int, *, by, reason: str) -> CurateResult:
    """★ 删一条边（★ 不连带删节点）。"""
    return _one(project_ref, by=by, reason=reason,
                change={"action": ACTION_REMOVE_EDGE, "edge_id": edge_id})


# ===========================================================================
# 看一眼：这个项目上被人补过什么
# ===========================================================================


def manual_summary(project_ref: str) -> dict:
    """★ **这个项目上有多少"人补的"东西**（`origin="manual"`）。

    ★ 用途：★ 维护者改完能确认自己改到了；
      ★★ 也**直接支撑 `§2.3.12` 规则 2**（「UI 上人工项有**视觉标记**」）——
      ★ 前端拿这个比例就能显示"这张图里有 N 项是人补的" ✅
    """
    nodes = Node.objects.filter(project_ref=project_ref, origin=ORIGIN_MANUAL)
    edges = Edge.objects.filter(project_ref=project_ref, origin=ORIGIN_MANUAL)
    return {
        "project_ref": project_ref,
        "manual_nodes": nodes.count(),
        "manual_edges": edges.count(),
        "total_nodes": Node.objects.filter(project_ref=project_ref).count(),
        "total_edges": Edge.objects.filter(project_ref=project_ref).count(),
        "graph_rev": revision.current(project_ref),
        "nodes": [
            {"vid": n.node_id, "name": n.name, "file_path": n.file_path, "line": n.line}
            for n in nodes.order_by("node_id")[:200]
        ],
    }
