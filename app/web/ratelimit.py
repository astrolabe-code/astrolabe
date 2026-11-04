"""★★ **搜索类请求的统一限流**（`B238` · 2026-10-23）⚠

## ★★★ 所有者原话（逐字）

> 「项目搜索限流，你这搜索限流不能统一一下吗？一会发现这里少加了，一会儿发现哪里
>   少加了，没发现的就漏了，直接在任何可以搜索的窗口前，加一个后端验证是不是被限流了，
>   没限流，才去真正触发搜索。」

## ★★ 为什么要"统一"

```
逐个接口加 @限流 ⇒ 新加一个搜索接口就漏一个（项目搜索就是这么漏的）
⇒ 改成**按请求特征**统一判定：`GET /api/*` 且带非空 `q`，就是一次搜索 ✅
```

## ★ 身份与速率

```
u<id>   登录用户        10 次/秒
a<ip>   匿名（按 IP）   10 次/秒   ← 2026-11-04 起：不再有设备令牌
anon    取不到 IP       10 次/秒   （理论上不会发生）
```

⚠★ 失败**放行**：限流是保护手段，Redis 挂了不该让搜索不可用 ✅
"""
from __future__ import annotations

import logging
import time

from django.http import JsonResponse

from search import terms

logger = logging.getLogger("astrolabe.ratelimit")


def identity(request) -> str:
    """★ 请求的身份（* 登录 > 设备 > 匿名）⚠"""
    from web.permissions import current_user

    user = current_user(request)
    if user is not None and getattr(user, "pk", None):
        return f"u{user.pk}"

    # ★★★ 2026-11-04：设备令牌已删除（所有者：「效果没多少，判断还多，没必要」）
    #   ⇒ 匿名一律按**真实 IP** 计账（`a<ip>`）；⚠ 真实 IP 要等自建隧道接入后才有意义
    from core.device import client_ip

    ip = client_ip(request)
    return f"a{ip}" if ip else "anon"


def is_search_request(request) -> bool:
    """★ 这次请求算不算"搜索"（* 只看 GET /api/* 且 q 非空）⚠"""
    if request.method != "GET":
        return False
    if not request.path.startswith("/api/"):
        return False
    return bool((request.GET.get("q") or "").strip())


def check(request, scope: str = "search") -> JsonResponse | None:
    """★★ 超限就返回 429，* 未超限返回 None（调用方继续处理）⚠"""
    if not is_search_request(request):
        return None

    who = identity(request)
    limit = terms.rate_limit_for(who)
    if terms.allow(scope, who, limit):
        return None

    _bump_hit(scope, request)

    from web.permissions import current_user

    user = current_user(request)
    logged_in = user is not None and getattr(user, "pk", None) is not None

    message = (
        "搜得有点快啦，歇一秒再试试～"
        if logged_in
        else "这会儿搜索的人有点多，先喘口气～登录后就是你的专属通道，不用和大家挤在一起。"
    )
    resp = JsonResponse(
        {
            "ok": False,
            "error": {"code": "rate_limited", "message": message},
            "data": {"login_hint": not logged_in},
        },
        status=429,
    )
    resp["Retry-After"] = "1"
    return resp


def _bump_hit(scope: str, request=None) -> None:
    """★ 记一次"被限流"（* 用来判断限流是不是误伤）⚠"""
    try:
        from django.utils import timezone

        r = terms._redis()
        key = f"astrolabe:rl:hits:{scope}:{timezone.localdate().isoformat()}"
        r.incr(key)
        r.expire(key, 172800)
    except Exception:
        pass

    # ★ 审计：**是谁**被限流了（原来只有全局日计数，看不出人）⚠
    if request is not None:
        try:
            from core import access_audit, device

            access_audit.record("rate_limited", device.client_ip(request), identity(request))
        except Exception:  # pragma: no cover
            pass


# ===========================================================================
# ★★★ 写操作限流（P2a · 2026-11-04）
# ===========================================================================
#
# 依据 RATE-LIMIT.md 5.2：
#   发布 / 删除 / 修改   30 次/分钟（按用户）
#   导出                 2 次/分钟（500 篇同步生成有内存峰值，5.2 已降到 2）
#
# ⚠ 只按**用户**计账（`u<id>`）：写操作本来就要登录，与真实 IP 无关 ⇒
#   P4 之前也能上（这是 P2a 能排在 IP 分段之前的原因）。
# ⚠ 匿名写请求不在这里判 —— 它们会在视图层被 401/403 挡掉，不需要额外限流。

#: 一般写操作：每分钟多少次
WRITE_LIMIT_PER_MIN = 30
#: 导出：每分钟多少次（⚠ 比一般写操作严，原因见上）
EXPORT_LIMIT_PER_MIN = 2

#: 算"导出"的路径前缀（500 篇上限那个接口）
EXPORT_PREFIXES = ("/api/me/deleted/export/",)

#: 不算"写操作"的路径（⚠ 登录/登出有自己的失败计数，混进来会互相干扰）
WRITE_EXEMPT_PREFIXES = ("/api/auth/",)


def is_write_request(request) -> bool:
    """★ 这次请求算不算"写操作"（⚠ 只看方法 + 路径，不看业务）"""
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    path = request.path or ""
    if not path.startswith("/api/"):
        return False
    return not any(path.startswith(prefix) for prefix in WRITE_EXEMPT_PREFIXES)


def is_export_request(request) -> bool:
    return any((request.path or "").startswith(p) for p in EXPORT_PREFIXES)


def allow_window(scope: str, who: str, limit: int, window: int) -> bool:
    """★★ **固定窗口限流**（* 每 `scope + 身份 + 窗口` 一个计数键）⚠

    ⚠ 失败**放行**：限流是保护手段，Redis 挂了不该让写操作全部失败
      （⚠ 与"登录计数 fail-closed"不同 —— 那个是认证闸门，这个是保护措施）
    """
    try:
        from search import terms

        r = terms._redis()
        key = f"astrolabe:rl:{scope}:{who}:{int(time.time()) // window}"
        n = r.incr(key)
        if n == 1:
            r.expire(key, window * 2)
        return n <= limit
    except Exception:
        return True


def check_write(request, scope: str = "write") -> JsonResponse | None:
    """★★ 写操作超限就返回 429，* 未超限返回 None（调用方继续处理）⚠"""
    if not is_write_request(request):
        return None

    who = identity(request)
    if who == "anon":
        # ⚠ 匿名写请求后面一定会被拒（401/403）⇒ 不用额外限流
        return None

    if is_export_request(request):
        scope, limit = "export", EXPORT_LIMIT_PER_MIN
    else:
        limit = WRITE_LIMIT_PER_MIN

    if allow_window(scope, who, limit, 60):
        return None

    _bump_hit(scope, request)
    message = (
        f"操作太频繁了（每分钟最多 {limit} 次），歇一下再试～"
    )
    resp = JsonResponse(
        {
            "ok": False,
            "error": {"code": "rate_limited", "message": message},
            "data": {"scope": scope, "limit": limit},
        },
        status=429,
    )
    resp["Retry-After"] = "60"
    return resp


# ===========================================================================
# ★★★ 读接口限流（P2b-1 · 2026-11-04）
# ===========================================================================
#
# 依据 RATE-LIMIT.md 5.1：
#   列表 / 详情（普通读，**不带 q**）  登录用户 30 次/秒
#   搜索（带 q）                      登录用户 10 次/秒  ← 已有（`check()`）
#
# ⚠★ **本阶段只收紧登录用户**（P2b-1）：
#   匿名的额度调整（5 次/秒、按 IP 分桶）要等 P4 —— 在那之前 `a<ip>` 就是网关，
#   收紧它会变成"全站匿名合计 5 次/秒"，日活几百的站高峰期会被自己打满（N1）。
#   ⇒ 匿名**本阶段完全不动**：普通读不新增限流，搜索维持现状（全站共享 10 次/秒）。

#: 登录用户：普通读每秒多少次
READ_LIMIT_PER_SEC = 30


def is_read_request(request) -> bool:
    """★ 算不算"普通读"（GET/HEAD + /api/ + **不带 q**）⚠

    ⚠ 带 `q` 的是搜索，归 `check()` 管（10 次/秒），这里必须排除，
      否则一次搜索会被记两笔。
    """
    if request.method not in ("GET", "HEAD"):
        return False
    if not (request.path or "").startswith("/api/"):
        return False
    return not is_search_request(request)


def check_read(request) -> JsonResponse | None:
    """★★ 登录用户的普通读超限 ⇒ 429；匿名与未超限 ⇒ None ⚠"""
    if not is_read_request(request):
        return None

    who = identity(request)
    # ⚠ P2b-1：只收紧登录用户（匿名额度调整要等 P4，见文件上方说明）
    if not who.startswith("u"):
        return None

    from search import terms

    if terms.allow("read", who, READ_LIMIT_PER_SEC):
        return None

    _bump_hit("read", request)
    resp = JsonResponse(
        {
            "ok": False,
            "error": {
                "code": "rate_limited",
                "message": f"请求太快了（每秒最多 {READ_LIMIT_PER_SEC} 次），歇一下～",
            },
            "data": {"scope": "read", "limit": READ_LIMIT_PER_SEC},
        },
        status=429,
    )
    resp["Retry-After"] = "1"
    return resp
