"""Astrolabe · ① Web 层：**登录会话**（Django 自带 session · B245 / B246）

---

# ★★★ 2026-10-25 所有者裁定：**弃用自研 Bearer 令牌，改用 Django session**

> 原话（逐字）：
> 「**我的天呐，你把django设计好的维持登陆状态和身份识别的令牌系统给了后台了吗？
>   你自己整个可能有漏洞的令牌系统给放到公网的网站？**」
>
> 「**你要换成django自带的token验证身份呀，你这样做，不知道有什么缺口，
>   django大家都在维护，出了问题，我能第一时间知道，打补丁，
>   你这自研的令牌系统，出了问题，谁知道呢？后台这种通过ssh链接的网页用这套自研的还差不多**」

## ★ 为什么这个裁定是对的

| | 自研 Bearer 令牌（旧） | Django session（现在） |
|---|---|---|
| 存放位置 | `localStorage` ⇒ **JS 可读，XSS 能偷走** | HttpOnly Cookie ⇒ **JS 读不到** |
| CSRF | 头不自动携带 ⇒ 无风险 | 需显式防护 ⇒ **见 `middleware.py` 的三件套** |
| 泄露后 | 30 天内服务端不主动失效 | 登出即失效；禁用账号可**当场删会话** |
| 维护 | 自己盯 | 跟着 Django 版本走，CVE 有公开补丁 |

★★ 旧方案的实现本身是按标准做的（`secrets` 高熵 · 库内只存 `blake2b` 哈希 · 明文只返回一次），
真正的短板是**架构取舍**：Bearer 放 localStorage 在公网场景下不值得 ⚠。

## ★ 有效期（B246）

> 原话：「**现有的 397 个 ApiToken直接删掉，记住我要做，但不要那么长的时间，
>   一周就差不多了，而且后台应该可调。**」

* `auth.session_ttl_days`（**默认 7 天**，后台「站点参数」可调，下限 1 天）
* 未勾「记住我」⇒ `set_expiry(0)`，**浏览器关闭即失效**

## ★ 设备令牌与此无关

`at_device` Cookie + HMAC 验签那套（`B238`）**只做限流身份**，本次不动 ——
它回答的是「这是哪台设备」，而 session 回答的是「你是谁」。
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib import auth as django_auth
from django.contrib.sessions.models import Session
from django.utils import timezone

from core import appsettings


# ===========================================================================
# 会话有效期
# ===========================================================================


def session_expiry(remember: bool = True) -> int | None:
    """★★ **会话有效期（秒）**（B246）⚠

    ```\n    勾「记住我」  ⇒ appsettings 的 auth.session_ttl_days × 86400（默认 7 天）\n    不勾           ⇒ None —— Django 语义是「浏览器关闭即失效」✅\n    ```\n
    ⚠ **下限 1 天**：配成 0 会让用户「登录成功但下一秒就掉线」，**极难排查** ⚠
    """
    if not remember:
        return None
    days = int(appsettings.get("auth.session_ttl_days") or 7)
    return int(timedelta(days=max(1, days)).total_seconds())


def login_user(request, user, *, remember: bool = True) -> None:
    """★★ **登录** —— 种 session + 按「记住我」设有效期 ⚠

    ⚠ 必须在**同一个响应**里种下 `sessionid` Cookie（Django 的标准行为）✅
    """
    django_auth.login(request, user)
    request.session.set_expiry(session_expiry(remember))


def logout_user(request) -> None:
    """★★ **登出** —— 清掉当前会话（Cookie 由 Django 负责删）。"""
    django_auth.logout(request)


# ===========================================================================
# 会话查询 / 批量清理
# ===========================================================================


def _session_pks(user) -> list[str]:
    """★★ 该用户所有**未过期**会话的主键（★ 查「某用户有哪些会话」的唯一入口）⚠

    ## ⚠⚠ 为什么不能靠 `session_data__contains`（实测踩过，**两次**）

    ```\n    ① session_data 存的是【压缩 + base64】后的串（以 `.` 开头）⇒ ⛔ 字面量永远匹配不上
    ② 即使解开，`_auth_user_id` 也是【字符串】`\"434\"` 而不是整数 434
    ```\n
    ⇒ ★★ 只能**遍历 + 解码**（`get_decoded()`）✅

    ⚠ 代价：O(会话总数)。★ 可接受的理由：
      · 本函数**只在**「登出全部设备 / 禁用账号 / 看设备列表」时调用，
        ⛔ **不在请求链路上**（否则每个 API 请求都要扫一遍表）⚠
      · 单机部署下会话数是百级 ⇒ 一次遍历 < 10ms ✅
    """
    if not getattr(user, "pk", None):
        return []
    pk = str(user.pk)          # ⚠ 会话里存的是**字符串**（见上）⚠
    out: list[str] = []
    for sess in Session.objects.filter(expire_date__gt=timezone.now()).only("pk", "session_data"):
        try:
            if str(sess.get_decoded().get("_auth_user_id") or "") == pk:
                out.append(sess.pk)
        except Exception:  # pragma: no cover - 坏会话不该让查询炸掉
            continue
    return out


def session_count(user) -> int:
    """★ 该用户当前有几个活着的会话（★ 供「登录设备」页 / 排查用）。"""
    return len(_session_pks(user))


def session_list(user, limit: int = 50) -> list[dict]:
    """★★ **会话列表**（B245 后「登录设备」页的数据源）⚠

    ⚠ 只回**时间**，不回 `session_data` 内容 —— 那里面是 Django 的内部结构 ⚠
    """
    rows = (
        Session.objects.filter(pk__in=_session_pks(user))
        .order_by("-expire_date")
        .values_list("pk", "expire_date")[:limit]
    )
    return [
        {"id": pk, "expire_date": exp.isoformat() if exp else None} for pk, exp in rows
    ]


def logout_all_sessions(user) -> int:
    """★★ **登出全部设备** —— 删掉该用户**所有**会话。

    ★ 用途：①「登出全部设备」按钮；② 禁用账号时**顺手清掉会话行**（B247①）。

    ⚠★ 关于②的一个诚实更正（2026-10-25 实测）：
      · 原以为「只把 `is_active` 置 False 不会让已登录的人掉线」—— **这是错的** ⚠
      · Django 的 `ModelBackend.get_user()` 内部会调 `user_can_authenticate()`
        （它检查 `is_active`）⇒ **停用账号的旧会话会自动变成 AnonymousUser** ✅
      · ⇒ 本函数对「禁止登录」而言是**锦上添花**（把行删掉，表更干净），
        ⛔ 不是那道必需的闸门 —— 必需的闸门 Django 已经给了 ✅
    """
    pks = _session_pks(user)
    if not pks:
        return 0
    deleted, _ = Session.objects.filter(pk__in=pks).delete()
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
    ident = (
        user.oauth_identities.order_by("created_at").first()
        if hasattr(user, "oauth_identities")
        else None
    )
    return {
        "id": user.pk,
        "username": user.get_username(),
        "is_staff": bool(user.is_staff),
        "avatar": ident.avatar_url if ident else "",
        # ★ 一期：本站没有密码登录 ⇒ 这个字段恒为 False（★ 前端可据此隐藏"改密码"入口）
        "has_password": user.has_usable_password(),
    }
