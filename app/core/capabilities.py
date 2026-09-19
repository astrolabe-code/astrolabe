"""Astrolabe · 共享内核：能力表（capability）

★ 依据 `USERS-AND-AUTH.md` U5：
   ★★ **判定只走能力表** —— ❌ **不允许**在视图里写 `if tier == "vip"`。

★★ 为什么必须这样（U5.1）：

    ⚠ 散落的 `if tier == ...` 会让「**VIP 到底能干什么**」**散在 20 个文件里** ——
    ★ 将来要调整边界（或把企业功能"收回公开版付费层"）时，
    **没人说得清要改哪几处**。★ 能力表**天生就是权限文档**。

★★ 三条纪律（U5.2）：

| # | 纪律 |
|---|---|
| **1** | ★ 判定**只走能力表**：`can(user, CAP_XXX)` —— ❌ 不准写 `tier == ...` |
| **2** | ★ **配额与能力分开** —— 能力是"能不能"，配额是"多少"（见 `appsettings.py`） |
| **3** | ★★ **未实现的档位在表里也要有列** —— 这样"可开可关"只是**改表里的一格** |

⚠ 分层纪律（`ARCHITECTURE.md` A3）：★ 本模块属于**共享内核** ——
   ★ ① Web 与 ② 作业**都要判**，所以必须放在两边都能 import 的地方；
   ⚠ 它**只依赖标准库**，❌ 不 import Django 的请求 / 视图 / 模型。
"""

from __future__ import annotations

from typing import Any, FrozenSet

# ===========================================================================
# 能力常量
#
# ⚠ 命名规则：`<域>.<动作>` —— ★ 一眼能看出它管什么
# ===========================================================================

# ---- 读（`U2.1`：★ 连游客都能完整读）----
CAP_READ_PUBLIC = "read.public"

# ---- UGC 写（`U2.2` 第 1 条）----
# ★★ 任何登录用户都可以写 —— ❌ **不要求拥有这个项目**、❌ 不要求协作者身份
CAP_UGC_WRITE = "ugc.write"
CAP_UGC_EDIT_OWN = "ugc.edit_own"          # ★ 只能改**自己写的**（❌ 不提供编辑他人内容）
CAP_UGC_ADOPT = "ugc.adopt"                # ★ 采纳（项目 owner / 管理员）
CAP_UGC_MODERATE = "ugc.moderate"          # ★ 删除他人内容（作者本人 / owner / 管理员）

# ---- 项目 ----
CAP_PROJECT_CREATE = "project.create"
CAP_PROJECT_PUBLISH_OWN = "project.publish.own"   # ★ 仍受 **Gate 0** 约束（`U3`）
CAP_PROJECT_PUBLISH_ANY = "project.publish.any"   # ★★ **特批**（唯一例外，`U2.5`）
CAP_PROJECT_EDIT_OWN = "project.edit_own"
CAP_PROJECT_DELETE_OWN = "project.delete_own"
CAP_PROJECT_REVIEW = "project.review"             # ★ 审核队列（`U3.7`，staff）
CAP_PROJECT_HIDE = "project.hide"                 # ★ 隐藏 / 下架 / 恢复（`U3.5`）

# ---- 付费（`U9`）----
CAP_PAID_SET = "paid.set"                  # ★ 把自己写的讲解设为付费（★ 受 `paid_slots` 约束）
CAP_PAID_READ_ENTITLED = "paid.read"       # ★ 看**已购买**的付费内容

# ---- 报告 / 举报（`U3.5` / `U9.9`）----
CAP_REPORT_CREATE = "report.create"        # ★★ **发动群众**（任何登录用户）
CAP_REPORT_HANDLE = "report.handle"        # ★ 处理举报（staff）

# ---- 学习进度（`U8.4`：★ 私有，只给自己看）----
CAP_PROGRESS_READ_OWN = "progress.read_own"
CAP_PROGRESS_WRITE_OWN = "progress.write_own"

# ---- 成就（`U7`）----
CAP_ACHIEVEMENT_VIEW = "achievement.view"              # ★ 看自己的（含**进度**，`U7.3` 机制 1）
CAP_ACHIEVEMENT_SHOWCASE = "achievement.showcase"      # ★★ VIP 的"**花哨展示**"（`U7.4`）

# ---- 深度分析（`U6` + 契约 §17.7）----
CAP_ANALYSIS_DEEP = "analysis.deep"        # ⚠ **VIP 且需管理员开通**

# ---- 管理（`U2.5`）----
CAP_ADMIN_SETTINGS = "admin.settings"      # ★ 改参数（**superuser**）
CAP_ADMIN_USERS = "admin.users"            # ★ 授予 / 撤销 staff
CAP_ADMIN_AUDIT = "admin.audit"            # ★ 看审计
CAP_INVITE_MANAGE = "invite.manage"        # ★ 生成 / 撤销邀请（`U4.7`）


# ===========================================================================
# ★★ 能力表
#
# ⚠ 档位分**两类**（`U1` 的三条正交线）：
#   · **登录态** —— 游客 vs 已登录
#   · **站点职权** —— user / staff / superuser
#   · **订阅层级** —— free / vip
# ★ 它们**独立累加**（一个 VIP 可以是普通用户，也可以是 staff）。
# ===========================================================================

#: ★ 游客（未登录）—— `U2.1`：★ **能完整地读**，❌ 不能写
ANONYMOUS: FrozenSet[str] = frozenset({CAP_READ_PUBLIC})

#: ★ 普通用户 —— `U2.2`
FREE: FrozenSet[str] = ANONYMOUS | frozenset(
    {
        CAP_UGC_WRITE,
        CAP_UGC_EDIT_OWN,
        CAP_UGC_MODERATE,          # ★ 只能删**自己写的**（范围由视图层收窄）
        CAP_PROJECT_CREATE,
        CAP_PROJECT_PUBLISH_OWN,   # ★ 仍受 Gate 0 约束
        CAP_PROJECT_EDIT_OWN,
        CAP_PROJECT_DELETE_OWN,
        CAP_PAID_READ_ENTITLED,    # ★ 有权益就能看（权益由管理员手工开，`U9.4`）
        CAP_REPORT_CREATE,         # ★★ 发动群众（`U9.9`）
        CAP_PROGRESS_READ_OWN,
        CAP_PROGRESS_WRITE_OWN,
        CAP_ACHIEVEMENT_VIEW,
    }
)

#: ★★ VIP —— `U2.3`：★ 是 FREE 的**超集**（❌ 不是"另一个人群"）
#: ⚠ 注意：这里**只多了配额与荣誉**，❌ **没有多一条"能看更多内容"** ——
#:    这正是 `U1` 的核心纪律。
VIP: FrozenSet[str] = FREE | frozenset(
    {
        CAP_ANALYSIS_DEEP,           # ⚠ 仍需管理员开通（view 层再查一次开关）
        CAP_PAID_SET,                # ★ 受 `paid_slots` 数量约束
        CAP_ACHIEVEMENT_SHOWCASE,    # ★ "花哨的展示方式"（`U7.4`）
    }
)

#: ★ 运营（staff）—— `U2.5`：★ **处理内容**
STAFF: FrozenSet[str] = FREE | frozenset(
    {
        CAP_PROJECT_REVIEW,   # ★ 审核队列（`U3.7`）
        CAP_PROJECT_HIDE,     # ★ 隐藏 / 下架 / 恢复（`U3.5`）
        CAP_REPORT_HANDLE,
        CAP_UGC_ADOPT,        # ★ 采纳
        CAP_UGC_MODERATE,     # ★ 删他人的
        CAP_ADMIN_AUDIT,
        CAP_INVITE_MANAGE,    # ★ 生成邀请（`U4.7`）
    }
)

#: ★★ 超管（superuser）—— `U2.5`：★ **改规则本身**
SUPERUSER: FrozenSet[str] = STAFF | VIP | frozenset(
    {
        CAP_ADMIN_SETTINGS,
        CAP_ADMIN_USERS,
        CAP_PROJECT_PUBLISH_ANY,   # ★★ **特批**（`U3.4`：无许可证 / 归属存疑时放行）
    }
)

#: 档位名 → 能力集
TIER_TABLE: dict[str, FrozenSet[str]] = {
    "anonymous": ANONYMOUS,
    "free": FREE,
    "vip": VIP,
    "staff": STAFF,
    "superuser": SUPERUSER,
}


# ===========================================================================
# 判定入口
# ===========================================================================

def capabilities_of(user: Any) -> FrozenSet[str]:
    """★ 取一个用户的能力集。

    ★★ **独立累加**（`U1` 的三条正交线）：

    | 线 | 判据 |
    |---|---|
    | **登录态** | `user.is_authenticated` |
    | **订阅层级** | `UserProfile.tier` |
    | **站点职权** | `user.is_staff` / `user.is_superuser` |

    ⚠ 三层**取并集** —— ★ 所以 `superuser` 天然拥有 VIP 的能力（见 `SUPERUSER` 定义）。
    ⚠ 本函数**只读已有属性**，❌ 不查库 —— ★ 需要 `tier` 时由调用方保证已加载。

    ★★ **三道前置检查（缺一不可）** —— ⚠ 这里踩过坑（`B144`）：

    | # | 检查 | ⚠ 不查会怎样 |
    |---|---|---|
    | **1** | `is_authenticated` | —— |
    | **2** | ★★ **`pk` 存在** | ⚠★ **Django 的 `User().is_authenticated` 永远是 `True`**（只有 `AnonymousUser` 才返回 `False`）⇒ ★ **一个"半成品"用户对象会通过权限检查** |
    | **3** | ★★ **`is_active`** | ⚠⚠ **管理员停用用户后，他仍然有权限** —— ★ 这是**真实的安全洞** |
    """
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return ANONYMOUS
    # ★ 停用账号 ⇒ 视为游客（⚠ 与"token 应该被认证层拒掉"是双保险）
    if not getattr(user, "is_active", True):
        return ANONYMOUS

    if getattr(user, "is_superuser", False):
        return SUPERUSER
    if getattr(user, "is_staff", False):
        base = STAFF
    else:
        base = None

    tier = _tier_of(user)
    tier_caps = VIP if tier == "vip" else FREE

    return tier_caps if base is None else (base | tier_caps)


def _tier_of(user: Any) -> str:
    """取订阅层级（⚠ 取不到就按 `free` —— ★ **fail-safe**，❌ 不能"取不到就当 VIP"）。"""
    profile = getattr(user, "profile", None)
    tier = getattr(profile, "tier", None)
    return tier if tier in ("free", "vip") else "free"


def can(user: Any, capability: str) -> bool:
    """★★ **唯一的权限判定入口**（`U5` 纪律 1）。

    ⚠ **项目级 / 条目级的附加约束不在这里** —— ★ 它由 `web/permissions.py` 组合：
    例如 `CAP_PROJECT_HIDE` 说明"你能管项目"，而"**能不能管这个项目**"要再看归属。

    ★ 判据：**能互相 import 的东西，迟早会长成一坨** ⇒ ★ 权限判定只留**一个**入口。
    """
    return capability in capabilities_of(user)


def tier_name(user: Any) -> str:
    """★ 用于展示 / 日志的档位名（⚠ 只是名字，❌ **不要用它做判定**）。"""
    # ★ 与 capabilities_of 同一套前置检查（`B144`）
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return "anonymous"
    if not getattr(user, "is_active", True):
        return "anonymous"
    if getattr(user, "is_superuser", False):
        return "superuser"
    if getattr(user, "is_staff", False):
        return "staff"
    return _tier_of(user)
