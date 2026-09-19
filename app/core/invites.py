"""Astrolabe · 共享内核：**邀请机制**（`U4.7` / `U4.8`）

> **用户原话（`B141`）**：「**必须还有邀请注册机制**，我要先做一些**公开上线测试**，
> ★★ **不能让任何人都能注册，必须是我邀请到的人**。」

---

# ★★ 为什么这个策略是对的

★★ 它是**「读开放 + 写邀请」**的组合 —— ★ 而这正是**冷启动的正确姿势**：

| | 策略 | 为什么 |
|---|---|---|
| ★ **读** | ★★ 完全开放（连游客都能完整读） | ★ 能被搜索引擎收录、能被分享 ⇒ **有流量** |
| ★★ **写** | ★★ **邀请制** | ★★ 早期**内容质量比数量重要得多** |

★★★ 一句话：★ **「让人随便看，但只让信得过的人写。」**

---

# ★★ 本模块最容易写错的地方：**并发核销**

⚠★ 天真的写法：

```python
invite = Invite.objects.get(token=token)
if invite.used_count < invite.max_uses:      # ← 两个请求同时读到 0 < 1
    invite.used_count += 1                   # ← 双双 +1 ⇒ 【超发】
    invite.save()
```

★★ 结果：★ **一次性邀请码被用了两次** ⇒ 邀请制**当场失效**。

⇒ ★★ 正确做法：**`select_for_update` 锁住这一行**，让同一个 token 的核销**串行**。

---

# ★★ 核销必须与「建号」在**同一个事务**里（`U4.8`）

⚠★ 否则会出现：★ **码被消耗了，但账号没建成** ⇒ ★★ 用户**白白损失一个邀请码**，
而他**没有任何办法自证**（他也拿不出码的另一个副本）。

★ 本模块的 `redeem()` 自己开 `transaction.atomic()` ——
★ 若调用方**已经在事务里**，Django 会让它成为**保存点** ⇒
★★ **两种用法都安全**（外层回滚时，核销也会一起回滚）。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core import appsettings
from core.models import AuditLog, Invite, UserProfile
from core.submission import ensure_profile

# ===========================================================================
# 凭证
# ===========================================================================

#: ★★ token 的随机字节数 —— `token_urlsafe(24)` ⇒ **32 个字符**
#:   ★ 熵 ≈ 192 bit ⇒ ★ **爆破在物理上不可能**（⚠ 这条正是"不用短码"的理由）
TOKEN_BYTES = 24


def new_token() -> str:
    """★ 生成一个**猜不到**的邀请凭证。"""
    return secrets.token_urlsafe(TOKEN_BYTES)


# ===========================================================================
# 结论
# ===========================================================================

@dataclass
class InviteCheck:
    """★ 预检结论（★ 注册流程**先用它问"这个码能用吗"**，再决定要不要往下走）。"""

    ok: bool = False
    invite: Invite | None = None
    #: ★★ **给用户看的说明** —— ⚠ 必须说清**为什么不能用**（★ 否则用户会以为是网络问题）
    message: str = ""

    @property
    def invited_by_name(self) -> str:
        return (self.invite.created_by_name or "") if self.invite else ""


@dataclass
class RedeemResult:
    """★ 核销结论。"""

    ok: bool = False
    invite: Invite | None = None
    message: str = ""
    #: ★ 核销后的已用次数（★ 便于后台显示"这个码用掉了没"）
    used_count: int = 0


@dataclass
class RegistrationGate:
    """★ 注册门禁（★ `U4.6` 三个开关的组合结果）。"""

    allowed: bool = False
    invite_required: bool = False
    #: ★ 整站停服（`paused`）—— ⚠ 它的优先级**高于**一切
    paused: bool = False
    registration_open: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "invite_required": self.invite_required,
            "paused": self.paused,
            "registration_open": self.registration_open,
            "message": self.message,
        }


# ===========================================================================
# 门禁（★ 注册 / OAuth 首次登录都要先过这一关）
# ===========================================================================

def registration_gate(*, settings_map: dict[str, Any] | None = None) -> RegistrationGate:
    """★★ **注册门禁** —— ★★ 这是 `U4.8` 那个「最容易漏的洞」的**唯一入口**。

    ⚠★★ `U4.8` 的错误写法：★ **只给"注册页"加邀请码，而"从 GitHub 登录"这条路不加**
      ⇒ ★★ **任何人都能靠"用 GitHub 登录一次"绕过邀请制**。

    ⇒ ★ 所以：★ **无论从哪条路进来（注册表单 / OAuth 回调），都必须先问这一个函数。**
      ★ 把判断收敛在**一处**，❌ 不要在两处各写一遍 ——
      ⚠ 两处写一遍，**早晚有一处会漏**。
    """
    s = settings_map or appsettings.all_settings()

    if s.get("paused"):
        return RegistrationGate(
            allowed=False, paused=True, registration_open=bool(s.get("registration_open")),
            message="站点正在维护，暂时无法注册。",
        )
    if not s.get("registration_open"):
        return RegistrationGate(
            allowed=False, registration_open=False,
            message="本站当前未开放注册，请等待邀请。",
        )
    return RegistrationGate(
        allowed=True,
        invite_required=bool(s.get("invite_required")),
        registration_open=True,
        message="",
    )


# ===========================================================================
# 创建 / 作废
# ===========================================================================

def create_invite(
    by,
    *,
    max_uses: int | None = None,
    valid_days: int | None = None,
    note: str = "",
    allow_no_expiry: bool = False,
) -> Invite:
    """★ 生成一个邀请（★ 默认从参数中心取）。

    ★ 默认值落在 `AppSetting`（★ **可配置，❌ 不硬编码**）：
      `invite.default_uses` / `invite.default_valid_days`。

    ⚠★★ **`valid_days <= 0` 直接 `raise`，❌ 不静默变成"永不过期"** ——
      ★ 这是被冒烟测试抓出来的：★ 原先写成
      `expires_at = ... if valid_days > 0 else None` ⇒
      ⚠★ **传 -1 会得到一个「永不过期」的邀请码**，正好**违反 `U4.7` 规则 2**
      （「必须有过期时间 —— 否则泄露了就永久有效」）。

      ⇒ ★ 本项目的纪律是 ★ **让错误在开发期暴露**（同 `ProjectReview.reject()`）：
        ★ 真要"永不过期"，必须**显式**写 `allow_no_expiry=True`。
    """
    if max_uses is None:
        max_uses = int(appsettings.get("invite.default_uses") or 1)
    if valid_days is None:
        valid_days = int(appsettings.get("invite.default_valid_days") or 7)

    max_uses = max(1, int(max_uses))

    if valid_days <= 0 and not allow_no_expiry:
        raise ValueError(
            f"邀请有效期必须 > 0（收到 {valid_days}）—— "
            "U4.7 规则 2 要求邀请必须有过期时间；"
            "如确实要永不过期，请显式传 allow_no_expiry=True"
        )

    expires_at = timezone.now() + timedelta(days=valid_days) if valid_days > 0 else None

    invite = Invite.objects.create(
        token=new_token(),
        created_by=by if getattr(by, "pk", None) else None,
        created_by_name=(getattr(by, "username", "") or "")[:150],
        max_uses=max_uses,
        expires_at=expires_at,
        note=note[:200],
    )

    # ★ **管理动作必留痕**（`U2.5` 纪律 1）
    AuditLog.objects.create(
        actor=by if getattr(by, "pk", None) else None,
        action="invite.create",
        target_kind="Invite",
        target_id=str(invite.pk),
        detail={
            "token_prefix": invite.token[:8],
            "max_uses": max_uses,
            "valid_days": valid_days,
            "note": note[:200],
        },
    )
    return invite


def revoke(invite: Invite, *, by=None) -> Invite:
    """★ **作废**一个邀请（★ 还没用完也能收回 —— 比如发现它被转发了）。"""
    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at", "updated_at"])

    AuditLog.objects.create(
        actor=by if getattr(by, "pk", None) else None,
        action="invite.revoke",
        target_kind="Invite",
        target_id=str(invite.pk),
        detail={"token_prefix": invite.token[:8], "used_count": invite.used_count},
    )
    return invite


# ===========================================================================
# 预检
# ===========================================================================

def check(token: str, *, at: datetime | None = None) -> InviteCheck:
    """★ 预检一个邀请凭证（★ 注册流程的第一步）。

    ★ 用途：★ **先问"能用吗"，再决定要不要让用户填后面的东西** ——
      ⚠ 让用户填完一整张表才告诉他"码过期了"，是纯粹的折磨。
    """
    token = (token or "").strip()
    if not token:
        return InviteCheck(ok=False, message="缺少邀请凭证。")

    invite = Invite.objects.filter(token=token).first()
    if invite is None:
        # ⚠ 刻意不区分"码不存在"和"码写错了" —— ★ 两者对用户是同一件事，
        #   而★ 区分开只会给爆破者**免费的反馈信号**
        return InviteCheck(ok=False, message="邀请链接无效，请确认链接是否完整。")

    if not invite.is_usable(at):
        return InviteCheck(ok=False, invite=invite, message=invite.reject_reason(at))

    return InviteCheck(ok=True, invite=invite, message="")


# ===========================================================================
# 核销（★★ 原子）
# ===========================================================================

def redeem(token: str, user, *, at: datetime | None = None) -> RedeemResult:
    """★★ **核销** —— ★★ 必须在与「建号」同一个事务里调用（见模块文档）。

    ★★ 正确性由两件事保证：

    | # | 手段 | 保证什么 |
    |---|---|---|
    | **1** | **`select_for_update` 锁住 token 那一行** | ★★ 同一个 token 的核销**串行** ⇒ **不超发** |
    | **2** | **同一个事务**内完成「写 `invited_by` + `used_count += 1`」 | ★ 不会出现「码用掉了但人没进来」 |

    ★★★ 另外硬守 `U4.7` 规则 4：★ **核销【不碰 `tier`】** ——
      ★★ 邀请**永远不产生 VIP**（`Invite` 里**根本没有** tier 字段 ⇒ ★ 结构上就做不到）。
    """
    now = at or timezone.now()
    token = (token or "").strip()
    if not token:
        return RedeemResult(ok=False, message="缺少邀请凭证。")

    with transaction.atomic():
        # ---- ★★ ① 锁住这一行（★ 防并发超发的【唯一】手段）----
        invite = Invite.objects.select_for_update().filter(token=token).first()
        if invite is None:
            return RedeemResult(ok=False, message="邀请链接无效，请确认链接是否完整。")

        profile = ensure_profile(user)
        if profile is None:
            return RedeemResult(ok=False, invite=invite, message="用户不存在。")

        # ---- ★★ ② **账号级**检查放在【凭证级】之前（★ 顺序有讲究，见下）----
        #   ⚠★ 如果先判凭证，一个"自己已经注册过、又点了同一个链接"的用户会看到
        #      「**这个邀请链接已经被用过了**」⇒ ★ 他会以为**码被别人抢了**，
        #      ⚠ 而真实原因是**他自己已经用过了**。
        #   ★★ 这违反 `U3.8` 的原则：**必须说清真正的原因**（错的原因 = 误导用户）。
        if profile.invited_by_id is not None:
            return RedeemResult(
                ok=False, invite=invite, message="这个账号已经通过邀请注册过了。"
            )

        if not invite.is_usable(now):
            return RedeemResult(
                ok=False, invite=invite, message=invite.reject_reason(now)
            )

        # ---- ★★ ③ 连带责任：记录「谁邀请了谁」（`U4.7` 规则 3）----
        profile.invited_by = invite.created_by
        # ⚠★ 这里**只写 invited_by**，❌ **绝不碰 `tier`** ——
        #   ★★ 见 `U4.7` 规则 4：通过邀请进来的**只能是 free**
        profile.save(update_fields=["invited_by", "updated_at"])

        # ---- ★ ④ 计数（★ 持锁状态下读改写 ⇒ 安全）----
        invite.used_count += 1
        invite.save(update_fields=["used_count", "updated_at"])

        # ---- ★ ⑤ 审计 ----
        AuditLog.objects.create(
            actor=user if getattr(user, "pk", None) else None,
            action="invite.redeem",
            target_kind="Invite",
            target_id=str(invite.pk),
            detail={
                "token_prefix": invite.token[:8],
                "invited_by": invite.created_by_name or None,
                "used_count": invite.used_count,
                "max_uses": invite.max_uses,
            },
        )

        return RedeemResult(ok=True, invite=invite, used_count=invite.used_count)


# ===========================================================================
# 查询
# ===========================================================================

def list_invites(*, by=None, usable_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    """★ 邀请列表（★ 后台用）。"""
    qs = Invite.objects.all()
    if getattr(by, "pk", None):
        qs = qs.filter(created_by=by)
    if usable_only:
        # ⚠ 这里过滤掉的是「已作废 / 已用尽」；★ 「是否过期」由 `is_usable()` 判
        #   （★ 因为过期要拿 `now` 比，交给 Python 更不容易写错时区）
        qs = qs.filter(revoked_at__isnull=True, used_count__lt=F("max_uses"))
    qs = qs.order_by("-created_at")[:limit]
    return [
        {
            "token": i.token,
            "invited_by": i.created_by_name,
            "used": i.used_count,
            "max_uses": i.max_uses,
            "expires_at": i.expires_at.isoformat() if i.expires_at else None,
            "usable": i.is_usable(),
            "note": i.note,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in qs
    ]


def who_invited(user) -> dict[str, Any] | None:
    """★ **连带责任查询**：这个用户是谁邀请进来的。

    ★★ 用途（`U4.7` 规则 3）：★ **有人邀请垃圾账号进来，要能找到邀请人。**
    """
    profile = getattr(user, "profile", None)
    inviter = getattr(profile, "invited_by", None) if profile else None
    if inviter is None:
        return None
    return {
        "user": getattr(user, "username", str(user)),
        "invited_by": getattr(inviter, "username", str(inviter)),
        "invited_by_id": inviter.pk,
        # ★ 这个人一共邀请了几个（★ 一多就值得看一眼）
        "invited_count": type(inviter).objects.filter(profile__invited_by=inviter).count(),
    }
