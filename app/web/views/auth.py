"""Astrolabe · ① Web 层：**认证端点**（OAuth + 令牌）

★ 依据 `USERS-AND-AUTH.md` `U4`（★ **没有用户名密码登录**）· `U4.7`（邀请）·
`U4.8`（OAuth 首次登录 = 注册）· `frontend-contract.md` §12。

---

# ★ 端点一览

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/auth/providers/` | ★ 有哪些登录方式可用 + **注册门禁状态** |
| `POST` | `/api/auth/<provider>/start/` | 发起授权 ⇒ `{authorize_url, state}` |
| `GET` | `/api/auth/<provider>/callback/` | ★★ 回调（★ 浏览器直接跳进来） |
| `GET` | `/api/auth/me/` | 当前用户（需 Bearer） |
| `POST` | `/api/auth/logout/` | 登出（撤销**这一个**令牌） |
| `POST` | `/api/auth/logout-all/` | ★ **登出全部设备**（怀疑泄露时的止血） |
| `GET` | `/api/auth/tokens/` | ★ 「登录设备」列表（⚠ 绝不含明文） |

---

# ⚠★ 一个必须防住的洞：**open redirect ⇒ token 泄露**

⚠★★ `next_url` 是**用户可控**的。如果我们原样拿去重定向，
攻击者只要构造：

```
/api/auth/github/start/?next_url=https://evil.com
```

★ 回调后我们就会把 **`#token=...` 的 fragment 重定向到 evil.com**
⇒ ★★★ **token 直接落到攻击者手里**。

⇒ ★★ 所以 `safe_next_url()` **只放行两种**：**站内相对路径** 与 **白名单内的 origin**
（★ 且在 `start` 与 `callback` **两处都校验** —— 防的是"state 是几分钟前存的"这个时间差）。
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_http_methods

from core import invites, oauth
from core.models import OAuthState
from web import auth
from web.http import fail, ok, read_json, safe_next_url

# ===========================================================================
# ★★ `next_url` 白名单 —— ⚠ 已移到 `web/http.py`
#
# ★ 原因：**发布端点也要用它**，而本模块又要调发布逻辑
#   ⇒ ⚠ 留在 view 层会形成**循环 import**（`auth` ↔ `publish`）。
# ===========================================================================


def _redirect_with_fragment(target: str, **params) -> HttpResponseRedirect:
    """★ 把参数放进 **URL fragment** 再重定向。

    ⚠★ 为什么用 `#`（fragment）而不是 `?`（query）：

    | | 会进服务端日志吗 |
    |---|---|
    | `?token=xxx` | ★ **会** —— ⚠ nginx / 代理 / 浏览器历史**全都记下来** |
    | ★ `#token=xxx` | ★ **不会** —— ★ 浏览器**根本不把 fragment 发给服务端** |

    ⇒ ★★ 对 token 这种一次性机密，**必须放 fragment**。
    """
    frag = urlencode(params)
    if not frag:
        return HttpResponseRedirect(target)
    sep = "&" if "#" in target else "#"
    return HttpResponseRedirect(f"{target}{sep}{frag}")


def _base_url() -> str:
    """★ 回调地址的基址。

    ⚠★ **刻意用配置值，而不是 `request.build_absolute_uri()`** ——
      后者依赖 `Host` 头，⚠ 一旦前面有代理 / 配置疏漏，**攻击者能改它** ⇒
      ★ 而回调地址在「授权」与「换 token」两处**必须完全一致**，否则第三方会拒绝。
      ★ 用固定配置值 ⇒ **确定、可预测、与 OAuth App 里填的一致**。
    """
    return getattr(settings, "ASTROLABE_BASE_URL", "http://localhost:8000").rstrip("/")


def _spa_url() -> str:
    return getattr(settings, "ASTROLABE_SPA_URL", "/")


# ===========================================================================
# /api/auth/providers/
# ===========================================================================


@require_http_methods(["GET"])
def providers(request: HttpRequest) -> JsonResponse:
    """★ 登录页要什么，这里就给什么。

    ★★ 为什么要暴露**注册门禁**：★ 前端要能在**点登录之前**就告诉用户
      「本站当前**仅限邀请注册**」—— ⚠ 否则用户一路授权到 GitHub 回来才被拒，
      ★ 那是**最糟的一种体验**（他还以为是自己操作错了）。
    """
    gate = invites.registration_gate()
    return ok({"providers": oauth.enabled_providers(), "registration": gate.to_dict()})


# ===========================================================================
# /api/auth/<provider>/start/
# ===========================================================================


@require_http_methods(["POST"])
def start(request: HttpRequest, provider: str) -> JsonResponse:
    """★ 发起授权 —— 建一个一次性 `state`，返回授权 URL。

    ⚠★ **不在这里强制邀请码** —— ★ 因为此刻我们还**不知道他有没有账号**
      （`U4.8` 流程第 ② 步是"若没有账号才要"，而判断发生在**回调**时）。
      ★ 所以邀请码只是**带过去**，★ 由 `oauth.callback()` 在确定要走注册时才校验与核销。
    """
    gate = invites.registration_gate()
    if gate.paused:
        # ⚠ `paused` 优先级最高（`U4.6`）—— 整站停服时连授权都不该发起
        return fail(gate.message or "站点正在维护", 503, code="paused")

    body = read_json(request)
    next_url = safe_next_url(str(body.get("next_url") or ""))
    if next_url is None:
        # ★★ 见模块文档：**放行它 = 把 token 送给攻击者**
        return fail("next_url 不在允许的域名白名单内", 400, code="bad_next_url")

    try:
        st = oauth.start(
            provider,
            invite_token=str(body.get("invite_token") or "").strip(),
            next_url=next_url,
            # ★ 「记住我」（契约 §12：7 / 30 天两档）—— ⚠ 必须存进 state，
            #   因为回调时用户已经不在我们页面上了
            remember=bool(body.get("remember", True)),
            base_url=_base_url(),
        )
    except oauth.OAuthError as exc:
        return fail(str(exc), 400, code="provider_unavailable")

    return ok({"authorize_url": st.url, "state": st.state.state})


# ===========================================================================
# /api/auth/<provider>/callback/
# ===========================================================================


@require_http_methods(["GET"])
def callback(request: HttpRequest, provider: str) -> JsonResponse | HttpResponseRedirect:
    """★★ **OAuth 回调** —— ★ 浏览器**直接跳进来**（所以是 `GET`）。

    ★ 两种出口：

    | 场景 | 出口 |
    |---|---|
    | ★ **浏览器跳转**（默认） | ★ `302` 到 `next_url`，参数放 **fragment** |
    | ★ **脚本 / 冒烟测试**（`?format=json`） | ★ JSON（★ 否则测试没法断言） |

    ⚠★ 失败时我们**可能不知道 `next_url`**（state 无效 / 已消费）⇒ ★ 退回 SPA 首页，
      并把 `error` 放进 fragment 让前端展示。
    """
    as_json = request.GET.get("format") == "json"
    code = (request.GET.get("code") or "").strip()
    state = (request.GET.get("state") or "").strip()

    if not code:
        # ★ 用户在授权页点了「取消」—— ⚠ 这不是错误，是**正常选择**
        return _failure("已取消授权", as_json=as_json)

    result = oauth.callback(provider, code=code, state=state, base_url=_base_url())
    if not result.ok or result.user is None:
        return _failure(result.message or "登录失败，请重试。", as_json=as_json)

    # ★★ 签发本站令牌（★ 明文只在这里出现一次）
    raw, token = auth.issue_token(
        result.user,
        provider=result.provider,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:200],
        remember=result.remember,
    )

    # ---- ★★★ 发布意图：★ **只能在【这一刻】做** ----
    #   ⚠★ 因为本平台**不保存 `access_token`**（`B148`）——
    #      ★ `result.access_token` 是**唯一一次**能拿它去校验归属的机会，
    #      ★ 用完即弃（⚠ 绝不落库）。
    publish_payload = None
    st = result.state_row
    if st is not None and st.action == OAuthState.ACTION_PUBLISH:
        publish_payload = _run_publish(result, st)

    # ⚠★ 再次校验 `next_url`（★ 防的是"state 是几分钟前存的"这个时间差）
    target = safe_next_url(result.next_url) or _spa_url()
    payload = {
        "token": raw,
        "exp": token.expires_at.isoformat(),
        "user": auth.user_json(result.user),
        "action": result.action,      # ★ `login` / `register` —— ★ 前端可据此显示欢迎语
    }
    if publish_payload is not None:
        payload["publish"] = publish_payload

    if as_json:
        return ok(payload)
    # ⚠ fragment 只能放字符串 ⇒ 发布结果**序列化成一段 JSON**
    #   （★ 前端 `JSON.parse` 即可；⚠ 不放 query 里 —— 那会进日志）
    frag = {"token": raw, "exp": payload["exp"], "action": payload["action"]}
    if publish_payload is not None:
        frag["publish"] = json.dumps(publish_payload, ensure_ascii=False)
    return _redirect_with_fragment(target, **frag)


def _run_publish(result, st: OAuthState) -> dict:
    """★★ 在回调里**真正执行发布**（★ 见 `web/views/publish.py` 模块文档）。

    ⚠★ 这一段**必须吞掉业务失败**（❌ 不抛）—— ★ 因为用户**已经登录成功了**，
      ⚠ 让"发布失败"把整个登录也搞挂，是**最糟的耦合**。
      ⇒ ★ 发布失败就**如实返回失败原因**，让前端在发布页展示。
    """
    from core import publish as publish_core

    intent = st.intent or {}
    try:
        pub = publish_core.publish_project(
            result.user,
            provider=result.provider,
            access_token=result.access_token,     # ⚠ 用完即弃，❌ 不落库
            repo_full_name=st.repo,
            name=intent.get("name", ""),
            desc=intent.get("desc", ""),
            source_path=intent.get("source_path", ""),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason_code": "internal", "message": f"发布失败：{exc}"[:400]}

    return {
        "ok": pub.ok,
        "reason_code": pub.reason_code,
        "message": pub.message,
        "project_ref": pub.project_ref,
        "job_id": pub.job.pk if pub.job is not None else None,
        "steps": pub.steps,
    }


def _failure(message: str, *, as_json: bool) -> JsonResponse | HttpResponseRedirect:
    if as_json:
        return fail(message, 401, code="oauth_failed")
    return _redirect_with_fragment(_spa_url(), error=message)


# ===========================================================================
# /api/auth/me/ · logout · logout-all · tokens
# ===========================================================================


def _current_user(request: HttpRequest):
    user = getattr(request, "user", None)
    return user if (user is not None and user.is_authenticated) else None


@require_http_methods(["GET"])
def me(request: HttpRequest) -> JsonResponse:
    """★ 当前用户（★ SPA 启动时调它校验 localStorage 里的 token 还有没有效）。"""
    user = _current_user(request)
    if user is None:
        # ⚠★ 注意：无效 Bearer 已经被**中间件**拦成 401 了，
        #   能走到这里说明是「**根本没有登录**」（没 Bearer、也没有 session）
        return fail("未登录", 401, code="unauthenticated")

    token = getattr(request, "api_token", None)
    return ok(
        {
            "user": auth.user_json(user),
            "exp": token.expires_at.isoformat() if token is not None else None,
        }
    )


@require_http_methods(["POST"])
def logout(request: HttpRequest) -> JsonResponse:
    """★ 登出 —— 撤销**当前这一个**令牌。

    ★ **幂等**（契约 §12：`data:{revoked:bool}`）——
      ⚠ 重复登出**不算错**：⚠ 否则"网络抖动后自动重试"会得到一个刺眼的报错。
    """
    token = getattr(request, "api_token", None)
    if token is None:
        # ⚠ 用 session 登录的人（管理员）也会走到这里 —— ★ 那就只清 session
        try:
            from django.contrib.auth import logout as dj_logout

            dj_logout(request)
            return ok({"revoked": False, "session": True})
        except Exception:  # noqa: BLE001
            return ok({"revoked": False})
    return ok({"revoked": auth.revoke_token(token)})


@require_http_methods(["POST"])
def logout_all(request: HttpRequest) -> JsonResponse:
    """★★ **登出全部设备** —— ★ 怀疑令牌泄露时的**止血手段**。

    ⚠★ 注意它会把**当前这个**也撤掉 —— ★ 这是**对的**：
      ★ "我在所有地方登出"本来就包含"这里"（⚠ 否则用户会以为没生效）。
    """
    user = _current_user(request)
    if user is None:
        return fail("未登录", 401, code="unauthenticated")
    return ok({"revoked": auth.revoke_all(user)})


@require_http_methods(["GET"])
def tokens(request: HttpRequest) -> JsonResponse:
    """★ 「登录设备」列表（⚠ **绝不含明文** —— 只有前缀与时间）。"""
    user = _current_user(request)
    if user is None:
        return fail("未登录", 401, code="unauthenticated")
    return ok({"tokens": [auth.token_json(t) for t in auth.active_tokens(user)[:50]]})
