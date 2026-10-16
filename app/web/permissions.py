"""Astrolabe · ① Web 层：权限**门面**（★ `B209` · 2026-10-16）

★★★ **本文件没有任何判定逻辑** ⚠

## ★★ 为什么退化成门面（所有者 2026-10-16 裁定，逐字）

> 「**有些权限判断是散乱的的，因为我是不断修改权限的，我加一个权限，
> 你就写一行代码。把权限判断检查收束一下。**」

★ 收束前的病：* 「owner ∨ 协作者 ∨ staff」这条梯子**在本文件里就写了 4 遍**
  （* `can_view` / `can_edit` / `is_owner_or_staff` / `note_readable`），
  * 加上两个视图里的私有判定和 `graph/curate.py`，* 全文 6 遍 ⚠

## ★★ 三层结构（`B209`②）

| 层 | 位置 | 职责 |
|---|---|---|
| ① ★★ **角色梯** | `core/access.py::role_of()` | 一个人对一个项目是什么角色 ——* **全系统只此一处** |
| ② ★★ **对象判据** | `core/access.py` | 项目 / 笔记 / 评论 / 点赞的读 / 写 / 删 ——* **全系统只此一处** |
| ③ ★★ **请求门面（* 本文件）** | request → user → 调内核 | * **一行一个，* 零判定逻辑** |

⚠ 视图**只认本文件** ——* ❌ 不许视图自己写判定，* ❌ 不许视图直接 import `core.access`
  （* 门面是唯一出口 ⇒* "谁在用哪条判据"grep 本文件就知道）⚠

## ★★ 现行口径速查（★ 权威版在 `core/access.py` 顶部的判据总表）

| 谁能看 | 公开项目 ⇒ 任何人；私有 ⇒ owner ∨ 协作者 ∨ staff |
|---|---|
| 谁能改内容 | owner ∨ 协作者 ∨ staff |
| 谁能删项目 | owner ∨ staff（协作者不能） |
| 谁能加 / 移协作者 | owner ∨ staff |

⚠ 两条硬纪律（`frontend-contract.md` §5 / §19.3）：

| # | 纪律 | 为什么 |
|---|---|---|
| **1** | ★ **越权统一 404**（与「不存在」**不可区分**） | 否则 `project_ref` 就成了**探测工具** —— 403 会告诉攻击者"这个项目存在" |
| **2** | ★ **`project_ref` 不得作为授权凭证** | 它会进 URL / 日志 / 分享链接 ⇒ 泄露即越权 |

⚠ 分层纪律（`ARCHITECTURE.md` A3）：本模块属于 ①，只依赖共享内核。
"""

from __future__ import annotations

from django.http import HttpRequest

from core import access
from core.models import Project

#: ★ 统一文案 —— ⚠ **不要**在文案里区分"不存在"与"无权"（那正是要避免的泄露）
NOT_FOUND = "项目不存在或无权访问"


# ---------------------------------------------------------------------------
# 请求态原语（★ 这些不是"判定"，* 是把 request 变成 user）
# ---------------------------------------------------------------------------

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
    """取项目（❌ **不做权限判定** —— 判定交给下面的门面函数，职责分开）。"""
    return Project.objects.filter(project_ref=project_ref).first()


# ---------------------------------------------------------------------------
# 门面：一行一个（★ 判定全在 core/access.py，* 这里只做 request → user → 调内核）
# ---------------------------------------------------------------------------

def can_view(request: HttpRequest, project: Project) -> bool:
    """能否**读这个项目**（* 判据：`core/access.can_view_project`）⚠"""
    return access.can_view_project(current_user(request), project)


def can_edit(request: HttpRequest, project: Project) -> bool:
    """能否**改这个项目的内容**（* 判据：`core/access.can_edit_project`）⚠"""
    return access.can_edit_project(current_user(request), project)


def can_delete(request: HttpRequest, project: Project) -> bool:
    """能否**删掉整个项目**（* 判据：`core/access.can_delete_project`）⚠"""
    return access.can_delete_project(current_user(request), project)


def can_manage_members(request: HttpRequest, project: Project) -> bool:
    """能否**加 / 移协作者**（* 判据：`core/access.can_manage_members`）⚠

    ⚠★ 2026-10-16 从 `is_owner_or_staff` **改名**（`B209`）：
      · ★ 旧名字描述**规则**（* owner or staff），* 将来规则一改名字就撒谎 ⚠
      · · ★ 新名字描述**意图**（* 管成员）——* 规则怎么变名字都不用动 ✅
    """
    return access.can_manage_members(current_user(request), project)


def note_readable(request: HttpRequest, note) -> bool:
    """**这篇笔记能读吗**（* 判据：`core/access.can_read_note`）⚠"""
    return access.can_read_note(current_user(request), note)


def project_of(note):
    """**这个笔记属于哪个项目**（* 本体：`core/access.project_of`）⚠

    ⚠★ 2026-10-16（`B209`③）从 `graph/notes.py` **移入内核** ——* 它回答
      "这篇笔记是谁的"，* 本质是访问判定；* 经门面露出，* ❌ 不让视图直接 import 内核 ⚠
    """
    return access.project_of(note)


def note_writable(request: HttpRequest, note) -> bool:
    """**这篇笔记能改 / 删吗**（* 判据：`core/access.can_write_note`）⚠

    ⚠★ 2026-10-16 收拢：* 原先是 `views/notes.py::_writable` 私有判定，
      * 现在只有这一个出口（* `B209`）✅
    """
    return access.can_write_note(current_user(request), note)


def comment_deletable(request: HttpRequest, comment) -> bool:
    """**这条评论能删吗**（* 判据：`core/access.can_delete_comment`）⚠

    ⚠★ 2026-10-16 收拢：* 原先是 `views/comments.py::_deletable` 私有判定 ✅
    """
    return access.can_delete_comment(current_user(request), comment)


def can_see_hidden_orphans(request: HttpRequest, note) -> bool:
    """**能看被隐藏的失锚段评吗**（* 判据：`core/access.can_see_hidden_orphans`）⚠

    ⚠★ 2026-10-16 收拢：* 原先是 `views/comments.py::_can_see_hidden` 私有判定 ✅
    """
    return access.can_see_hidden_orphans(current_user(request), note)


def can_create_comment(request: HttpRequest, note) -> bool:
    """**能发评论吗**（* 判据：`core/access.can_create_comment`）⚠

    ⚠★ 可读性由调用方**先判** ⇒* 本门面 False 通常只是"**没登录**"（* 回 401）✅
    """
    return access.can_create_comment(current_user(request), note)


def can_like(request: HttpRequest, note) -> bool:
    """**能点赞 / 取消赞吗**（* 判据：`core/access.can_like`）⚠

    ⚠★ 同 `can_create_comment`：* 可读性先判过 ⇒* False = 没登录（* 回 401）✅
    """
    return access.can_like(current_user(request), note)


def can_curate(project_ref: str, user):
    """★★★ **能否修补这个项目的图**（`§2.3.12` 通道 ②）。

    ★★ 本函数**只是转交** —— 梯子与判据在 `core/access.can_curate()`，
      包装在 `graph.curate.can_curate()`：

    | 方向 | 允许？ | 为什么 |
    |---|---|---|
    | `web → graph`（**本函数**） | ✅ | ★ ① 层可以依赖更底下的模块 |
    | `graph → web` | ❌ | ⚠ **越层**（`ARCHITECTURE.md` A3） |

    ⚠ 返回的是 `graph.curate.CanCurate`（★ 含 `via_admin` —— 管理员代改**审计里要看得出来**）。
    """
    from graph.curate import can_curate as _can_curate

    return _can_curate(project_ref, user)
