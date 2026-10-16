"""Astrolabe · 共享内核：**行级访问判定**（★ `B209` · 2026-10-16）

★★★ **本模块是全系统权限判断的【唯一】发源地** ⚠

## ★★★ 为什么必须有它（所有者 2026-10-16 裁定，逐字）

> 「**有些权限判断是散乱的的，因为我是不断修改权限的，我加一个权限，
> 你就写一行代码。把权限判断检查收束一下。**」

★ 收束前的病（* 实测）：* 「owner ∨ 协作者 ∨ staff」这条梯子**全文写了 6 遍** ——
  `web/permissions.py` 内 4 遍 + `views/notes.py::_writable` +
  `views/comments.py::_deletable` / `_can_see_hidden` + `graph/curate.py::can_curate`。
  ★★ 改一条口径要改 6 处，* 漏一处 = **静默权限漏洞**（* 不报错，* 只是某类人从某处还能进）⚠

## ★★ 三层结构（`B209`②）

| 层 | 位置 | 职责 |
|---|---|---|
| ① ★★ **角色梯** | 本模块 `role_of()` | 一个人对一个项目是什么角色 ——* **全系统只此一处** |
| ② ★★ **对象判据** | 本模块其余函数 | 项目 / 笔记 / 评论 / 点赞的读 / 写 / 删 ——* **判据只此一处** |
| ③ ★★ **请求门面** | `web/permissions.py` | request → user → 调内核；* 一行一个，* ❌ 零判定逻辑 |

## ★★ 判据总表（★ 「谁能做什么」一个文件看完）

| 判据 | 规则 | 谁在用 |
|---|---|---|
| `role_of` | owner → collaborator → staff → user → guest | 本模块全部判据的地基 |
| `can_view_project` | 公开 ⇒ 任何人；私有 ⇒ owner ∨ collaborator ∨ staff | 项目详情/列表、笔记、评论、点赞、协作者端点 |
| `can_edit_project` | owner ∨ collaborator ∨ staff | 项目设置、触发拉取、取消作业、**建笔记**、协作者名单 |
| `can_delete_project` | owner ∨ staff | **删项目**（`B207`②：协作者不能删） |
| `can_manage_members` | owner ∨ staff | 加 / 移协作者（邀请是项目主的权力） |
| `can_read_note` | 项目大门 +（公开 ∨ 作者 ∨ owner ∨ collaborator ∨ staff） | 笔记详情、评论、点赞 |
| `can_write_note` | 作者 ∨ `can_edit_project` | 改 / 删笔记 |
| `can_create_comment` | 登录 + 可读 | 发评论 |
| `can_delete_comment` | 评论作者 ∨ staff ∨ `can_edit_project` | 删评论 |
| `can_like` | 登录 + 可读 | 点赞 / 取消赞 |
| `can_see_hidden_orphans` | 作者 ∨ `can_edit_project` ∨ staff | `include_hidden=1` |
| `can_curate` | owner ∨ collaborator ∨ staff | 修图（`graph/curate.py` 委托本模块拿梯子） |

⚠★ **加一种权限的走法**：* 在**本文件**加一个判据函数（* 查 `role_of` 或组合已有判据）+
  上面这张表补一行；* 门面加一个一行包装。* ★★ **判定逻辑永远只有一份** ⚠

⚠ 分层纪律（`ARCHITECTURE.md` A3）：本模块属于**共享内核**（① Web 与 `graph/` 都要判），
  只依赖 ORM，* ❌ 不 import Django 的请求 / 视图 / URL。
"""

from __future__ import annotations

from typing import Any

# ===========================================================================
# ① 角色梯（★ 全系统只此一处）
# ===========================================================================

#: ★ 未登录（或没有 pk 的"半成品"用户对象 —— ⚠ 见 `capabilities.py` 的 B144 坑）
ROLE_GUEST = "guest"
#: ★ 登录了，但与本项目无关
ROLE_USER = "user"
#: ★ 站点管理员（`is_staff`）
ROLE_STAFF = "staff"
#: ★ 项目协作者（`core_collaborator` 有一行）
ROLE_COLLABORATOR = "collaborator"
#: ★ 项目创建者
ROLE_OWNER = "owner"

#: ★ 角色强弱序（★ 只用于表达"谁包含谁"，* ❌ 不用于判定 —— 判定一律显式写）
ROLE_ORDER = (ROLE_GUEST, ROLE_USER, ROLE_STAFF, ROLE_COLLABORATOR, ROLE_OWNER)


def role_of(user: Any, project: Any) -> str:
    """★★ **一个人对一个项目是什么角色** ——* 全系统权限的**唯一**发源地 ⚠

    ```
    owner → collaborator → staff → user → guest
    ```

    ⚠★ 顺序即优先级：* owner 优先于协作者优先于 staff ⚠
      （* 一个用户可能同时是协作者和 staff ⇒* 取更强的那个，* 与旧实现一致）✅

    ⚠★ `pk` 检查不能省：* Django 的 `User().is_authenticated` **永远是 `True`**
      （* 只有 `AnonymousUser` 返回 `False`）⇒* 一个"半成品"用户对象会 otherwise 通过检查 ⚠
    """
    if user is None or not getattr(user, "pk", None):
        return ROLE_GUEST
    if project is not None and project.owner_id == user.pk:
        return ROLE_OWNER
    if project is not None and _is_collaborator(user, project):
        return ROLE_COLLABORATOR
    if getattr(user, "is_staff", False):
        return ROLE_STAFF
    return ROLE_USER


def _is_collaborator(user: Any, project: Any) -> bool:
    """★ 协作者判定（* `core_collaborator` 有一行即为协作者）✅"""
    from core.models import Collaborator

    return Collaborator.objects.filter(project=project, user=user).exists()


def is_admin(user: Any) -> bool:
    """★ 站点管理员（* staff 或 superuser）✅"""
    return bool(user is not None and getattr(user, "pk", None)
                and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)))


# ===========================================================================
# ② 对象判据（★ 判据只此一处）
# ===========================================================================


def can_view_project(user: Any, project: Any) -> bool:
    """能否**读这个项目**。

    ★ 公开项目：**游客也能读**（`U2.1`：读开放是策略）。
    ⚠ 私有项目：owner ∨ 协作者 ∨ staff。
    """
    if project is None:
        return False
    if project.is_public:
        return True
    return role_of(user, project) in (ROLE_OWNER, ROLE_COLLABORATOR, ROLE_STAFF)


def can_edit_project(user: Any, project: Any) -> bool:
    """能否**改这个项目的内容**（设置 / 触发拉取 / 取消作业 / **建笔记** / 看协作者名单）。

    ⚠ 与 UGC 的**评论 / 点赞**无关（那两条任何登录用户都可，见 `can_create_comment`）；
      ★★ 而**建笔记依赖**本判据（`B207`③：只能在自己 / 协项目建）⚠。
    ⚠★ **删项目不在这里** —— 见 `can_delete_project`（`B207`②）⚠。
    """
    if project is None:
        return False
    return role_of(user, project) in (ROLE_OWNER, ROLE_COLLABORATOR, ROLE_STAFF)


def can_delete_project(user: Any, project: Any) -> bool:
    """★★★ **能否删掉整个项目**（`B207`②：协作者**不能**删项目）⚠

    ★★ 仅 owner ∨ staff。

    ⚠★ 为什么单开一道判据、* ❌ 不并进 `can_edit_project`：
      · ★ `can_edit_project` 管的是"**改内容**"，* 删项目是"**毁掉全部**"——
      · · ★ 两者破坏性差一个量级，* 混在一个函数里迟早有人给错 ⚠
    """
    if project is None:
        return False
    return role_of(user, project) in (ROLE_OWNER, ROLE_STAFF)


def can_manage_members(user: Any, project: Any) -> bool:
    """★★ **能否加 / 移协作者**（* 邀请是项目主的权力，* `A24③`）⚠

    ★★ 仅 owner ∨ staff ——* 协作者**不能**加 / 移协作者 ⚠

    ⚠ 当前规则与 `can_delete_project` **相同**，* 但**刻意分成两个名字**：
      * 它们服务不同意图（* 一个毁全部、* 一个加同伴），* 将来若要分开收费不会互相绊住 ⚠
    """
    if project is None:
        return False
    return role_of(user, project) in (ROLE_OWNER, ROLE_STAFF)


def project_of(note: Any) -> Any:
    """★★ **这个笔记属于哪个项目**（* 用于取项目级设置 / 判 owner）⚠

    ⚠★ 2026-10-16 从 `graph/notes.py` **移入本模块**（`B209`③）：
      · ★ 它回答"这篇笔记是谁的"，* 本质是**访问判定**，* 该住内核 ⚠
      · · ★ `graph/notes.py` 改为从本模块 import（* graph → core 是允许方向）✅

    ⚠★ 笔记挂在 `graph_node` 上，* 而节点可能属【项目】/【基图】/【修改层】⚠
      · · ★ 属项目（* 外键）⇒ ★ 直接取 `node.project` ✅
      · · ★ 属基图 ⇒ ★ 顺基图找到**绑它的项目** ⚠
      · · ★ 属修改层（* 老口径 `project_ref`）⇒ ★ ref 唯一 ⇒ **精确命中** ✅
      · · ★（* 而一个基图可能被多个项目绑 ⇒ ★ 这种情形下"是哪个项目的策略"
        * **不明确** ⇒* 取第一个）⚠
      · · ★★ 取不到唯一项目时返回 None ⇒ ★ 用**代码默认值** ✅

    ⚠★★ 修掉过一个**静默取错项目**的洞（* 2026-10-16 发现）：
      · ★ 老实现无条件 `Project.objects.filter(base_graph_id=node.base_graph_id).first()`——
      · · ★ 而 `base_graph_id` 为 None 时 ⇒ ★ 它会匹配到**任意一个没绑基图的项目** ⚠
      · · ★★ 后果：* 失锚策略 / 删除权限可能读到【别的项目】的设置
        （* 不报错，* 只是错）⚠
    """
    node = note.node
    if node is None:
        return None
    if node.project_id is not None:
        return node.project
    from core.models import Project

    if node.base_graph_id is not None:
        return Project.objects.filter(base_graph_id=node.base_graph_id).first()
    if node.project_ref:
        return Project.objects.filter(project_ref=node.project_ref).first()
    return None


def can_read_note(user: Any, note: Any) -> bool:
    """★★★ **这篇笔记能读吗**（* 两层判据，* `B207`⑦；* **只此一份**）⚠

    ## ★★ 两层（* 顺序不能反）

    ```
    ⓪ ★★ **项目大门**（* `can_view_project` 不过 ⇒ * 一律 False）⚠
       · · ★ 所有者原话整句：「私有项目上没有"公开笔记"，项目私有，
         其中的一切都私有，不可见，除非把项目改公开。」
       · · ★★ 所以：* 私有项目里 `is_public` **失去意义** ⚠
       · · ★（* 这条同时补掉了"凭 note_id 直达"的洞 ——* note_id 是自增整数，
         可枚举，* 而详情 / 评论 / 点赞三个端点都走本函数）⚠
    ① ★ **笔记层**：* `is_public` ∨ 作者 ∨ owner ∨ 协作者 ∨ staff ✅
       · · ★ 协作者能看别人的私有笔记（* 原话整句：「不能看，怎么修改？」）✅
    ```

    ⚠★ 已知近似（* 2026-10-16 如实记）：* 笔记挂在**基图节点**上时，
      `project_of()` 取的是**第一个绑它的项目** ⇒ * 该项目私有则 **fail-closed**
      （* 宁可多挡几个人，* ❌ 不放过一个）⚠
    """
    project = project_of(note)

    # ⓪ 项目大门（* `B207`⑦④）✅
    if project is not None and not can_view_project(user, project):
        return False

    # ① 笔记层 ✅
    if note.is_public:
        return True
    if user is None or not getattr(user, "pk", None):
        return False
    if note.created_by_id == user.pk:
        return True
    if is_admin(user):
        return True
    if project is not None and (
        project.owner_id == user.pk or _is_collaborator(user, project)
    ):
        return True
    return False


def can_write_note(user: Any, note: Any) -> bool:
    """★★ **这篇笔记能改 / 删吗**（* `B207`③：* 协作者可改 / 删项目内**任何人**的笔记）⚠

    ```
    ★★ staff ✅
    ★★ 作者本人 ✅
    ★★ 项目 owner ∨ 协作者（* `can_edit_project`）✅
    ```

    ⚠★ 普通登录用户**不能**改别人项目里的笔记 ——* 所有者原话整句：
      「普通登陆用户不能修改别人项目的图与笔记，这是别人辛辛苦苦写的，
       怎么能允许别人轻易修改？这些就像B站up主发的视频一样。」⚠
    """
    if user is None or not getattr(user, "pk", None):
        return False
    if is_admin(user):
        return True
    if note.created_by_id == user.pk:
        return True
    return can_edit_project(user, project_of(note))


def can_create_comment(user: Any, note: Any) -> bool:
    """★★ **能发评论吗**（* `B207`⑤：* **任何登录用户**就能评）⚠

    ★★ 登录 + 可读。

    ⚠★ 可读性由调用方**先判**（* 评论列表 / 详情入口）⇒* 本判据在入口处 False
      通常只是"**没登录**"（* 门面据此回 401）✅
    """
    if user is None or not getattr(user, "pk", None):
        return False
    return can_read_note(user, note)


def can_delete_comment(user: Any, comment: Any) -> bool:
    """★★ **谁能删这条评论**（* `B207`⑤：* 评论作者 ∨ owner ∨ 协作者 ∨ staff）⚠

    ⚠★ **评论只删不改**（* `B201③` 重申）——* 所以这里**没有**"能改"一说 ⚠
    ⚠★ 协作者与 owner / 管理员一样能删**别人**的评论（* 所有者原话整句：
      「协作者跟作者与管理员一样，可以删别人评论。」；* 且管理员可以删评论，
      * 见 `B208` 保留项）✅
    """
    if user is None or not getattr(user, "pk", None):
        return False
    if is_admin(user):
        return True
    if comment.created_by_id == user.pk:
        return True
    return can_edit_project(user, project_of(comment.note))


def can_like(user: Any, note: Any) -> bool:
    """★★ **能点赞 / 取消赞吗**（* `B207`⑥：* 任何登录用户就能赞）⚠

    ★★ 登录 + 可读（* 同 `can_create_comment` 的形状）✅
    """
    if user is None or not getattr(user, "pk", None):
        return False
    return can_read_note(user, note)


def can_see_hidden_orphans(user: Any, note: Any) -> bool:
    """★★ **谁能看被隐藏的失锚段评**（* `include_hidden=1` 的权限侧）⚠

    ★★ 作者 / 项目 owner / 协作者 / staff ✅
      （* `B207`① 齐平：* 项目内访问齐平，* 协作者与 owner 同权；
        * staff 保留是因为**管理员可以删评论**（* `B208`）——* 要看得见才删得掉）⚠
    """
    if user is None or not getattr(user, "pk", None):
        return False
    if is_admin(user):
        return True
    if note.created_by_id == user.pk:
        return True
    return can_edit_project(user, project_of(note))


def can_curate(user: Any, project: Any) -> bool:
    """★★★ **谁能修补这个项目的图**（* `B207`④：* 协作者与 owner 同权修图）⚠

    ★★ owner ∨ 协作者 ∨ staff ✅

    ⚠★ `graph/curate.py::can_curate()` **委托本函数拿梯子**，* 自己只负责
      把结果包装成 `CanCurate`（* 带 message / is_owner / is_collaborator /
      via_admin）——* ★★ 梯子只此一处，* ❌ 不再来一遍 ⚠
    """
    if project is None:
        return False
    return role_of(user, project) in (ROLE_OWNER, ROLE_COLLABORATOR, ROLE_STAFF)
