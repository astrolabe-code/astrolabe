"""Astrolabe · ① Web 层：权限判定

★ 一期口径（**最小可用**）：

| 谁能看 | 范围 |
|---|---|
| **公开项目** | ★ **任何人**（含未登录游客）—— 这是「读懂别人的代码」的前提 |
| **私有项目** | ★ **仅 owner** |

⚠ 一期**没有**：协作者 / 分享链接（`?share=`）/ 组织 / 团队 ——
  见 `PRODUCT-VERSIONS.md`；⚠ 契约 §5 的 `view_err` / `edit_err` 是**旧站**的口径，
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


def can_view(request: HttpRequest, project: Project) -> bool:
    """能否**读**。

    ★ 公开项目：**游客也能读**（`request.user` 可能是 `AnonymousUser`）。
    ⚠ 私有项目：仅 owner；⚠ owner 为空（平台代管）⇒ **只有管理员能读**。
    """
    if project.is_public:
        return True
    return _is_owner(request, project) or _is_staff(request)


def can_edit(request: HttpRequest, project: Project) -> bool:
    """能否**改**（项目设置 / 触发解析 / 删除）。

    ⚠ 一期：**仅 owner**（或管理员）。
    ⚠ 与 UGC **无关**：解释 / 提问 / 笔记的写权**不依赖** `can_edit`
      （契约 §20.2「UGC 写权不依赖 can_edit」）—— 那是另一条通道。
    """
    return _is_owner(request, project) or _is_staff(request)


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
