"""Astrolabe · ① Web 层：权限判定

★ 口径（**协作者批次后**，`B202` / `B206` / `B207`）：

| 谁能看 | 范围 |
|---|---|
| **公开项目** | ★ **任何人**（含未登录游客）—— 这是「读懂别人的代码」的前提 |
| **私有项目** | ★ **owner ∨ 协作者 ∨ staff**（`B207`②：邀请了就能查看） |

| 谁能改 | 范围 |
|---|---|
| **项目内容**（设置 / 触发拉取 / 取消作业 / 建笔记 / 修图） | ★ **owner ∨ 协作者 ∨ staff** |
| ★★ **删项目** | ★★ **仅 owner ∨ staff**（`B207`②：协作者不能删项目） |

⚠ 协作者 = **一对多表** `core_collaborator(project, user)`（`B202`）——
  ★ 管理页**按用户名直接加**，❌ 不发链接、❌ 不要 token（`B206`）。

⚠ 仍**没有**：分享链接（`?share=`）/ 组织 / 团队 —— 见 `PRODUCT-VERSIONS.md`；
  ⚠ 契约 §5 的 `view_err` / `edit_err` 是**旧站**的口径，
  本模块按**新设计**重写（旧站那套含已删除机制）。

★★ 两条硬纪律（`frontend-contract.md` §5 / §19.3）：

| # | 纪律 | 为什么 |
|---|---|---|
| **1** | ★ **越权统一 404**（与「不存在」**不可区分**） | 否则 `project_ref` 就成了**探测工具** —— 403 会告诉攻击者"这个项目存在" |
| **2** | ★ **`project_ref` 不得作为授权凭证** | 它会进 URL / 日志 / 分享链接 ⇒ 泄露即越权 |

⚠ 分层纪律（`ARCHITECTURE.md` A3）：本模块属于 ①，只依赖共享内核。
"""

from __future__ import annotations

from django.http import HttpRequest

from core.models import Project
from graph.notes import project_of

#: ★ 统一文案 —— ⚠ **不要**在文案里区分"不存在"与"无权"（那正是要避免的泄露）
NOT_FOUND = "项目不存在或无权访问"


def current_user(request: HttpRequest):
    """★ 当前登录用户（⚠ 未登录返回 `None`，❌ 不返回 `AnonymousUser`）。

    ★ 统一在这里判，而**不是**各处写 `request.user.is_authenticated` ——
      ⚠ 因为 `AnonymousUser` 也有 `.is_authenticated`（恒为 False），
      ★ 一旦有人写成 `if request.user:`，**匿名用户也会进**（`AnonymousUser` 是真值！）。
    """
    user = getattr(request, "user", None)
    return user if (user is not None and user.is_authenticated) else None


def is_staff(request: HttpRequest) -> bool:
    """★ 站点管理员（`U2.2`：用 Django 自带的 `is_staff`，❌ 不另造一套）。"""
    user = current_user(request)
    return bool(user and user.is_staff)


def staff_only(view):
    """★★ **管理员端点**的装饰器（★ 与 `require_http_methods` 叠加使用）。

    ★ 两级区分（`U2.4`）：**staff** 能审核；★ 而改**门禁类参数**只有 **superuser** 能
      —— 后者由 `appsettings.set_value()` 自己拦（⚠ 不在这一层判，因为那是**参数层**的纪律）。
    """
    from functools import wraps

    from web.http import fail

    @wraps(view)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if current_user(request) is None:
            return fail("请先登录", 401, code="unauthenticated")
        if not is_staff(request):
            # ⚠ 403（**不是 404**）—— ★ 与项目越权不同：★ 这里没什么可隐藏的
            #   （"管理员接口存在"是公开信息，⚠ 假装 404 只会让真管理员困惑）
            return fail("需要管理员权限", 403, code="forbidden")
        return view(request, *args, **kwargs)

    return wrapper


def login_required(view):
    """★ 需要登录（⚠ 不发 401 的**语义**区别：`unauthenticated` 才是"去登录"的信号）。"""
    from functools import wraps

    from web.http import fail

    @wraps(view)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if current_user(request) is None:
            return fail("请先登录", 401, code="unauthenticated")
        return view(request, *args, **kwargs)

    return wrapper


def get_project(request: HttpRequest, project_ref: str) -> Project | None:
    """取项目（❌ **不做权限判定** —— 判定交给下面两个函数，职责分开）。"""
    return Project.objects.filter(project_ref=project_ref).first()


def _is_collaborator(request: HttpRequest, project: Project) -> bool:
    """★★ **这个用户是这个项目的协作者吗**（★ `B202` / `B207`）⚠

    ★★ 本函数是 `can_view` / `can_edit` 的**唯一**协作者判据 ——
      ❌ 不许在视图里各自查一遍 `Collaborator`（* 那会漏判，* 且纪律只剩一处）⚠
    """
    user = current_user(request)
    if user is None:
        return False
    from core.models import Collaborator

    return Collaborator.objects.filter(project=project, user=user).exists()


def can_view(request: HttpRequest, project: Project) -> bool:
    """能否**读**。

    ★ 公开项目：**游客也能读**（`request.user` 可能是 `AnonymousUser`）。
    ⚠ 私有项目：owner ∨ 协作者 ∨ staff —— ★★ 协作者批次后（`B207`②）：
      「一个项目甭管是私有的还是公开的，只要邀请了，对方都可以查看修改」
      ⇒ 私有项目的大门也给协作者开（* 否则邀请是空操作）⚠
    """
    if project.is_public:
        return True
    return (
        _is_owner(request, project)
        or _is_collaborator(request, project)
        or _is_staff(request)
    )


def can_edit(request: HttpRequest, project: Project) -> bool:
    """能否**改项目内容**（项目设置 / 触发拉取 / 取消作业 / 建笔记 / 修图）。

    ⚠ 一期：owner ∨ 协作者 ∨ staff。
    ⚠ 与 UGC **部分**无关：**评论 / 点赞**的写权**不依赖** `can_edit`
      （契约 §20.2「UGC 写权不依赖 can_edit」）—— 那是另一条通道；
      ★★ 而**建笔记依赖** `can_edit`（`B207`③：只能在自己/协项目建）⚠。

    ⚠★ **删项目不在这里** —— 见 `can_delete()`（`B207`②：协作者不能删项目）⚠
    """
    return (
        _is_owner(request, project)
        or _is_collaborator(request, project)
        or _is_staff(request)
    )


def is_owner_or_staff(request: HttpRequest, project: Project) -> bool:
    """★★ **owner 或 staff**（* 全系统**最严**的一档）⚠

    ★★ `can_delete`（* 删项目）与**协作者管理**（* 加人 / 移除）都用它 ✅
      · · ★ 两者都是"只有项目主本人能干"的事（* `B207`②）⚠
      · · ★（* 协作者**不能**删项目，* 也**不能**加 / 移协作者）⚠
    """
    return _is_owner(request, project) or _is_staff(request)


def can_delete(request: HttpRequest, project: Project) -> bool:
    """★★★ **能否删掉整个项目**（★ `B207`② 新增，* 2026-10-16）⚠

    ★★ **仅 owner ∨ staff** ——* 协作者**不能**删项目 ⚠
      （* 所有者原话整句：「协作者不能删项目。」）✅

    ⚠★ 为什么单开一道判据、* ❌ 不并进 `can_edit`：
      · ★ `can_edit` 管的是"**改内容**"，* 删项目是"**毁掉全部**"——
      · · ★ 两者破坏性差一个量级，* 混在一个函数里迟早有人给错 ⚠
      · ★ 而 `projects.detail` 的 DELETE 分支**只认本函数** ✅
    """
    return is_owner_or_staff(request, project)


def note_readable(request: HttpRequest, note) -> bool:
    """★★★ **这篇笔记能读吗**（★ 两层判据，* `B207`⑦；* **只此一份**）⚠

    ## ★★ 两层（* 顺序不能反）

    ```
    ⓪ ★★ **项目大门**（* `can_view` 不过 ⇒ * 一律 False）⚠
       · · ★ 所有者原话整句：「私有项目上没有"公开笔记"，项目私有，
         其中的一切都私有，不可见，除非把项目改公开。」
       · · ★★ 所以：* 私有项目里 `is_public` **失去意义** ⚠
       · · ★（* 这条同时补掉了"凭 note_id 直达"的洞 ——* note_id 是自增整数，
         可枚举，* 而详情 / 评论 / 点赞三个端点都走本函数）⚠
    ① ★ **笔记层**：* `is_public` ∨ 作者 ∨ owner ∨ 协作者 ∨ staff ✅
       · · ★ 协作者能看别人的私有笔记（* 原话整句：「不能看，怎么修改？」）✅
    ```

    ⚠★ 笔记详情 / 评论 / 点赞**共用**本函数 —— * ❌ 不三处各写一份 ⚠
    ⚠★ 已知近似（* 2026-10-16 如实记）：* 笔记挂在**基图节点**上时，
      `project_of()` 取的是**第一个绑它的项目** ⇒ * 该项目私有则 **fail-closed**
      （* 宁可多挡几个人，* ❌ 不放过一个）⚠
    """
    project = project_of(note)

    # ⓪ 项目大门（* `B207`⑦④）✅
    if project is not None and not can_view(request, project):
        return False

    # ① 笔记层 ✅
    if note.is_public:
        return True
    user = current_user(request)
    if user is None:
        return False
    if note.created_by_id == user.pk:
        return True
    if getattr(user, "is_staff", False):
        return True
    if project is not None and (
        project.owner_id == user.pk or _is_collaborator(request, project)
    ):
        return True
    return False


def can_curate(project_ref: str, user):
    """★★★ **能否修补这个项目的图**（`§2.3.12` 通道 ②）—— ★ **项目创建者自己**。

    > **用户原话（`B157`）**：「修补节点是**项目创建者自己**修补，**不是我这个管理员帮他修补**。」

    ★★ 本函数**只是转交** —— 真正的判定在 `graph.curate.can_curate()`：

    | 方向 | 允许？ | 为什么 |
    |---|---|---|
    | `web → graph`（**本函数**） | ✅ | ★ ① 层可以依赖更底下的模块 |
    | `graph → web` | ❌ | ⚠ **越层**（`ARCHITECTURE.md` A3） |

    ★★ 所以权限判定**必须住在 `graph/` 那一侧** —— ⚠ 否则 `graph.curate` 就没法自己判，
      只能指望**每个调用方都记得判**（★ 而总有一天会有人忘）。

    ⚠ 返回的是 `graph.curate.CanCurate`（★ 含 `via_admin` —— 管理员代改**审计里要看得出来**）。
    """
    from graph.curate import can_curate as _can_curate

    return _can_curate(project_ref, user)


def _is_owner(request: HttpRequest, project: Project) -> bool:
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and project.owner_id == user.pk)


def _is_staff(request: HttpRequest) -> bool:
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_staff)
