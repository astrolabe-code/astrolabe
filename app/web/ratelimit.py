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
u<id>      登录用户      10 次/秒
d<token>   设备（游客）  10 次/秒
anon       都没有        90 次/秒（全体共用 = 10 × 9）
```

⚠★ 失败**放行**：限流是保护手段，Redis 挂了不该让搜索不可用 ✅
"""
from __future__ import annotations

import logging

from django.http import JsonResponse

from search import terms

logger = logging.getLogger("astrolabe.ratelimit")


def identity(request) -> str:
    """★ 请求的身份（* 登录 > 设备 > 匿名）⚠"""
    from web.permissions import current_user

    user = current_user(request)
    if user is not None and getattr(user, "pk", None):
        return f"u{user.pk}"

    token = getattr(request, "device_token", "") or ""
    if token:
        return f"d{token.split('.')[0][:16]}"
    return "anon"


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

    _bump_hit(scope)

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


def _bump_hit(scope: str) -> None:
    """★ 记一次"被限流"（* 用来判断限流是不是误伤）⚠"""
    try:
        from django.utils import timezone

        r = terms._redis()
        key = f"astrolabe:rl:hits:{scope}:{timezone.localdate().isoformat()}"
        r.incr(key)
        r.expire(key, 172800)
    except Exception:
        pass
