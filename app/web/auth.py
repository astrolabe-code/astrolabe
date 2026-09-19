"""Astrolabe · ① Web 层：**Bearer 令牌**（签发 / 校验 / 撤销）

★ 依据 `USERS-AND-AUTH.md` `U4.4` 纪律 1 + `frontend-contract.md` §12。

---

# ★★ 唯一的硬纪律：**明文只返回一次，库里只存哈希**

| | |
|---|---|
| ★ 明文 | ★ **只在签发的那一刻返回**（此后服务端**再也拿不到**） |
| ★ 库里 | ★ **`blake2b(raw, digest_size=32)` 的 hex** |

★★ 为什么用 **`blake2b` 而不是 `make_password`**：★ token 是**高熵随机串**，
爆破物理上不可能 ⇒ 慢哈希只是**白白拖慢每个请求**。★ 契约 §12 也是这个口径。

---

# ★★ 一个容易忽略的工程细节：**`last_used_at` 不能每个请求都写**

⚠★ 它看着无害，其实是**写放大**：每个 API 请求都 UPDATE 一行 ⇒
★ 在只读为主的站点上，**把一个纯读请求变成了写请求**（⚠ 还会撑大 WAL、加剧 autovacuum）。

⇒ ★ 只在「距上次记录超过 `_TOUCH_INTERVAL`」时才写。

---

# ★ 撤销的两种粒度

| 场景 | 函数 |
|---|---|
| ★ 登出（撤销**这一个**令牌） | `revoke_token()` |
| ★★ **登出全部设备**（`U4.4` / 契约 §12 的 `--revoke-user`） | `revoke_all()` |
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

from core import appsettings
from core.models import ApiToken

#: ★ 明文前缀 —— ★ 让令牌在日志 / 密钥扫描器里**一眼可辨**（⚠ 也便于排查泄露）
TOKEN_PREFIX = "ast_"

#: ★ 随机字节数 —— `token_urlsafe(32)` ⇒ 约 43 字符，**熵 ≈ 256 bit**
TOKEN_BYTES = 32

#: ⚠ `last_used_at` 的写节流（秒）—— ★ 见模块文档的"写放大"
_TOUCH_INTERVAL = 300


# ===========================================================================
# 生成 / 哈希
# ===========================================================================


def new_raw_token() -> str:
    """★ 生成一个**猜不到**的令牌明文。"""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw: str) -> str:
    """★ `blake2b(raw, digest_size=32)` 的 hex（64 字符）—— ★ **库里只存它**。

    ⚠★ 这是**查 token 的唯一入口**：★ 用哈希本身做等值查询，❌ 不存在"比较明文"这一步
      （⇒ ★ 也就没有 `==` 的时序侧信道问题）。
    """
    return hashlib.blake2b((raw or "").encode("utf-8"), digest_size=32).hexdigest()


def _prefix_of(raw: str) -> str:
    """★ 明文前 12 位 —— ⚠ 只用于**辨认**（★ 远不足以还原 32 字节随机串）。"""
    return (raw or "")[:12]


# ===========================================================================
# 签发 / 校验 / 撤销
# ===========================================================================


def _ttl(remember: bool = True) -> timedelta:
    key = "auth.token_ttl_days" if remember else "auth.token_ttl_days_short"
    days = int(appsettings.get(key) or (30 if remember else 7))
    # ⚠ 下限 1 天 —— ★ 不允许配置成 0/负数（那会签发一个**立刻失效**的令牌，
    #   ⚠ 表现为"登录成功了但下一秒就 401"，**极难排查**）
    return timedelta(days=max(1, days))


def issue_token(
    user,
    *,
    provider: str = "",
    user_agent: str = "",
    remember: bool = True,
) -> tuple[str, ApiToken]:
    """★ 签发令牌。

    Returns:
        `(明文, ApiToken)` —— ★★ **明文只有这一次机会**，⚠ 调用方必须立刻返回给前端，
        而且**不要记进日志**。
    """
    raw = new_raw_token()
    token = ApiToken.objects.create(
        user=user,
        token_hash=hash_token(raw),
        prefix=_prefix_of(raw),
        provider=(provider or "")[:16],
        user_agent=(user_agent or "")[:200],
        expires_at=timezone.now() + _ttl(remember),
    )
    return raw, token


def verify_token(raw: str, *, touch: bool = True) -> ApiToken | None:
    """★ 校验令牌 —— ★ 无效 / 过期 / 已撤销一律返回 `None`（⚠ 调用方**不区分**这三者）。

    ⚠★ 为什么调用方不该区分：★ 对攻击者来说它们**没有区别**
      （"这个 token 存在但过期了"同样是**免费的信息**）。
      ★ 用户看到的都应该是同一句「登录状态已失效，请重新登录」。
    """
    if not raw or not raw.startswith(TOKEN_PREFIX):
        # ⚠ 快速排除明显不是令牌的串 —— ★ 省一次数据库查询
        #   （⚠ 不靠它做安全判定：真正的判定是下面的哈希查询）
        return None

    token = ApiToken.objects.select_related("user").filter(token_hash=hash_token(raw)).first()
    if token is None or not token.is_valid():
        return None

    if touch:
        now = timezone.now()
        last = token.last_used_at
        # ★ 写节流 —— ⚠ 见模块文档（不这么做就把纯读请求变成了写请求）
        if last is None or (now - last).total_seconds() >= _TOUCH_INTERVAL:
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
            token.last_used_at = now
    return token


def revoke_token(token: ApiToken) -> bool:
    """★ 撤销**一个**令牌（登出）。

    ★ **幂等**（契约 §12：`data:{revoked:bool}`）—— ⚠ 重复登出不算错。
    """
    if token is None or token.revoked_at is not None:
        return False
    ApiToken.objects.filter(pk=token.pk).update(revoked_at=timezone.now())
    return True


def revoke_all(user) -> int:
    """★★ **登出全部设备** —— 撤销该用户所有**还活着**的令牌。

    ★ 用途：★ **怀疑令牌泄露**时的止血手段（契约 §12 的 `--revoke-user`）。
    """
    if not getattr(user, "pk", None):
        return 0
    return ApiToken.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def active_tokens(user):
    """★ 该用户还活着的令牌（★ 供"登录设备"页面用）。"""
    return ApiToken.objects.filter(user=user, revoked_at__isnull=True).order_by("-created_at")


def purge_expired(*, days: int = 30) -> int:
    """★ 清理**早已过期**的令牌（⚠ 否则这张表会无限增长）。

    ⚠ 刻意留 `days` 天缓冲再删 —— ★ 因为"过期"与"可以忘掉"不是同一件事：
      ★ 用户可能正是在过期后才来查"我上次是哪台设备登的"。
    """
    cutoff = timezone.now() - timedelta(days=max(0, days))
    deleted, _ = ApiToken.objects.filter(expires_at__lt=cutoff).delete()
    return deleted


# ===========================================================================
# 序列化
# ===========================================================================


def user_json(user) -> dict:
    """★ 用户的**公开投影**（契约 §12：`user:{id,username,is_staff,avatar}`）。

    ⚠★ 刻意**不返回** `email` / `is_superuser` / `last_login` ——
      ★ 前端用不到，而**多给一个字段就多一分泄露面**。
    """
    if user is None:
        return {}
    ident = user.oauth_identities.order_by("created_at").first() if hasattr(user, "oauth_identities") else None
    return {
        "id": user.pk,
        "username": user.get_username(),
        "is_staff": bool(user.is_staff),
        "avatar": ident.avatar_url if ident else "",
        # ★ 一期：本站没有密码登录 ⇒ 这个字段恒为 False（★ 前端可据此隐藏"改密码"入口）
        "has_password": user.has_usable_password(),
    }


def token_json(token: ApiToken) -> dict:
    """★ 令牌的公开投影（★ 供"登录设备"页面 —— ⚠ 绝不含明文）。"""
    return {
        "id": token.pk,
        "prefix": token.prefix,
        "provider": token.provider,
        "created_at": token.created_at.isoformat() if token.created_at else None,
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
    }
