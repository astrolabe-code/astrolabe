"""Astrolabe · 共享内核：**上传限额**（防刷审核，`U3.9`）

> **用户原话**：「……还有一些**恶意刷审核**的，规定**一天或一周只能传几个项目**，
> **我不觉得一个人一天能做十几个解释**，那就类似 B 站的**水视频**了。
> 还有，这个**上传频率，管理员可控**，要是真有人，这么厉害，也得**给其创造空间**。」

---

# 一、★★ 为什么限额要按「**提交**」计次，而不是按「**通过**」计次

| 方案 | 结果 |
|---|---|
| ❌ 通过才计次 | ★★ 恶意刷的人**被驳回了也不占额度** ⇒ **可以无限刷** ⇒ **限额形同虚设** |
| ✅ **提交即计次** | ★★ 刷一次就少一次 ⇒ **防刷才真正成立** |

⚠★ 代价：**被误驳回的用户会亏额度**。
⇒ ★ 所以必须配一个**退还**动作（`ProjectReview.quota_refunded` + `reject(refund_quota=True)`）。

---

# 二、★★ 计数必须来自「流水」，❌ 不能数 `Project` 表

⚠★ 因为：★ **用户把项目删掉、再传一次，就绕过了限额。**

⇒ ★ 计数一律走 `ProjectReview`（**append-only 流水**，且它的 `project` 外键是
   **`SET_NULL`** ⇒ ★★ **项目删了，流水还在**）。

---

# 三、★★ 三级覆盖（`U6`）—— 「给厉害的人创造空间」

```
档位默认（代码常量）  →  参数覆盖（管理员改 AppSetting）  →  用户级覆盖（给某个人单独放宽）
                                                              ↑
                                                    UserProfile.quota_override
```

★ 所以"给某个人创造空间"**不需要改代码、不需要新表** ——
★ 管理员往那个用户的 `quota_override` 里写一行即可：

```python
# ★ 给某个 VIP 单独放到「一天 50 个」
user.profile.quota_override = {"project_per_day": 50, "project_per_week": 300}
user.profile.save(update_fields=["quota_override"])
```

★★ **`project_per_day = 0`（或负数）表示「不限制」** ——
   ★ 给"真的厉害"的人 / 官方账号 / 内部测试用的**彻底放行**口子。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from core import appsettings

# ===========================================================================
# 结论
# ===========================================================================

#: 允许
CODE_OK = "ok"
#: ★ 触到「日」上限
CODE_DAILY = "daily"
#: ★ 触到「周」上限
CODE_WEEKLY = "weekly"
#: ★ **同一个仓库重复提交** —— 防"改个名字反复刷"
CODE_DUPLICATE_REPO = "duplicate_repo"


@dataclass
class QuotaVerdict:
    """★ 限额判定结论 —— ★ **必须带上「为什么」和「什么时候能再来」**。

    ⚠★ 只告诉用户"你不能传了"是**不合格**的 ——
      ★ 他会反复重试（★ 反而**加重刷审核**）。
      ⇒ ★★ 必须说清 **① 为什么 ② 什么时候可以**
    """

    allowed: bool = True
    reason_code: str = CODE_OK
    #: ★★ 给用户看的说明（★ **说清原因 + 下次什么时候能传**）
    user_message: str = ""

    per_day: int = 0
    used_day: int = 0
    per_week: int = 0
    used_week: int = 0

    #: ★ **什么时候可以再提交**（⚠ 只在上限类拦截时才有）
    retry_after: datetime | None = None
    #: ★ 额度是从哪一层来的（`free` / `vip` / `user`）—— ★ 便于排查"为什么他被限了"
    source: str = ""
    #: ★★ 是否**不限制**（`project_per_day <= 0` 或总开关关闭）
    unlimited: bool = False

    @property
    def remaining_day(self) -> int:
        if self.unlimited or self.per_day <= 0:
            return 10**6
        return max(0, self.per_day - self.used_day)

    @property
    def remaining_week(self) -> int:
        if self.unlimited or self.per_week <= 0:
            return 10**6
        return max(0, self.per_week - self.used_week)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "user_message": self.user_message,
            "per_day": self.per_day,
            "used_day": self.used_day,
            "per_week": self.per_week,
            "used_week": self.used_week,
            "remaining_day": self.remaining_day,
            "remaining_week": self.remaining_week,
            "retry_after": self.retry_after.isoformat() if self.retry_after else None,
            "source": self.source,
            "unlimited": self.unlimited,
        }


# ===========================================================================
# 时间窗
# ===========================================================================

def day_start(now: datetime | None = None) -> datetime:
    """★ 本地时区的「今天 0 点」。

    ⚠★ 用 `localtime` 而不是 UTC —— ★ 否则"一天"的边界对用户来说是**半夜 8 点**（东八区），
      ★ 用户会觉得"明明说好一天 3 个，怎么刚过中午就没了"。
    """
    local = timezone.localtime(now or timezone.now())
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def week_start(now: datetime | None = None) -> datetime:
    """★ 本地时区的「本周一 0 点」。"""
    start = day_start(now)
    return start - timedelta(days=start.weekday())


# ===========================================================================
# 计数
# ===========================================================================

def count_submissions(user, *, since: datetime) -> int:
    """★ 某人从 `since` 起的**提交次数**（★ 这就是"刷了几次"）。

    ⚠★ 两条必须的纪律：

    ① ★ **走 `ProjectReview` 流水**，❌ 不数 `Project` 表
       —— 否则用户**删掉项目再传**就能绕过（见模块文档）。
    ② ★★ **排除已退还额度的**（`quota_refunded=True`）
       —— ★ 否则"退还"就只是个**安慰性字段**，用户白白亏额度。
    """
    from core.models import ProjectReview

    if not getattr(user, "pk", None):
        return 0
    return (
        ProjectReview.objects.filter(submitted_by=user, created_at__gte=since)
        .exclude(quota_refunded=True)
        .count()
    )


def _find_active_duplicate(user, repo_url: str):
    """★ 同一用户是否**已经提交过同一个仓库**（且那条**没被驳回**）。

    ★★ 防的是「**改个名字 / 反复提交同一个仓库**」这种刷法 ——
      ⚠ 单纯限制次数**挡不住它**（一天 3 次也能刷）。

    ★ 已驳回的**不算** —— ★ 用户改了东西想重传，应当允许。
    """
    from core.models import ProjectReview

    if not (repo_url or "").strip() or not getattr(user, "pk", None):
        return None
    return (
        ProjectReview.objects.filter(submitted_by=user, repo_url=repo_url.strip())
        .exclude(decision=ProjectReview.DECISION_REJECTED)
        .order_by("-created_at")
        .first()
    )


# ===========================================================================
# 判定
# ===========================================================================

def check_upload_quota(
    user, *, at: datetime | None = None, repo_url: str = "", profile=None
) -> QuotaVerdict:
    """★ **上传闸门** —— 能不能提交这次审核。

    ⚠★ 调用方**必须在事务里**（见 `core/submission.py`）——
      ★ 否则两个并发请求会**各自读到"还剩 1 个"**，双双通过（★ 经典的检查-使用竞态）。
    """
    # ---- ★ 总开关：管理员可以整体关掉（⚠ 只在被刷爆时才关）----
    if not appsettings.get_bool("quota.upload_limit"):
        return QuotaVerdict(
            allowed=True, reason_code=CODE_OK, source="disabled", unlimited=True,
            user_message="",
        )

    if profile is None:
        profile = getattr(user, "profile", None)

    tier = getattr(profile, "tier", None) or "free"
    quota = appsettings.quota_for(tier, profile)

    per_day = int(quota.get("project_per_day") or 0)
    per_week = int(quota.get("project_per_week") or 0)
    # ★ 额度来自哪一层（★ 便于回答"为什么他被限了"）
    source = "user" if (getattr(profile, "quota_override", None) or {}) else tier

    now = at or timezone.now()
    d0, w0 = day_start(now), week_start(now)
    used_day = count_submissions(user, since=d0)
    used_week = count_submissions(user, since=w0)

    verdict = QuotaVerdict(
        per_day=per_day, used_day=used_day, per_week=per_week, used_week=used_week,
        source=source,
    )

    # ---- ★★ `<= 0` = 不限制（给"真厉害的人"创造空间的口子）----
    if per_day <= 0 and per_week <= 0:
        verdict.unlimited = True
        return verdict

    # ---- ★ 重复仓库（★ 与次数无关，永远拦）----
    dup = _find_active_duplicate(user, repo_url)
    if dup is not None:
        verdict.allowed = False
        verdict.reason_code = CODE_DUPLICATE_REPO
        verdict.user_message = (
            f"这个仓库你已经提交过了（项目「{dup.project_name or dup.project_ref}」"
            f"，状态：{dup.get_decision_display()}），不用重复提交。\n"
            "★ 如果那是**另一次独立的构建**（例如换了版本），请先删掉旧项目再提交。"
        )
        return verdict

    # ---- ★ 日上限 ----
    if per_day > 0 and used_day >= per_day:
        verdict.allowed = False
        verdict.reason_code = CODE_DAILY
        verdict.retry_after = d0 + timedelta(days=1)
        verdict.user_message = (
            f"你今天已经提交了 {used_day} 个项目（每天最多 {per_day} 个），"
            f"请在 {timezone.localtime(verdict.retry_after):%m-%d %H:%M} 之后再试。\n"
            "★ 这样是为了防止刷审核，保证每个项目都被认真看过。"
        )
        return verdict

    # ---- ★ 周上限 ----
    if per_week > 0 and used_week >= per_week:
        verdict.allowed = False
        verdict.reason_code = CODE_WEEKLY
        verdict.retry_after = w0 + timedelta(days=7)
        verdict.user_message = (
            f"你这周已经提交了 {used_week} 个项目（每周最多 {per_week} 个），"
            f"请在 {timezone.localtime(verdict.retry_after):%m-%d %H:%M} 之后再试。"
        )
        return verdict

    return verdict


# ===========================================================================
# 给管理员：查某人还剩多少
# ===========================================================================

def describe_for_admin(user, *, at: datetime | None = None) -> dict[str, Any]:
    """★ 管理员视角：这个人还剩多少额度、额度是哪来的。

    ★ 用途：当用户来问"我为什么传不了"时，管理员**一眼能答**。
    """
    profile = getattr(user, "profile", None)
    tier = getattr(profile, "tier", None) or "free"
    quota = appsettings.quota_for(tier, profile)
    now = at or timezone.now()

    return {
        "user": getattr(user, "username", str(user)),
        "tier": tier,
        "quota_override": dict(getattr(profile, "quota_override", None) or {}),
        "project_per_day": int(quota.get("project_per_day") or 0),
        "project_per_week": int(quota.get("project_per_week") or 0),
        "used_day": count_submissions(user, since=day_start(now)),
        "used_week": count_submissions(user, since=week_start(now)),
        "refunded": _refunded_count(user),
        "upload_limit_enabled": appsettings.get_bool("quota.upload_limit"),
    }


def _refunded_count(user) -> int:
    """★ 被退还过几次（★ 便于看出"是不是总被误驳"）。"""
    from core.models import ProjectReview

    if not getattr(user, "pk", None):
        return 0
    return ProjectReview.objects.filter(submitted_by=user, quota_refunded=True).count()
