"""Astrolabe · ① Web 层：**认证相关中间件**

★★ 2026-10-25（B245）：**Bearer 令牌中间件已删除** —— 公网改用 Django 自带 session。

> 所有者原话（逐字）：
> 「**我的天呐，你把django设计好的维持登陆状态和身份识别的令牌系统给了后台了吗？
>   你自己整个可能有漏洞的令牌系统给放到公网的网站？**」

⇒ 认证交回 `AuthenticationMiddleware`（Django 自带），本模块只剩三件与认证**相关**的事：

| # | 中间件 | 作用 |
|---|---|---|
| ① | `CsrfCookieMiddleware` | ★★ **B247②**：GET 时种下 `csrftoken` Cookie，否则前端第一个请求就拿不到它 |
| ② | `DeviceTokenMiddleware` | 设备令牌（`B238`）—— 限流身份，**与登录认证无关** |
| ③ | `SearchRateLimitMiddleware` | 搜索限流（`B238`） |

---

# ⚠★ CSRF 三件套（B247②，一个都不能少）

```
① 本中间件：GET 时 get_token() ⇒ 种 csrftoken Cookie（必须非 HttpOnly，前端才读得到）
② 登录接口：⛔ 不许 csrf_exempt —— 否则等于"替攻击者登录受害者"
③ 前端：所有非 GET 带 X-CSRFToken 头（见 frontend/src/api/client.ts）
```

⚠ 换成 cookie 认证后，请求**会自动携带凭证** ⇒ CSRF 从「可选」变成「必须」⚠
"""

from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token

logger = logging.getLogger("astrolabe.protect")

#: ★ 只有「安全方法」才种 CSRF Cookie ——
#: ⚠ POST 上种它没有意义（那一刻请求已经带着自己的 token 了）
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CsrfCookieMiddleware:
    """★★ **保证 `csrftoken` Cookie 一定存在**（B247②）⚠

    ```\n    前端登录前要先发一次 GET（* 拉站点配置 / Providers）⇒ 那时就要能读到 csrftoken\n    否则第一个 POST /api/auth/login/ 必 403（* 表现为"登录永远失败"，极难排查）⚠\n    ```\n
    ★ 做法：安全方法上调 `get_token(request)` —— ★ 它只往 `request.META` 里放一个值，
      **不查库、不写库**；★ 真正的种 Cookie 由 `CsrfViewMiddleware.process_response` 完成 ✅
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        if request.method in _SAFE_METHODS:
            # ⚠ 幂等且极轻：已有 Cookie 时直接返回原值 ⚠
            get_token(request)
        return self.get_response(request)



class BanCheckMiddleware:
    """★★ **IP 封禁拦截**（2026-11-04 从 `DeviceTokenMiddleware` 里拆出来）⚠

    ## 为什么现在单独一个类

    ```
    原来这段判定写在 DeviceTokenMiddleware 里（顺手做的）
    2026-11-04 删设备令牌时把它一起删了 ⇒ **后台封禁名单直接失效**
    （冒烟脚本「被封 IP ⇒ 403」当场抓到，这不是猜测）
    ⇒ 封禁是**独立职责**，不该依附在"发令牌"上
    ```

    ⚠ 回环与容器网段由 `access_audit.is_banned` 内部直接放行（防自锁）。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core import access_audit, device

        if access_audit.is_banned(device.client_ip(request)):
            logger.warning("ban 拦截 ip=%s", device.client_ip(request))
            return HttpResponse(
                "Access denied.", status=403, content_type="text/plain; charset=utf-8"
            )
        return self.get_response(request)


class SearchRateLimitMiddleware:
    """★★ **搜索类请求的统一限流**（`B238`）⚠

    > 「直接在任何可以搜索的窗口前，加一个后端验证是不是被限流了，没限流，才去真正
    >   触发搜索。」

    ```
    GET /api/** 且 ?q= 非空  ⇒ 判一次（* 笔记搜索 / 联想 / 项目搜索 全部覆盖）✅
    ```

    ⚠ 必须排在 `DeviceTokenMiddleware` **之后**（* 要用它的设备身份）⚠
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from web import ratelimit

        blocked = ratelimit.check(request)
        if blocked is not None:
            return blocked
        return self.get_response(request)


class ReadRateLimitMiddleware:
    """★★ **登录用户的读接口限流**（P2b-1 · 2026-11-04）⚠

    依据 RATE-LIMIT.md 5.1：

    ```
    GET /api/** 且**不带 q**（列表 / 详情）   登录用户 30 次/秒
    GET /api/** 且**带 q**（搜索）            登录用户 10 次/秒  ← 由 SearchRateLimitMiddleware 管
    ```

    ⚠★ **本阶段只收紧登录用户**（P2b-1）：
      匿名的额度调整（5 次/秒、按 IP 分桶）必须等 P4 —— 在那之前 `a<ip>` 就是网关，
      收紧它会变成"全站匿名合计 5 次/秒"，高峰期会被自己打满（N1）。
      ⇒ 匿名在本阶段：普通读**不新增限流**、搜索**维持现状**。
    ⚠ 必须排在 `SearchRateLimitMiddleware` 之后，且自己不处理带 q 的请求。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from web import ratelimit

        blocked = ratelimit.check_read(request)
        if blocked is not None:
            return blocked
        return self.get_response(request)


class WriteRateLimitMiddleware:
    """★★ **写操作限流**（P2a · 2026-11-04）⚠

    依据 RATE-LIMIT.md 5.2：

    ```
    发布 / 删除 / 修改（POST/PUT/PATCH/DELETE /api/**）  30 次/分钟（按用户）
    导出（POST /api/me/deleted/export/）                  2 次/分钟
    ```

    ⚠ **只按用户计账**（`u<id>`）：写操作本来就要登录，与真实 IP 无关
      ⇒ 所以这一条**不需要等隧道**（P4 之前就能上）。
    ⚠ 匿名写请求不在这里判：它们会在视图层被 401/403 挡住。
    ⚠ 与 `SearchRateLimitMiddleware` 不重叠：那个只管带 `q` 的 GET。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from web import ratelimit

        blocked = ratelimit.check_write(request)
        if blocked is not None:
            return blocked
        return self.get_response(request)


class ProtectModeMiddleware:
    """★★ **站点保护模式**（保命开关 · 2026-11-04）⚠

    ## 所有者原话（逐字）

    > 「打开了，admin 也要能登陆呀，否则我怎么解除这个呢？
    >   admin 是用 ssh 连接登陆的，放宽也没影响，先要破除我的 ubuntu 密码再说。」

    ## 开启后

    ```
    已登录 + is_staff      ⇒ 一切正常（admin 必须能进来解除开关）
    未登录                 ⇒ 只能**只读浏览**；搜索 / 登录 / 写操作 一律 503
    已登录但非 staff        ⇒ 同上（他们不是管理员，没有理由豁免）
    健康检查                ⇒ 放行（否则监控会报"站点挂了"，掩盖真实情况）
    ```

    ⚠ **为什么放行 /api/auth/login/**：admin 需要能登录才能解除；
      真正的判定在 `web/views/auth.py::login()` —— 非 staff 登录会被拒（503 `protect_mode`）。
    ⚠ **必须排在 `AuthenticationMiddleware` 之后**（要用 `request.user`）。
    """

    #: 这些前缀始终放行（健康检查 + 登录入口 + 身份查询）
    ALWAYS = ("/healthz", "/readyz", "/api/auth/login/", "/api/auth/me/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core import maintenance

        if not maintenance.is_on():
            return self.get_response(request)

        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False) and user.is_staff:
            return self.get_response(request)

        path = request.path or "/"
        if any(path.startswith(prefix) for prefix in self.ALWAYS):
            return self.get_response(request)

        # ★ 只读浏览放行：无 q 的 GET / HEAD（⚠ 带 q = 搜索，最贵的那个入口）
        if request.method in ("GET", "HEAD") and not (request.GET.get("q") or "").strip():
            return self.get_response(request)

        logger.warning(
            "protect_mode 拦截 %s %s ip=%s",
            request.method,
            path,
            request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", ""),
        )
        message = "站点正在保护中：已登录用户不受影响，其他人现在只能浏览。"
        if path.startswith("/api/"):
            return JsonResponse(
                {"ok": False, "error": {"code": "protect_mode", "message": message}},
                status=503,
            )
        return HttpResponse(message, status=503, content_type="text/plain; charset=utf-8")
