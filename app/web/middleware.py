"""Astrolabe · ① Web 层：**Bearer 认证中间件**

★ 依据 `frontend-contract.md` **§7**（认证与 CSRF 精确边界）· `USERS-AND-AUTH.md` `U4.4`。

---

# ★★ 三态判定（契约 §7 原文口径，**一个都不能少**）

| # | 请求 | 行为 |
|---|---|---|
| **1** | ★ **没有** `Authorization` 头 | ★ **不动** `request.user` ⇒ 走 **session + CSRF**（⚠ 这是"管理员用 `/admin/` 登录"那条路） |
| **2** | `Authorization: Bearer <合法>` | ★ 挂 `request.user` + ★★ **置 `_dont_enforce_csrf_checks = True`（免 CSRF）** |
| **3** | 有 `Authorization` 但**无效 / 过期 / 撤销** | ★★ **401 `unauthenticated`，且【不回退 session】** |

## ★★ 第 3 条为什么必须"不回退"

⚠★ 如果无效 token 就悄悄回退到 session，会出现一种**极危险的错觉**：

> 用户以为"我登出了"（浏览器里的 token 已清），
> ⚠★ 但请求仍然带着**旧的 session cookie** ⇒ **服务端照样认得他**。

⇒ ★ 前端会把 `unauthenticated` 当作「**清 token、跳登录**」的唯一信号（契约 §1 第 27 行）
  —— ★★ 而这个信号**只有在服务端真的不回退时才有意义**。

---

# ⚠★ 中间件顺序（**错了会静默失效**）

```
SecurityMiddleware → SessionMiddleware → ★ AuthenticationMiddleware
                                          ↓  （必须晚于它：否则 request.user 会被冲掉）
                                   ★ BearerAuthMiddleware
                                          ↓  （必须早于 CSRF：否则 Bearer 请求会被 CSRF 拦掉）
                                   CsrfViewMiddleware
```

★ `AuthenticationMiddleware` 是**懒加载**的（`request.user` 是个 SimpleLazyObject）——
★ 我们在它之后赋值，**覆盖**它即可 ✅。
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse

from web import auth
from web.http import fail

#: ★ 只有 `/api/` 下的请求才做 Bearer 判定 ——
#: ⚠ `/admin/` 走的是 Django 自带的 session 认证（`U4.1`：**与 API 认证物理分开**）
API_PREFIX = "/api/"

#: ★ 无效令牌的统一文案（★ 见模块文档：**不区分**"不存在 / 过期 / 已撤销"）
UNAUTHENTICATED_MESSAGE = "登录状态已失效，请重新登录"

#: ★★ **允许"无效令牌"也能到达视图的路径**（⚠ 只有这一个，**开得很克制**）
#:
#: ⚠★ 为什么必须开：★ 契约 §12 规定 `POST /api/auth/logout/` 是**幂等**的
#:   （返回 `data:{revoked:bool}`）—— ★ 但**撤销过的令牌**在中间件这一层就被 401 了，
#:   ⇒ ⚠ 第二次登出（★ 典型场景是**响应丢了、前端重试**）会变成一个刺眼的报错。
#:
#: ★★ 为什么开它**是安全的**：★ 登出**本来就要作废令牌**，
#:   ⚠ 无论返回 401 还是 200，**都不泄露任何东西、也不产生任何副作用**。
#:   ★ 而其它接口**必须**维持"无效令牌一律 401"（那才是前端清 token 的信号）。
_IDEMPOTENT_PATHS = ("/api/auth/logout/",)


class BearerAuthMiddleware:
    """★ 见模块文档的三态判定。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        # ---- ⚠ CORS 预检（OPTIONS）**必须放行** ----
        #   ★ 否则预检会被 401 挡掉，浏览器**连正式请求都不会发** ⇒
        #     ⚠ 前端只会看到一个含义模糊的 CORS 报错，**极难排查**。
        if request.method == "OPTIONS" or not request.path.startswith(API_PREFIX):
            return self.get_response(request)

        header = request.META.get("HTTP_AUTHORIZATION", "") or ""
        if not header:
            # ---- 第 ① 态：无 Authorization ⇒ 走 session + CSRF（★ 什么都不做）----
            return self.get_response(request)

        if not header.lower().startswith("bearer "):
            # ⚠ 有 Authorization 头，但**不是 Bearer** ⇒ ★ 同样按第 ③ 态处理：
            #   ★ 不能"看不懂就忽略" —— 那会让前端以为自己的 token 生效了
            return _unauthorized()

        token = auth.verify_token(header[7:].strip())
        if token is None:
            # ---- 第 ③ 态：无效 / 过期 / 已撤销 ⇒ 401，★ 不回退 session ----
            #   ★ 例外：幂等接口（登出）放行到视图 —— ⚠ 见 `_IDEMPOTENT_PATHS` 的说明
            if any(request.path.endswith(p) for p in _IDEMPOTENT_PATHS):
                return self.get_response(request)
            return _unauthorized()

        # ---- 第 ② 态：合法 ⇒ 挂 user + 免 CSRF ----
        request.user = token.user
        # ★★ Bearer 免 CSRF 的**唯一**机制（与 `@csrf_exempt` 是同一个内部标记）
        #   ⚠★ 安全性来自"**攻击者的站点读不到 localStorage 里的 token**"，
        #      ❌ 不是来自"我们信任了这个头"
        request._dont_enforce_csrf_checks = True
        # ★ 挂上去，便于视图知道"这次是哪个令牌"（★ 登出时要撤销的就是它）
        request.api_token = token
        return self.get_response(request)


def _unauthorized() -> JsonResponse:
    """★ 401 —— ★ 用 ④ 型（带 `code`），⚠ 因为前端**必须**对 `unauthenticated` 分支。

    （★ 契约 §1：`unauthenticated`(401) ⇒ **清 token、跳登录** ——
      ⚠ 若不带 `code`，前端就**没法区分**它和别的 401 了。）
    """
    return fail(UNAUTHENTICATED_MESSAGE, 401, code="unauthenticated")
