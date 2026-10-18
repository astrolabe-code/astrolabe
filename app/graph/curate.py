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

# ★★★ `B179` / `B180`：**本模块的规则 1、2 被【颠倒】了**（★ 2026-10-13）

★★★ 所有者原话（逐字）：

> 「**基图与用户修改存在不同模型里，请求时，直接请求这两份数据，前端负责整合**，
> 这就要求节点索引一定要设计好，能迅速对比出修改的部分，
> **不是在服务器上整合了，再发出去**哦。」

## ⚠★ 规则 1 从「直接改图」变成「**绝不碰基图**」

| | `B179` 之前 | `B179` 之后 |
|---|---|---|
| ★ 规则 1 | ★ 「**直接改图**，不做叠加层」| ★★ **修改一律落 `GraphPatch`，★ 基图行一个字都不动** ⚠ |
| ★ 新增节点 | ★ 建一个 `project_ref` 的 `Node` | ★ 照旧建行（★ 它**本来就是叠加层**）✅ + **一条 `add_node` 补丁** |
| ★ 改 / 删基图节点 | ★★ **直接改那行** ⚠ | ★★ **只写补丁**（★ `target_node` 指向它）⚠ |

★★★ **为什么改 / 删绝不能落在基图行上**：★ 基图是**所有用户共享**的 ⚠
  —— ★★ A 改一下，★ B 看到的就变了（★ 那是「**串号**」，⚠ 不是「修改」）⚠

## ⚠★ 规则 2 从「写 `origin` 列」变成「**归属算出来**」

★ `B179` 把 `origin` **列删了**（★ 基图行必然是 `parsed`、叠加行必然是 `manual`）⚠
⇒ ★★ 所以这里**不再写 `origin=`**，★ 由序列化器**算**（★ 见 `web/serializers.py`）✅

## ★★ 因此「怎么整合」的责任在前端

★ 服务端**只发两份数据**（★ 基图一份 · ★ 补丁一份），⚠ **不做合并** ⚠
  · 基图 ⇒ `…/graph/nodes/` · `…/graph/edges/`（★ 走 `graph/scope.py`）
  · ★★ 补丁 ⇒ `…/graph/patches/`（★ 每条带**目标 vid**）✅
⇒ ★ 前端**按 vid 一比**就知道哪个节点被改过 / 删过 ⚠

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
| **1** | ★ **直接改图**，不做「叠加层」 | ⚠★ **`B179` 已把这条颠倒**：★ 见上一节 ——<br>★★ **改 / 删一律落 `GraphPatch`，★ 基图行绝不碰** ⚠<br>（★ 唯一例外是**新增**：★ 它建的就是叠加层自己的行 ✅） |
| **2** | ★ 带 `origin = parsed ｜ manual`，**UI 上人工项有视觉标记** | ⚠★ **`B179` 已把这条颠倒**：★ `origin` **列已删**，<br>⇒ ★ **不再写列**，★ 由序列化器按**归属算** ✅<br>（★ 前端照旧拿到 `origin` —— ★ 接口没变，变的是存法 ⚠） |
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

# ⚠★ `Count` 在 `django.db.models` 里（★ 不在 `django.db`）——
#   ★★ `manage.py check` 抓出来的：写错就是 **ImportError ⇒ 全站起不来** ⚠
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from graph import identity, kinds, revision, scope
from graph.models import (
    PATCH_ACTIONS,
    PATCH_ADD_EDGE,
    PATCH_ADD_NODE,
    PATCH_REMOVE_EDGE,
    PATCH_REMOVE_NODE,
    PATCH_UPDATE_EDGE,
    PATCH_UPDATE_NODE,
    Edge,
    GraphPatch,
    Node,
)

#: ★ 允许修补的节点字段（★ **白名单**，❌ 不是"传什么改什么"）——
#: ⚠ `node_id` / `project_ref` / 归属 / 时间戳**不在其中**（★ 它们不是"内容"）
#: ⚠★ `B179`：此表曾含 `"origin"` —— ★ **列已删**，★ 归属决定它，❌ 不许改 ⚠
_NODE_FIELDS: tuple[str, ...] = (
    "kind", "name", "qname", "file_path", "line", "line_end",
    # ⚠★ `B176`：此表曾含 `"doc"` —— ★ 随节点字段一并移除（★ 修补不允许写入注释内容）✅
    "lang", "signature", "extra",
)

#: ★ 允许修补的边字段
_EDGE_FIELDS: tuple[str, ...] = ("type", "line", "confidence", "extra")

#: ★★ **六类动作**（★ 契约 `changes[].action` 的取值）
#: ⚠★ `B179`：字面值与 `graph/models.py` 的 `PATCH_*` **同一套** ——
#:   ★★ 所以这里【直接用它】，❌ 不再自己定义一份（★ 两套字面值早晚对不上）⚠
ACTION_ADD_NODE = PATCH_ADD_NODE
ACTION_UPDATE_NODE = PATCH_UPDATE_NODE
ACTION_REMOVE_NODE = PATCH_REMOVE_NODE
ACTION_ADD_EDGE = PATCH_ADD_EDGE
ACTION_UPDATE_EDGE = PATCH_UPDATE_EDGE
ACTION_REMOVE_EDGE = PATCH_REMOVE_EDGE

ACTIONS: tuple[str, ...] = PATCH_ACTIONS

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

    ⚠★ 2026-10-16（`B208`①）：**`via_admin` 字段已删** ⚠
      · ★ 管理员**不能**修图（* 所有者原话整句：「网站管理员有权限修改图和笔记，
        不行。」）⇒* `is_staff` 代改这条路**没有了**，* 字段留着就是死代码 ⚠
      · · ★ 审计要区分"谁改的" ⇒* 看 `is_owner` / `is_collaborator` 两个标记 ✅
    """

    allowed: bool = False
    #: ★ 机器可读原因（`not_found` / `forbidden` / `ok`）
    code: str = "forbidden"
    message: str = ""
    is_owner: bool = False
    #: ★★ **协作者**（`B202` / `B207`）—— ★ 与 owner 同权修图，* 但审计里要分得开 ⚠
    is_collaborator: bool = False
    project: Any = None


def can_curate(project_ref: str, user) -> CanCurate:
    """★★★ **谁能修补这个项目的图** —— ★ 这是本模块的**唯一权限入口**。

    ★★ 与 `web/permissions.can_edit` 是**同一条规则**，且由它**调用本函数**
      （★ 方向是 `web → graph`，符合 `ARCHITECTURE.md` A3 的分层 ✅）
      —— ⚠ 反过来的话 `graph/` 就要 import `web/`，**越层**了。

    ## ★★ 两种放行（* `B207`④：* 协作者与 owner 同权修图）⚠

    ```
    ① ★★ 项目创建者（* 主路径）✅
    ② ★★ 协作者（* B207④：* 「协作者可以改/删项目内任何人的笔记和图节点」）✅
    ```

    ⚠★★ 2026-10-16（`B208`①）：**管理员（staff）不再能修图** ⚠
      · ★ `CanCurate.via_admin` 字段与 staff 分支**一并删除** ✅

    ⚠★★ 2026-10-16（`B209`）：**梯子收拢到内核** ⚠
      · ★ 本函数**只负责把角色映射成 `CanCurate`**（* 每个角色的 message /
        标记不同 ⇒* 映射必须留在这一处）✅
      · · ★★ 而"谁是哪个角色"**只此一处**：* `core/access.py::role_of` ⚠
      · · ★（* 收束前这里自己写了一遍 owner→协作者→staff，* 是第 5 条复制线）⚠

    ⚠ 越权**统一按"找不到"处理**（同 `web/permissions.NOT_FOUND`）——
      ★ 否则 `403` 会告诉攻击者"这个项目存在"。
    """
    from core import access
    from core.models import Project

    project = Project.objects.filter(project_ref=project_ref).first()
    if project is None:
        return CanCurate(allowed=False, code="not_found", message="项目不存在或无权访问")

    # ★★ 梯子只此一处（* `core/access.py`）✅
    role = access.role_of(user, project)

    if role == access.ROLE_OWNER:
        # ★★ **主路径**：项目创建者自己修补（★ 用户原话）
        return CanCurate(
            allowed=True, code="ok", is_owner=True, project=project,
            message="你是这个项目的创建者",
        )

    if role == access.ROLE_COLLABORATOR:
        # ★★ `B207`④：**协作者与 owner 同权修图** ⚠
        return CanCurate(
            allowed=True, code="ok", is_collaborator=True, project=project,
            message="你是这个项目的协作者",
        )

    if user is None or not getattr(user, "pk", None):
        return CanCurate(allowed=False, code="forbidden", message="请先登录")

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
    """★ 节点快照 —— ★★ **审计里的"改前"**（⚠ 只留关键字段，别把整个对象塞进去）。

    ⚠★ `B179`：此函数曾返回 `origin` —— ★ **列已删**，★ 归属算得出来 ⚠
    """
    return {
        # ★★ `B219`：* 对外一律 stable_vid（* 内部主键不出门）⚠
        "vid": node.stable_vid,
        "uid": node.uid,
        "kind": kinds.kind_name(node.kind),
        "name": node.name,
        "file_path": node.file_path,
        "line": node.line,
        "line_end": node.line_end,
        # ★★ `B220`：* 归属按 `repo` 算（* 叠加层节点没有 repo）⚠
        "origin": "parsed" if node.repo_id else "manual",
    }


def _edge_snapshot(edge: Edge) -> dict:
    return {
        "edge_id": edge.pk,
        "type": edge.type,
        "from_vid": edge.from_node.stable_vid,
        "to_vid": edge.to_node.stable_vid,
        "line": edge.line,
        "origin": "parsed" if edge.repo_id else "manual",
    }


def _project(project_ref: str):
    """★ 取项目行（* 补丁按 `project` 外键写 —— `B221`）⚠"""
    from core.models import Project

    return Project.objects.filter(project_ref=project_ref).first()


def _target_node(project_ref: str, vid):
    """★★ **这个项目能改的节点**（★ `vid` 是 `stable_vid`，* `B219`）⚠

    | 顺序 | 哪来 | 说明 |
    |---|---|---|
    | ① | ★ 基图（* 本版本的 `versions` 里）| 解析产物 |
    | ② | ★ 本项目自己新增的（`project` 外键）| 叠加层 |
    """
    if vid is None:
        return None
    try:
        want = int(vid)
    except (TypeError, ValueError):
        return None
    node = scope.nodes_of(project_ref).filter(stable_vid=want).first()
    if node is not None:
        return node
    project = _project(project_ref)
    if project is None:
        return None
    return Node.objects.filter(project=project, stable_vid=want).first()


def _target_edge(project_ref: str, edge_id):
    """★★ **这个项目能改的边**（* 边 id 仍是主键 —— 它跨版本稳定）⚠"""
    if edge_id is None:
        return None
    try:
        want = int(edge_id)
    except (TypeError, ValueError):
        return None
    edge = scope.edges_of(project_ref).filter(pk=want).first()
    if edge is not None:
        return edge
    project = _project(project_ref)
    if project is None:
        return None
    return Edge.objects.filter(project=project, pk=want).first()


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


def _write_patch(project, *, lookup: dict, action: str, payload: dict, note, by):
    """★★★ 写补丁：**同一目标只有一条现行意见**（`B223`）⇒ `update_or_create` ⚠

    ⚠★ 不是追加 —— 再改就是**覆盖**（* 历史在 `AuditLog`）✅
    """
    from graph.patch_spec import ACTION_IDS

    patch, _ = GraphPatch.objects.update_or_create(
        project=project,
        **lookup,
        defaults={
            "action": ACTION_IDS[action],
            "payload": payload,
            "note": (note or "")[:400],
            "created_by": by,
        },
    )
    return patch


# ===========================================================================
# 内部：逐条执行（★ **不**在此 bump、**不**在此写审计 —— 那两个是"批"级别的）
# ===========================================================================


def _do_add_node(project, c: dict, by=None) -> CurateResult:
    """★★ **新增一个节点**（★ 六种动作里**唯一真的建行**的）✅

    ⚠★★ `B222`：* 类型必须**登记过**（* ⛔ 杜绝奇怪的类型名）⚠
    """
    from graph import kinds

    kind_name = str(c.get("kind") or "function").strip().lower()
    if not kinds.is_registered(kind_name):
        return CurateResult(
            ok=False, action=ACTION_ADD_NODE,
            message=f"未登记的类型：{kind_name!r}（见 graph/kinds.py）",
        )

    name = str(c.get("name") or "")
    file_path = str(c.get("file_path") or "")
    line_raw = c.get("line")
    if not name or not file_path or line_raw is None:
        return CurateResult(ok=False, action=ACTION_ADD_NODE,
                            message="add_node 需要 name/file_path/line")
    try:
        line = int(line_raw)
    except (TypeError, ValueError):
        return CurateResult(ok=False, action=ACTION_ADD_NODE, message="line 必须是整数")
    if line < 1:
        return CurateResult(ok=False, action=ACTION_ADD_NODE, message="line 必须 >= 1")

    line_end = c.get("line_end")
    canon = identity.canonical(kind_name, file_path, name, line, line_end)
    vid = identity.hash53(canon)

    # ★★★ `B225`：**已有同 vid 的节点 ⇒ 拒绝新增**（⛔ 不造第二份）⚠
    #   · · ★ 先查本项目可读的**基图节点**，* 再查**项目自己的叠加层** ⚠
    #   · · ★★ 同一份代码造两份 ⇒* 数据重复 + 笔记分裂（* 一份里写的笔记另一份看不见）⚠
    duplicate = scope.nodes_of(project.project_ref).filter(stable_vid=vid).first()
    if duplicate is None:
        duplicate = Node.objects.filter(project=project, stable_vid=vid).first()
    if duplicate is not None:
        return CurateResult(
            ok=False,
            action=ACTION_ADD_NODE,
            message=(
                f"这个节点已经在图里了（vid={vid}，{duplicate.name}）—— "
                "不要新增，请改用 update_node 修改它"
            ),
            detail={
                "code": "duplicate_node",
                "vid": vid,
                "existing_kind": kinds.kind_name(duplicate.kind),
                "existing_name": duplicate.name,
                "existing_file_path": duplicate.file_path,
                "existing_line": duplicate.line,
            },
        )

    node = Node.objects.create(
        project=project,
        stable_vid=vid,
        versions=[],
        uid=(str(c.get("uid") or f"{kind_name}#{file_path}#{name}"))[:512],
        kind=kinds.kind_id(kind_name),
        name=name[:512],
        qname=str(c.get("qname") or "")[:512],
        file_path=file_path[:1024],
        line=line,
        line_end=(int(line_end) if line_end is not None else -1),
        lang=str(c.get("lang") or "")[:32],
        signature=str(c.get("signature") or "")[:512],
        extra=c.get("extra") or {},
    )

    patch = _write_patch(
        project,
        lookup={"target_node": node},
        action=ACTION_ADD_NODE,
        payload={"vid": vid},
        note=c.get("note"),
        by=by,
    )
    return CurateResult(
        ok=True, action=ACTION_ADD_NODE, node=node,
        message=f"已新增节点 {node.name}",
        detail={"before": None, "after": _node_snapshot(node),
                "vid": node.stable_vid, "patch_id": patch.pk},
    )


def _do_update_node(project, c: dict, by=None) -> CurateResult:
    """★★★ **改一个节点 ⇒ 只写补丁**（★ 基图行一个字都不动）⚠

    ⚠★ 例外（`B223`④）：* 叠加层节点是**项目自己的行** ⇒* 直接改行，
      * 动作保持 `add_node`（* 否则前端看不见它）⚠
    """
    from graph import kinds, patch_spec

    fields = c.get("fields") or {}
    clean, err = patch_spec.validate_payload("update_node", fields)
    if err is not None:
        return CurateResult(ok=False, action=ACTION_UPDATE_NODE, message=err)
    if not clean:
        return CurateResult(ok=False, action=ACTION_UPDATE_NODE, message="没有要改的字段")

    node = _target_node(project.project_ref, c.get("vid"))
    if node is None:
        return CurateResult(ok=False, action=ACTION_UPDATE_NODE,
                            message=f"节点不存在（vid={c.get('vid')}）")

    before = _node_snapshot(node)

    if node.project_id == project.pk:
        # ★★ 叠加层节点：* 直接改行（* 项目自己的数据）—— * 动作保持 `add_node` ⚠
        for key, value in clean.items():
            setattr(node, key, kinds.kind_id(value) if key == "kind" else value)
        node.save()
        patch = _write_patch(
            project, lookup={"target_node": node}, action=ACTION_ADD_NODE,
            payload={"vid": node.stable_vid}, note=c.get("note"), by=by,
        )
    else:
        patch = _write_patch(
            project, lookup={"target_node": node}, action=ACTION_UPDATE_NODE,
            payload=clean, note=c.get("note"), by=by,
        )

    after = {**before, **clean}
    return CurateResult(
        ok=True, action=ACTION_UPDATE_NODE, node=node,
        message=f"已记录对节点 {node.name} 的修改（{', '.join(sorted(clean))}）",
        detail={"before": before, "after": after, "changed": sorted(clean),
                "vid": node.stable_vid, "patch_id": patch.pk},
    )


def _do_remove_node(project, c: dict, by=None) -> CurateResult:
    """★★★ **删一个节点 ⇒ 基图只写补丁；叠加层自己的行才真删** ⚠

    > **用户原话**：「他删除了，是他的事。」⇒ ★ **不阻拦**（只要求记理由）。
    """
    vid = c.get("vid")
    node = _target_node(project.project_ref, vid)
    if node is None:
        return CurateResult(ok=False, action=ACTION_REMOVE_NODE,
                            message=f"节点不存在（vid={vid}）")

    before = _node_snapshot(node)

    if node.project_id == project.pk:
        # ★ 叠加层节点：* 撤销新增 ⇒* 删行（* 它的 add_node 补丁随 CASCADE 走）✅
        GraphPatch.objects.filter(project=project, target_node=node).delete()
        node.delete()
        return CurateResult(
            ok=True, action=ACTION_REMOVE_NODE,
            message="已撤销新增的节点",
            detail={"before": before, "after": None, "vid": before["vid"]},
        )

    patch = _write_patch(
        project, lookup={"target_node": node}, action=ACTION_REMOVE_NODE,
        payload={}, note=c.get("note"), by=by,
    )
    return CurateResult(
        ok=True, action=ACTION_REMOVE_NODE,
        message=f"已记录对节点 {node.name} 的删除（★ 基图行没动）",
        detail={"before": before, "after": None, "vid": node.stable_vid, "patch_id": patch.pk},
    )


def _do_add_edge(project, c: dict, by=None) -> CurateResult:
    """★★ **新增一条边**（★ 叠加层自己的事）✅

    ⚠★ 端点可以是**基图节点**，* 也可以是本项目新增的节点 ⚠
    """
    from graph import patch_spec

    # ★ 兼容两种传法：* `fields` 对象（* 新口径）或平铺在 change 上（* 旧口径）⚠
    # ⚠ 只收**传了**的键 ——* 把没传的 `confidence=None` 塞进去会被白名单挡下 ⚠
    fields_src = c.get("fields")
    if fields_src is None:
        fields_src = {}
        for key in ("type", "line", "confidence"):
            if c.get(key) is not None:
                fields_src[key] = c[key]
    fields, err = patch_spec.validate_payload("add_edge", fields_src)
    if err is not None:
        return CurateResult(ok=False, action=ACTION_ADD_EDGE, message=err)

    from_vid, to_vid = c.get("from_vid"), c.get("to_vid")
    nodes = {}
    for v in (from_vid, to_vid):
        n = _target_node(project.project_ref, v)
        if n is not None:
            nodes[v] = n
    missing = [v for v in (from_vid, to_vid) if v not in nodes]
    if missing:
        return CurateResult(ok=False, action=ACTION_ADD_EDGE,
                            message=f"端点不存在，或不属于这个项目：vid={missing}")

    src, dst = nodes[from_vid], nodes[to_vid]

    # ★★★ `B225`：**已有同一条边 ⇒ 拒绝新增**（* 建议改用 `update_edge`）⚠
    edge_type = fields.get("type") or "calls"
    edge_line = fields.get("line", -1)
    duplicate_edge = (
        scope.edges_of(project.project_ref)
        .filter(from_node=src, to_node=dst, type=edge_type, line=edge_line)
        .first()
    )
    if duplicate_edge is None:
        duplicate_edge = (
            Edge.objects.filter(
                project=project, from_node=src, to_node=dst, type=edge_type, line=edge_line
            ).first()
        )
    if duplicate_edge is not None:
        return CurateResult(
            ok=False,
            action=ACTION_ADD_EDGE,
            message=(
                f"这条边已经在图里了（{src.name} -[{edge_type}]-> {dst.name}，"
                f"edge_id={duplicate_edge.pk}）—— 不要新增，请改用 update_edge 修改它"
            ),
            detail={"code": "duplicate_edge", "edge_id": duplicate_edge.pk},
        )

    patch = _write_patch(
        project,
        lookup={"from_node": src, "to_node": dst},
        action=ACTION_ADD_EDGE,
        payload=fields,
        note=c.get("note"),
        by=by,
    )
    return CurateResult(
        ok=True, action=ACTION_ADD_EDGE,
        message=f"已补上边 {src.name} -[{fields.get('type')}]-> {dst.name}",
        detail={"before": None, "after": fields,
                "from_vid": src.stable_vid, "to_vid": dst.stable_vid,
                "patch_id": patch.pk},
    )


def _do_update_edge(project, c: dict, by=None) -> CurateResult:
    """★★★ **改一条边 ⇒ 只写补丁**（★ 同 `update_node`）⚠"""
    from graph import patch_spec

    fields, err = patch_spec.validate_payload("update_edge", c.get("fields") or {})
    if err is not None:
        return CurateResult(ok=False, action=ACTION_UPDATE_EDGE, message=err)
    if not fields:
        return CurateResult(ok=False, action=ACTION_UPDATE_EDGE, message="没有要改的字段")

    edge = _target_edge(project.project_ref, c.get("edge_id"))
    if edge is None:
        return CurateResult(ok=False, action=ACTION_UPDATE_EDGE,
                            message=f"边不存在（edge_id={c.get('edge_id')}）")

    before = _edge_snapshot(edge)
    patch = _write_patch(
        project, lookup={"target_edge": edge}, action=ACTION_UPDATE_EDGE,
        payload=fields, note=c.get("note"), by=by,
    )
    return CurateResult(
        ok=True, action=ACTION_UPDATE_EDGE,
        message=f"已记录对边的修改（{', '.join(sorted(fields))}）",
        detail={"before": before, "after": {**before, **fields},
                "edge_id": edge.pk, "patch_id": patch.pk},
    )


def _do_remove_edge(project, c: dict, by=None) -> CurateResult:
    """★★★ **删一条边 ⇒ 只写补丁**（★ 基图边一行不动）⚠"""
    edge = _target_edge(project.project_ref, c.get("edge_id"))
    if edge is None:
        return CurateResult(ok=False, action=ACTION_REMOVE_EDGE,
                            message=f"边不存在（edge_id={c.get('edge_id')}）")

    before = _edge_snapshot(edge)
    patch = _write_patch(
        project, lookup={"target_edge": edge}, action=ACTION_REMOVE_EDGE,
        payload={}, note=c.get("note"), by=by,
    )
    return CurateResult(
        ok=True, action=ACTION_REMOVE_EDGE,
        message="已记录对边的删除",
        detail={"before": before, "after": None, "edge_id": edge.pk, "patch_id": patch.pk},
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
    project = _project(project_ref)
    if project is None:
        return CurateBatchResult(ok=False, message="项目不存在")

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
                r = fn(project, raw or {}, by=by)
                if not r.ok:
                    # ★★ `B225`：* 单条的 detail（* 如 `duplicate_node` 的 code / vid）⚠
                    #   · · ★ 必须透出批量结果 ——* 否则前端只知道"失败了"，* 不知道怎么处理 ⚠
                    raise _BatchFailed(
                        f"第 {idx + 1} 条失败：{r.message}",
                        {"failed_index": idx, "action": action, **(r.detail or {})},
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
        # ★★ `B220`：* 叠加层节点按 (project, stable_vid) 取 ⚠
        project = _project(project_ref)
        out.node = (
            Node.objects.filter(project=project, stable_vid=d.get("vid")).first()
            if project is not None
            else None
        )
    # ⚠★ `B223`：* `add_edge` 只写补丁，* 不再建 Edge 行 ⇒* `out.edge` 留空 ✅
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
    """★★ **这个项目上有多少"人补的"东西**（★ `B179`：★ 改数**补丁条数** ⚠）。

    ## ⚠★ `B179` 改了什么

    ★ 以前：★ `Node.objects.filter(project_ref=…, origin=ORIGIN_MANUAL)` ——
      ★★ 那时"人补的"**真的是行**（★ 规则 1 还是"直接改图"）⚠
    ★ 现在：★ **补丁就是修改本身** ⇒ ★ 数 `GraphPatch` ✅
      · ⚠ 而 `project_ref` 的那些 `Node` / `Edge` 行**只是"新增"的载体** ——
        ★★ 它们**不代表**全部修改（★ 改 / 删都在补丁里）⚠

    ★ 用途：★ 维护者改完能确认自己改到了；
      ★★ 也**直接支撑 `§2.3.12` 规则 2**（「UI 上人工项有**视觉标记**」）——
      ★ 前端拿这个比例就能显示"这张图里有 N 项是人补的" ✅
      （★ 标记本身由序列化器按**归属**算，★ 见 `web/serializers.py`）
    """
    patches = GraphPatch.objects.filter(project_ref=project_ref)
    # ★ 基图那两份（★ 总数要从基图数 —— ⚠ 项目自己那几行**不是**图的全集）
    base_nodes = scope.nodes_of(project_ref)
    base_edges = scope.edges_of(project_ref)
    # ★ 叠加层自己新增的行
    own_nodes = Node.objects.filter(project_ref=project_ref)
    own_edges = Edge.objects.filter(project_ref=project_ref)

    by_action: dict[str, int] = {}
    for action, n in patches.values_list("action").annotate(n=Count("pk")):
        by_action[action] = n

    return {
        "project_ref": project_ref,
        # ★★ "人补的"= 补丁条数（★ 这才是修改的全集）⚠
        "manual_total": patches.count(),
        "manual_by_action": by_action,
        "manual_nodes_added": own_nodes.count(),
        "manual_edges_added": own_edges.count(),
        # ★ 全集 = 基图 + 本项目自己新增的
        "total_nodes": base_nodes.count() + own_nodes.count(),
        "total_edges": base_edges.count() + own_edges.count(),
        "base_graph_nodes": base_nodes.count(),
        "base_graph_edges": base_edges.count(),
        "graph_rev": revision.current(project_ref),
        "patched_vids": list(
            patches.filter(target_node__isnull=False)
            .order_by("pk")
            .values_list("target_node_id", flat=True)
            .distinct()[:200]
        ),
    }
