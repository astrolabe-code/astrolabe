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
import re
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.http import HttpRequest, HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core import appsettings, invites, oauth
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
    intent_result = None
    st = result.state_row
    if st is not None and st.action == OAuthState.ACTION_PUBLISH:
        intent_result = _run_publish(result, st)
    elif st is not None and st.action == OAuthState.ACTION_FETCH:
        # ★★★ `B169`：**拉取代码**（★ 对**已有项目**发起）——
        #   ★★ 「归属校验 + 投递作业」**都发生在这里**（⚠ 因为此刻才有 access_token）
        intent_result = _run_fetch(result, st)

    # ⚠★ 再次校验 `next_url`（★ 防的是"state 是几分钟前存的"这个时间差）
    target = safe_next_url(result.next_url) or _spa_url()
    payload = {
        "token": raw,
        "exp": token.expires_at.isoformat(),
        "user": auth.user_json(result.user),
        "action": result.action,      # ★ `login` / `register` —— ★ 前端可据此显示欢迎语
    }
    # ★★ `B169`：**意图结果**（★ `publish` / `fetch` 通用一个键）——
    #   ⚠ 原名 `publish`，改为中性的 `intent_result`（★ 因为现在有两种意图了）
    if intent_result is not None:
        payload["intent_result"] = intent_result

    if as_json:
        return ok(payload)
    # ⚠ fragment 只能放字符串 ⇒ 意图结果**序列化成一段 JSON**
    #   （★ 前端 `JSON.parse` 即可；⚠ 不放 query 里 —— 那会进日志）
    frag = {"token": raw, "exp": payload["exp"], "action": payload["action"]}
    if intent_result is not None:
        frag["intent_result"] = json.dumps(intent_result, ensure_ascii=False)
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


def _run_fetch(result, st: OAuthState) -> dict:
    """★★★ 在回调里**真正执行「拉取代码」**（`B169`）。

    ## ★ 它做三件事（★ 顺序不能换）
    ① ★★★ **归属校验**（`verify_repo_ownership`）—— ★ 这是本条的**全部意义**：
       ★★ 「**未通过 ⇒ 服务端不代为拉取**」（`backend-design.md` 的 `[Gate 0]` 原文）⚠
    ② ★★ **留痕**（`AuditLog`）—— ★ 设计要求的那三项：
       `verify_provider` / `verify_account` / `verified_at`（⚠ **通过和拒绝都要留**）
    ③ ★ **投递作业** —— ★ 「拉取 + 解析」是**同一个作业**的连贯两步 ✅
       （★ 正是所有者说的「**拉了就解析**」，★ 所以这里**不拆成两个动作**）

    ## ⚠★ 一个必须守住的纪律
    ★ **本函数【必须吞掉业务失败】**（★ 与 `_run_publish` 完全相同的原因）——
      ⚠ 因为用户**已经登录成功了**；★ 让"拉取失败"把**整个登录**搞挂，是最糟的耦合 ⚠
      ⇒ ★ 业务失败一律**用返回值表达**（❌ 不抛）✅

    ## ★★ 与视图的纵深关系
    ★ `waiting`：`start_fetch()`（`views/projects.py`）在**发起前**已经查过一遍
      （★ 权限 · 定版闸门 · `repo_url` · `provider` · 身份绑定）——
      ⚠★ 但那不能替代这里：★ **state 是几分钟前建的**，★ 中间项目可能被改/被删/已定版 ⚠
      ⇒ ★★ **两处都查**（★ 与 `safe_next_url` 在 `start` 与 `callback` 两处都校验同一道理）✅
    """
    from core import oauth as oauth_core
    from core.models import OAuthIdentity, Project
    from jobs import dispatch
    # ⚠★ `Job` 在 `jobs.models`，❌ **不在 `core.models`** ——
    #   ★ 这类错**编译检查抓不到**（import 在函数体内），⚠ 只有运行到才会炸
    from jobs.models import Job

    ref = (st.project_ref or "").strip()
    repo = (st.repo or "").strip()
    intent = st.intent or {}

    # ---- ① 项目必须还在、且**属于他**（★ 越权与"不存在"不可区分 —— 统一 404 口径）----
    project = Project.objects.filter(project_ref=ref, owner=result.user).first()
    if project is None:
        return {"ok": False, "reason_code": "not_found", "message": "项目不存在或不属于你。"}

    # ---- ② 定版闸门（★ 与视图**同一口径** —— 纵深防御）----
    if project.is_graph_built:
        return {
            "ok": False,
            "reason_code": "graph_immutable",
            "message": "这个项目已经拉取并解析过了，图不会重新生成。",
        }

    # ---- ③ ★★★ 归属校验（★ 唯一的目的）----
    #   ★ `result.identity` 在登录成功那一刻就已带上 ⇒ ★ 优先用它（少一次查询）；
    #   ⚠★ **兜底**：万一上游没填，也要能查出来 —— ★ 否则会拿空 ID 去过校验，
    #     ⚠ 那会导致**"明明是他的库也被拒"**（★ 一种最难排查的误拒）⚠
    ident = result.identity or OAuthIdentity.objects.filter(
        user=result.user, provider=result.provider
    ).first()
    own = oauth_core.verify_repo_ownership(
        result.provider,
        result.access_token,          # ⚠ 用完即弃，❌ **不落库**（`B148`）
        repo_full_name=repo,
        provider_user_id=ident.provider_user_id if ident is not None else "",
    )

    # ---- ④ ★★ 留痕（★ `[Gate 0]` 明确要求；⚠ **通过和拒绝都要记**）----
    #   ★ 走公共函数 —— ⚠ 不要在这里再写一遍（★ `publish_project` 也要用同一份逻辑）
    oauth_core.record_ownership_audit(
        user=result.user,
        provider=result.provider,
        repo_full_name=repo,
        verdict=own,
        project_ref=project.project_ref,
        verify_account=getattr(ident, "login", "") if ident is not None else "",
    )

    if not own.ok:
        return {"ok": False, "reason_code": own.reason_code, "message": own.message}

    # ---- ⑤ 投递作业（★ 拉取 + 解析：**同一个作业的两步，不可拆**）----
    payload: dict = {
        "project_id": project.pk,
        "provider": project.provider,
        "repo_full_name": repo,
        "repo_url": project.repo_url,
        "commit": project.commit,
    }
    # ⚠★ `source_path` 只对 staff 生效（★ 在 `start_fetch()` 里已按身份过滤过）
    source_path = str(intent.get("source_path") or "")
    if source_path:
        payload["path"] = source_path

    job, created = dispatch.submit(
        kind=Job.KIND_PARSE,
        project_ref=project.project_ref,
        payload=payload,
        # ★ 幂等：同一项目 + 同一 commit ⇒ 复用已有作业（⚠ 与 `B115 ④` 同一口径）
        dedup_key=f"fetch:{project.project_ref}:{project.commit or 'head'}",
    )
    return {
        "ok": True,
        "reason_code": "",
        "message": "已开始拉取代码并解析。",
        "project_ref": project.project_ref,
        "job_id": job.pk,
        "created": created,
    }


def _failure(message: str, *, as_json: bool) -> JsonResponse | HttpResponseRedirect:
    if as_json:
        return fail(message, 401, code="oauth_failed")
    return _redirect_with_fragment(_spa_url(), error=message)


# ===========================================================================
# /api/auth/login/ · /api/auth/register/     ★ 用户名 + 密码（`B170` · `U4.9`）
# ===========================================================================

#: ★ 用户名规则（`B170`）：★ 3–30 位，★ 允许中英文 / 数字 / 下划线 / 连字符 / 点
#: ⚠★ `\w` 在 Python `re` 里默认就是 `UNICODE` ⇒ ★ **中文自动可用**
#: （★ 本项目是中文项目，★ 强制英文用户名没必要 —— ★ 一期）
_USERNAME_RE = re.compile(r"^[\w.\-]{3,30}$", re.UNICODE)


def _login_allowed() -> bool:
    """★ `login_open` 门禁（`U4.6`）。

    ⚠★ 语义（`U4.6` 原文）：★ **只拦【新登录】，❌ 不影响已有 token** ——
      ★ 若它把已登录的人也踢出去，那它就是 `paused`（⚠ **别把这两个开关混成一个**）。
    """
    return bool(appsettings.get("login_open"))


def _password_problem(password: str) -> str:
    """★ 密码强度的**最低**校验（`B170` 一期）—— ★ 返回问题描述，空串 = 通过。

    ⚠★ 刻意**只做最低** —— ★ `U4.2` 列的那一整套（撞库 / 锁定 / 验证码 / 重置邮件）
      ★ 是**待办**；★ 而这里必须挡住的只有一件事：
      ⚠★ **"123456" 这种一秒被猜到的密码** ⚠
    """
    if len(password) < 8:
        return "密码至少 8 位。"
    if len(password) > 128:
        return "密码太长了（最多 128 位）。"
    if password.isdigit() or password.isalpha():
        return "密码不能是纯数字或纯字母。"
    return ""


@csrf_exempt
@require_http_methods(["POST"])
def register(request: HttpRequest) -> JsonResponse:
    """★★★ **注册**（`B170`）—— ★ 用户名 + 密码 +（可能）邀请码。

    ## ★★ 门禁**只问一处**
    ★ `invites.registration_gate()` —— ★ `U4.8` 的纪律：★ 判断**收敛到一处** ⚠
    （★ 不要在这里再写一遍开关判断 —— ★ 两处写一遍，**早晚有一处会漏**）

    ## ★ 两种情形（★ 由 `registration_open` 决定，⚠ 语义见 `B170`）
    · ★ `True`  ⇒ 入口**可见** · ★ 按 `invite_required` 决定要不要码
    · ★★ `False` ⇒ 入口**隐藏**（★ 只有拿到邀请链接的人才看得到这个页面）
      ⇒ ★★ **强制要码**（★ `gate.invite_required` 恒为 `True`）

    ## ⚠★ 一期范围
    ★ 只做「能注册」：★ **邮箱验证 / 验证码 / 撞库防护** ⇒ **待办** ⚠
    """
    gate = invites.registration_gate()
    if gate.paused:
        return fail(gate.message or "站点正在维护", 503, code="paused")
    if not gate.allowed:
        return fail(gate.message or "本站当前未开放注册。", 403, code="registration_closed")

    body = read_json(request)
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    invite_token = str(body.get("invite_token") or "").strip()

    if not username or not password:
        return fail("请填写用户名和密码", 400, code="missing_fields")

    if not _USERNAME_RE.match(username):
        return fail(
            "用户名需 3–30 位，只能用中英文、数字、下划线、连字符和点。",
            400,
            code="bad_username",
        )

    problem = _password_problem(password)
    if problem:
        return fail(problem, 400, code="weak_password")

    User = get_user_model()
    if User.objects.filter(username__iexact=username).exists():
        # ⚠★ **注册时必须说清"这个名字被占了"** —— ★ 这与登录**刻意不同**：
        #   · 登录要含糊（★ 防账号枚举，见 `login()`）⚠
        #   · ★ 而注册**躲不掉** —— ★ 不说的话，用户只会**反复试同一个名字** ⚠
        return fail("这个用户名已经被占用了，换一个吧。", 409, code="username_taken")

    # ★ 需要码时**先预检**（⚠ 不消耗）—— ★ 同 `U4.8`：「★ 校验通过前不消耗」
    if gate.invite_required:
        c = invites.check(invite_token)
        if not c.ok:
            return fail(c.message or "邀请凭证无效。", 400, code="bad_invite")

    # ★★★ 建号 + 核销 **必须同一事务**（`U4.7` 纪律 2：★ 核销与建号**同生共死**）——
    #   ⚠★ 否则会出现「**码被消耗了、账号却没建成**」⇒ ★ 用户**白白损失一个邀请码**且**无法自证** ⚠
    with transaction.atomic():
        user = User.objects.create_user(username=username, password=password)
        if invite_token:
            r = invites.redeem(invite_token, user)
            if not r.ok:
                # ★★ 主动回滚 ⇒ **不留"号建了、码没用上"的孤儿账号**
                transaction.set_rollback(True)
                return fail(r.message or "邀请凭证无效。", 400, code="invite_failed")

    raw, token = auth.issue_token(
        user,
        provider="password",
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:200],
        remember=True,
    )
    return ok(
        {
            "token": raw,
            "exp": token.expires_at.isoformat(),
            "user": auth.user_json(user),
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(["POST"])
def login(request: HttpRequest) -> JsonResponse:
    """★★★ **用户名 + 密码 登录**（`B170` · `U4.9`）。

    ★ 契约 §12 定好了形状：★ `POST /api/auth/login/` ⇒ `data:{token, user, exp}`，
    ★★ 且**显式 `csrf_exempt`** —— ★ 因为此刻**还没有 token**，★ Bearer 那条路走不到 ⚠

    ## ⚠★★ 一条安全底线（★ 一期就必须有）
    ★ **「用户名不存在」与「密码错误」返回【同一句话 + 同一个状态码 + 同一个 code】** ——
      ★ 否则等于**免费告诉攻击者"哪些用户名存在"**（★ 那正是 `U4.2` 第 3 条说的难题）⚠
    ★★ 注意：★ 只在**文案**上含糊是不够的，⚠ **code 也必须一样** ⚠

    ## ⚠★ 一期范围
    ★ 只做"能登进来"：★ **失败计数 / 锁定 / 验证码 / 防撞库** ⇒ **待办** ⚠
      ★ 一期唯一的前置补偿：★ `login_open` 开关（★ 出事时能一键停掉新登录）
    """
    if not _login_allowed():
        return fail("本站当前未开放登录，请稍后再试。", 503, code="login_closed")

    body = read_json(request)
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not username or not password:
        return fail("请填写用户名和密码", 400, code="missing_fields")

    user = authenticate(request, username=username, password=password)
    if user is None:
        # ⚠★ 刻意**不区分**"没这个人"与"密码错了" —— ★ 见函数文档
        #
        # ⚠★★ **被停用的账号也会落到这里** ——
        #   ★ Django 的 `ModelBackend.authenticate()` 内部会调 `user_can_authenticate()`
        #     （★ 它检查 `is_active`）⇒ ★★ **停用的用户直接返回 `None`** ⚠
        #   ⇒ ★ 所以下面那个 `is_active` 分支**目前走不到**
        #     （★ 保留它是因为"换 backend 就变了"，⚠ 不是死代码洁癖）
        #
        #   ⚠ 取舍（★ 如实记下）：★ **不让"账号已停用"成为一句可用的提示** ——
        #     ★ 因为它会**确认"这个用户名存在"**（★ 那就是**免费的用户名枚举信号**）⚠
        #   ★★ 代价：★ 被停用的用户**只会看到"用户名或密码不正确"**，⚠ 他会反复试 ——
        #     ★ 这是**一期明确接受的代价**（★ 待办：将来可考虑"只对管理员显示停用原因"）
        return fail("用户名或密码不正确。", 401, code="bad_credentials")
    if not user.is_active:
        # ⚠ 见上：★ 当前 `ModelBackend` 走不到这里（★ 留着是为了不依赖某个 backend 的实现细节）
        return fail("这个账号已被停用。", 403, code="account_disabled")

    raw, token = auth.issue_token(
        user,
        provider="password",
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:200],
        remember=bool(body.get("remember", True)),
    )
    return ok(
        {
            "token": raw,
            "exp": token.expires_at.isoformat(),
            "user": auth.user_json(user),
        }
    )


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
