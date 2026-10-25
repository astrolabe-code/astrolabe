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

from django.http import HttpRequest
from django.middleware.csrf import get_token

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


class DeviceTokenMiddleware:
    """★★ **设备令牌**（`B238` · 2026-10-23）⚠

    > 「网站链接建立时，就给设备发送一个token存起来。然后，它每次访问都要带上这个
    >   token，做为身份识别。这样游客也能区分了，有token或有用户名的就给正常速率。
    >   都没有的，看作一个人，走哪9倍的速率限制……他们用脚本清除token不管用。」

    ```
    没有 cookie / 验签失败 ⇒ 发新令牌并写 HttpOnly Cookie（每 IP 每小时 150 个）
    有合法令牌            ⇒ request.device_token = 它
    ```

    ⚠ 只挂一个属性，**不做任何拦截** —— 是否限流由各接口自己决定 ✅
    ⚠ 与登录认证无关：它回答「这是哪台设备」，session 回答「你是谁」⚠
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core import device

        token = request.COOKIES.get(device.COOKIE_NAME, "")
        freshing = None

        # ⚠★★ **限流身份只看"请求带来的令牌"**：
        #   · · 如果这里把"刚发的令牌"当身份 ⇒ **不带 cookie 的脚本每次都是新身份**，
        #     * 限流直接失效（实测发现）⚠
        #   · · 所以：* 带来的合法令牌 ⇒ 记身份；* 没带 ⇒ 就是 anon（共用桶）✅
        valid = device.verify(token)
        if not valid:
            # ★ 发牌前先看配额（* 每 IP 每小时 150 个，* 超了就不发）⚠
            if device._issue_allowed(device.client_ip(request)):
                freshing = device.issue()
            token = ""

        request.device_token = token if valid else ""
        response = self.get_response(request)
        if freshing:
            device.set_cookie(response, freshing)
        return response


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
