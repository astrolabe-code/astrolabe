"""Astrolabe · 共享内核：**OAuth**（`U4` · `U4.8` · `U3.1`）

> **用户原话（`B141`）**：「本站要有**登陆功能**，也就是在本站要**有账号**，**就像 B 站一样**。」
> ★ 但 ★ **「有账号」说的是【身份】，「怎么登录」说的是【凭证】**（`U4.5`）。

---

# ★★★ 本模块最不能写错的一处：`U4.8` 那个洞

> ⚠★ **如果只给"注册页"加邀请码，而"从 GitHub 登录"这条路径不加** ——
> ★★ **任何人都能靠"用 GitHub 登录一次"绕过邀请制。**

## ★ 正确流程（`U4.8`）

```
① 访问登录页
        ↓
② 若【没有账号】⇒ ★ 必须先填【邀请码 / 走邀请链接】
        ↓   （★ 校验：有效 · 未过期 · 未用尽）      ← 只校验，❌ 不消耗
③ 把意图存进 state，跳转 GitHub / Gitee 授权
        ↓
④ OAuth 回调
        ↓
⑤ ★ 判断：这个 provider 身份【绑定过账号】吗？
        ├── ✅ 绑定过 ⇒ ★ 【登录】（★ 只查 login_open）
        └── ❌ 没绑定 ⇒ ★★ 【注册】（★ 必须查 registration_open + 邀请码）
                          ⇒ 建账号 + 绑定身份 + ★ 记 invited_by + ★ 核销邀请码
```

★ **两个入口，一个校验点**：

> ★★ **「首次建立账号」这一步，必须过邀请校验。**

★ 所以本模块**只调用 `invites.registration_gate()` 这一个函数** ——
❌ 绝不在这里再写一遍 `if registration_open ...`（⚠ **两处写一遍，早晚有一处会漏**）。

---

# ★★ 本平台**不长期保存 `access_token`**（有意）

★ 依据 `U3.3`：★ **只申请 `read:user`，❌ 不碰私有仓库**；
★ 而归属校验用的是 `GET /repos/{owner}/{repo}` —— ★ **公开信息**。

⇒ ★★ 所以 `callback()` 会把 `access_token` **放在返回值里**，
  ★ 由调用方（发布流程）**当场拿去校验归属，用完即弃** —— ❌ **绝不落库**。

★ 代价如实说明：★ 每次发布**都要重新授权一次**（⚠ 体验有损），
★★ 换来的是 **「token 泄露」这一类事故彻底不存在** ——
★ 与 `U4.2` 理由 4「**少一套凭据要保护**」同一个精神。

---

# ★★ `U4.8` 三条纪律（实现里逐条落实）

| # | 纪律 | 落在哪 |
|---|---|---|
| **1** | ★ **邀请码在校验通过前不消耗** | ★ 第 ② 步只 `check()`；★ 真正 `redeem()` 在**建号事务内**（第 ⑤ 步） |
| **2** | ★★ **核销必须与「建账号」在同一个事务里** | ★ 见 `_register()`：核销失败 ⇒ **`raise` 回滚建号** |
| **3** | ★★ **`registration_open=false` 时 OAuth 新用户一律拒绝**，★ 且给**可读原因** | ★ `registration_gate().message` 原样返回给用户 |
"""

from __future__ import annotations

import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import appsettings, invites
from core.models import AuditLog, OAuthIdentity, OAuthState

# ===========================================================================
# Provider 定义
# ===========================================================================


@dataclass(frozen=True)
class Provider:
    """★ 一个第三方 provider 的端点与字段差异（★ 新增 provider 只加一条）。"""

    key: str
    label: str
    authorize_url: str
    token_url: str
    profile_url: str
    #: ★★ 查仓库的地址模板（⚠★ **各 provider 路径不同** ——
    #:   GitHub 是 `/repos/{full}`，而 Gitee 是 `/api/v5/repos/{full}`；
    #:   ⚠ 用"从 profile 地址推导 host"的写法会拼错，**必须显式写**）
    repo_url_template: str
    #: ★★ **最小权限**（`U3.3`）—— ⚠ 绝不申请读私有仓库
    scope: str
    login_field: str
    avatar_field: str
    #: ★ 不同的 provider 把数字 ID 放在不同字段（★ 都要试，取第一个有值的）
    id_fields: tuple[str, ...]
    user_agent: str = "astrolabe"

    @property
    def id_field(self) -> str:
        return self.id_fields[0]


PROVIDERS: dict[str, Provider] = {
    "github": Provider(
        key="github",
        label="GitHub",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        profile_url="https://api.github.com/user",
        repo_url_template="https://api.github.com/repos/{full}",
        # ★ `read:user` = 只读公开档案（★ U3.3：权限越少，越多人敢点）
        scope="read:user",
        login_field="login",
        avatar_field="avatar_url",
        id_fields=("id",),
        user_agent="astrolabe",
    ),
    "gitee": Provider(
        key="gitee",
        label="Gitee",
        authorize_url="https://gitee.com/oauth/authorize",
        token_url="https://gitee.com/oauth/token",
        profile_url="https://gitee.com/api/v5/user",
        # ⚠★ Gitee 的仓库也在 `/api/v5/` 下 —— ★ 不能套用 GitHub 的 `/repos/` 形态
        repo_url_template="https://gitee.com/api/v5/repos/{full}",
        scope="user_info",
        login_field="login",
        avatar_field="avatar_url",
        id_fields=("id",),
        user_agent="astrolabe",
    ),
}


def get_provider(key: str) -> Provider:
    p = PROVIDERS.get((key or "").strip().lower())
    if p is None:
        raise OAuthError(f"不支持的登录方式：{key}")
    return p


class OAuthError(Exception):
    """★ 第三方交互失败 —— ⚠ **消息是给用户看的**（❌ 不要把内部细节塞进去）。"""


# ===========================================================================
# HTTP（★ 可注入 —— 冒烟测试用假 fetcher，❌ 不真的去连 GitHub）
# ===========================================================================


class HttpFetcher:
    """★ 默认实现：**标准库 `urllib`**（❌ 不引入 `requests` —— 少一套依赖）。"""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def post_form(self, url: str, data: dict[str, Any], *, headers: dict | None = None) -> dict:
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                **(headers or {}),
            },
            method="POST",
        )
        return self._open(req)

    def get_json(self, url: str, *, headers: dict | None = None) -> dict:
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", **(headers or {})}, method="GET"
        )
        return self._open(req)

    def _open(self, req) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:      # noqa: PERF203
            raw = exc.read().decode("utf-8", "replace")
            # ★ 把第三方的错误原样带出来一小段（★ 便于排查，⚠ 但不整坨塞给用户）
            raise OAuthError(f"第三方服务返回错误（HTTP {exc.code}）：{raw[:200]}") from exc
        except OSError as exc:
            raise OAuthError("无法连接第三方登录服务，请稍后再试。") from exc

        try:
            return json.loads(raw)
        except ValueError as exc:
            raise OAuthError("第三方服务返回了无法解析的内容。") from exc


_default_fetcher = HttpFetcher()


# ===========================================================================
# 配置
# ===========================================================================


def _client(provider: Provider, conf: dict | None = None) -> tuple[str, str]:
    """★ 取 client_id / client_secret。

    ⚠★ **这两个是机密，放 `settings` 的环境变量，❌ 不放 `AppSetting`** ——
      ★ 后者会进数据库、并且**要在后台明文显示在页面上**。
    """
    conf = conf if conf is not None else getattr(settings, "ASTROLABE_OAUTH", {})
    block = (conf or {}).get(provider.key) or {}
    cid = (block.get("client_id") or "").strip()
    secret = (block.get("client_secret") or "").strip()
    if not cid or not secret:
        raise OAuthError(f"{provider.label} 登录尚未配置完成。")
    return cid, secret


def redirect_uri(provider: Provider, *, base_url: str | None = None) -> str:
    """★ 回调地址 —— ⚠★ **授权与换 token 两处必须完全一致**（否则第三方会拒绝）。"""
    base = (base_url or getattr(settings, "ASTROLABE_BASE_URL", "http://localhost:8000")).rstrip("/")
    return f"{base}/api/auth/{provider.key}/callback"


def enabled_providers() -> list[dict[str, str]]:
    """★ 哪些 provider **真的配好了**（⚠ 没配好的**不要显示在登录页上** —— 点了必然报错）。"""
    conf = getattr(settings, "ASTROLABE_OAUTH", {}) or {}
    out = []
    for key, p in PROVIDERS.items():
        block = conf.get(key) or {}
        if (block.get("client_id") or "").strip() and (block.get("client_secret") or "").strip():
            out.append({"key": key, "label": p.label})
    return out


#: ★ `intent` 允许的键与长度上限 —— ⚠★ **必须白名单**：
#:   ★ `intent` 来自请求体（用户可控）⇒ 若不限量，★ 一个 10MB 的 JSON 会被塞进数据库。
_INTENT_LIMITS: dict[str, int] = {
    "name": 200,
    "desc": 2000,
    "source_path": 512,
}


def _slim_intent(intent: dict | None) -> dict:
    """★ 裁剪 `intent` —— ⚠ **只留白名单内的键，并截断长度**（★ 见上方说明）。"""
    if not isinstance(intent, dict):
        return {}
    out: dict[str, str] = {}
    for key, limit in _INTENT_LIMITS.items():
        val = intent.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()[:limit]
    return out


# ===========================================================================
# ① 发起
# ===========================================================================


@dataclass
class OAuthStart:
    url: str
    state: OAuthState


def start(
    provider_key: str,
    *,
    action: str = OAuthState.ACTION_LOGIN,
    invite_token: str = "",
    next_url: str = "",
    repo: str = "",
    project_ref: str = "",
    intent: dict | None = None,
    remember: bool = True,
    base_url: str | None = None,
    now: datetime | None = None,
) -> OAuthStart:
    """★ 发起授权：**建一个一次性 state + 拼授权 URL**。

    ★★ `invite_token` 在这里就写进 state —— 见 `OAuthState` 文档
      （★ 因为本平台不保存 token，**跳转前必须把意图塞进 state**）。
    """
    p = get_provider(provider_key)
    cid, _ = _client(p)

    ttl = int(appsettings.get("oauth.state_ttl_seconds") or 600)
    st = OAuthState.objects.create(
        state=secrets.token_urlsafe(24),
        provider=p.key,
        action=action if action in dict(OAuthState.ACTION_CHOICES) else OAuthState.ACTION_LOGIN,
        invite_token=(invite_token or "").strip()[:64],
        next_url=(next_url or "")[:512],
        repo=(repo or "")[:512],
        project_ref=(project_ref or "")[:64],
        # ★ 发布意图的其余字段（⚠ 只留小字段 —— state 是公开可猜的载体，别塞大对象）
        intent=_slim_intent(intent),
        # ★ 「记住我」—— ⚠ 必须存进 state（回调时用户已经不在我们页面上了，见字段说明）
        remember=bool(remember),
        expires_at=(now or timezone.now()) + timedelta(seconds=max(60, ttl)),
    )

    query = urllib.parse.urlencode(
        {
            "client_id": cid,
            "redirect_uri": redirect_uri(p, base_url=base_url),
            "scope": p.scope,
            "state": st.state,
            "response_type": "code",
            # ⚠ 换取 token 的 httpx 请求也要带，但这一步只影响展示
            "allow_signup": "true",
        }
    )
    return OAuthStart(url=f"{p.authorize_url}?{query}", state=st)


# ===========================================================================
# ② 回调
# ===========================================================================


@dataclass
class OAuthResult:
    """★ 回调结论。"""

    ok: bool = False
    #: ★ `login`（已绑定过）或 `register`（首次建立账号）—— ★ 两者查的开关**不同**
    action: str = ""
    user: Any = None
    identity: OAuthIdentity | None = None
    #: ★★ **给用户看的说明**（★ 拒绝时**必须**能读懂为什么）
    message: str = ""
    next_url: str = ""
    #: ★ 「记住我」（★ 由 `state` 带过来的，见 `OAuthState.remember`）
    remember: bool = True
    state_row: OAuthState | None = None

    # ⚠★★ **只在本次调用内使用，❌ 绝不落库** ——
    #   ★ 由调用方（发布流程）**当场拿去校验归属，用完即弃**（见模块文档）
    access_token: str = ""

    provider: str = ""
    provider_user_id: str = ""
    login: str = ""


def callback(
    provider_key: str,
    *,
    code: str,
    state: str,
    fetcher: HttpFetcher | None = None,
    base_url: str | None = None,
    now: datetime | None = None,
) -> OAuthResult:
    """★★ **OAuth 回调** —— ★★ `U4.8` 那个洞的**唯一守门处**。

    ★ 流程见模块文档；★ 关键在第 ⑤ 步：★ **「没绑定过」走的是注册，必须过邀请校验**。
    """
    f = fetcher or _default_fetcher
    now = now or timezone.now()

    try:
        p = get_provider(provider_key)
        cid, secret = _client(p)
    except OAuthError as exc:
        return OAuthResult(ok=False, message=str(exc))

    # ---- ① ★★ 消费 state（★ 一次性 + 防重放）----
    st, why = _consume_state(state, provider_key=p.key, now=now)
    if st is None:
        return OAuthResult(ok=False, message=why)

    # ---- ② 换 token ----
    try:
        tok = f.post_form(
            p.token_url,
            {
                "client_id": cid,
                "client_secret": secret,
                "code": code,
                "redirect_uri": redirect_uri(p, base_url=base_url),
                "grant_type": "authorization_code",
            },
            headers={"User-Agent": p.user_agent},
        )
        access_token = (tok.get("access_token") or "").strip()
        if not access_token:
            return OAuthResult(
                ok=False, state_row=st,
                message=f"未能从 {p.label} 取得授权（{tok.get('error_description') or tok.get('error') or '未知原因'}）。",
            )
    except OAuthError as exc:
        return OAuthResult(ok=False, state_row=st, message=str(exc))

    # ---- ③ 取身份 ----
    try:
        prof = f.get_json(
            p.profile_url,
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": p.user_agent},
        )
    except OAuthError as exc:
        return OAuthResult(ok=False, state_row=st, message=str(exc))

    provider_user_id = ""
    for fld in p.id_fields:
        if prof.get(fld) not in (None, ""):
            provider_user_id = str(prof[fld])
            break
    login = str(prof.get(p.login_field) or "").strip()

    if not provider_user_id:
        return OAuthResult(
            ok=False, state_row=st,
            message=f"{p.label} 没有返回用户标识，无法确认身份。",
        )

    avatar = str(prof.get(p.avatar_field) or "")[:512]

    base = OAuthResult(
        access_token=access_token,     # ⚠ 用完即弃，❌ 不落库
        provider=p.key,
        provider_user_id=provider_user_id,
        login=login,
        state_row=st,
        next_url=st.next_url,
        remember=st.remember,
    )

    # ---- ④ ★★ 判断：这个 provider 身份【绑定过账号】吗？----
    ident = (
        OAuthIdentity.objects.select_related("user")
        .filter(provider=p.key, provider_user_id=provider_user_id)
        .first()
    )

    if ident is not None:
        return _login(ident, login=login, avatar=avatar, now=now, base=base)

    # ---- ⑤ ★★ 没绑定 ⇒ **注册**（★ `U4.8` 的洞就在这里）----
    return _register(p, login=login, avatar=avatar, now=now, base=base)


def _consume_state(
    state: str, *, provider_key: str, now: datetime
) -> tuple[OAuthState | None, str]:
    """★★ **消费 state** —— ★ **一次性**（`select_for_update` + `consumed_at`）。

    ⚠★ 为什么必须一次性：★ 否则回调 URL 可以被**重放** ——
      ★ 攻击者拿到一次授权码之后可以反复提交。

    ★★ 返回 `(row, 失败原因)` ——
      ⚠ 刻意**区分「已用过」和「已过期」**（★ 与 `U3.9` 同一条纪律：**说清真正的原因**）：
      ★ 用户**双击了回调链接**时会看到「这次授权已经用过了」而不是含糊的「无效或已过期」，
      ⚠ 后者会让他误以为是**服务端出了问题**、反复重试。

    ⚠ 但**「state 不存在」与「provider 不匹配」仍然合并成一句** ——
      ★ 那是**攻击面**（区分开等于给探测者免费反馈）。
    """
    state = (state or "").strip()
    if not state:
        return None, "缺少授权会话参数，请重新发起登录。"

    with transaction.atomic():
        row = OAuthState.objects.select_for_update().filter(state=state).first()
        if row is None:
            return None, "授权会话无效，请重新发起登录。"
        if row.provider != provider_key:
            return None, "授权会话与登录方式不匹配，请重新发起登录。"
        if row.consumed_at is not None:
            return None, "这次授权已经用过了，请重新发起登录。"
        if not row.is_usable(now):
            return None, row.reject_reason(now)

        row.consumed_at = now
        row.save(update_fields=["consumed_at", "updated_at"])
        return row, ""


def _login(ident: OAuthIdentity, *, login: str, avatar: str, now: datetime, base: OAuthResult) -> OAuthResult:
    """★ **已绑定过 ⇒ 登录** —— ★★ **只查 `login_open`**（❌ 不查注册开关）。

    ⚠★ 这一点很重要：★ 邀请制测试期 `registration_open = false`，
      ★ 但**已有账号的人必须还能登录** —— ⚠ 否则等于把老用户也踢出去了
      （★ 那就变成 `paused` 了，见 `U4.6`）。
    """
    if not appsettings.get_bool("login_open"):
        return OAuthResult(
            ok=False, state_row=base.state_row,
            message="本站当前暂停登录，请稍后再试。",
        )

    # ★ 刷新 `login`（⚠ 它会变 —— `U3.2` 坑 1；★ `provider_user_id` 才是判据）
    upd = ["last_login_at", "updated_at"]
    ident.last_login_at = now
    if login and ident.login != login:
        ident.login = login[:150]
        upd.append("login")
    if avatar and ident.avatar_url != avatar:
        ident.avatar_url = avatar
        upd.append("avatar_url")
    ident.save(update_fields=upd)

    return OAuthResult(
        ok=True, action=OAuthState.ACTION_LOGIN, user=ident.user, identity=ident,
        message="", next_url=base.next_url, remember=base.remember,
        access_token=base.access_token, provider=base.provider,
        provider_user_id=base.provider_user_id, login=base.login,
        state_row=base.state_row,
    )


class _Abort(Exception):
    """★ 内部：用于**主动回滚**建号事务（⚠ 消息是给用户看的）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _register(p: Provider, *, login: str, avatar: str, now: datetime, base: OAuthResult) -> OAuthResult:  # noqa: PLR0911
    """★★ **首次建立账号 ⇒ 注册** —— ★★ 必须过 `registration_gate()`。

    ★★ 三条纪律逐条落实（`U4.8`）：

    | # | 纪律 | 这里怎么做 |
    |---|---|---|
    | **1** | 邀请码**校验通过前不消耗** | ★ 先 `check()`；★ 真正 `redeem()` 在**建号事务内** |
    | **2** | 核销与建号**同事务** | ★ `redeem()` 失败 ⇒ **`raise` 回滚整个建号** |
    | **3** | `registration_open=false` **一律拒绝**且给**可读原因** | ★ 直接返回 `gate.message` |
    """
    st = base.state_row
    assert st is not None

    # ---- ★★ 纪律 3：注册门禁（★ 唯一入口，❌ 不在这里重写开关判断）----
    gate = invites.registration_gate()
    if not gate.allowed:
        return OAuthResult(
            ok=False, state_row=st,
            message=gate.message or "本站当前未开放注册。",
        )

    # ---- ★ 纪律 1：**只校验，❌ 不消耗** ----
    invite_token = (st.invite_token or "").strip()
    if gate.invite_required:
        if not invite_token:
            return OAuthResult(
                ok=False, state_row=st,
                message="本站为邀请制，请先填写邀请码或通过邀请链接进入。",
            )
        c = invites.check(invite_token, at=now)
        if not c.ok:
            return OAuthResult(
                ok=False, state_row=st,
                message=c.message or "邀请凭证无效。",
            )

    # ---- ★★ 纪律 2：建号 + 核销 **同一个事务** ----
    user = None
    try:
        with transaction.atomic():
            user = _create_user(login=login)

            OAuthIdentity.objects.create(
                user=user,
                provider=p.key,
                provider_user_id=base.provider_user_id,
                login=login[:150],
                avatar_url=avatar,
                last_login_at=now,
            )

            if invite_token:
                # ★ 核销（★ 这里是**保存点**：失败则连同建号一起回滚）
                r = invites.redeem(invite_token, user, at=now)
                if not r.ok:
                    # ⚠★ 关键：**raise 把建号一起回滚** ——
                    #   ★ 否则会留下「账号建了、但不算被邀请」的半成品
                    raise _Abort(r.message or "邀请凭证无效。")

            AuditLog.objects.create(
                actor=user,
                action="user.register",
                target_kind="User",
                target_id=str(user.pk),
                detail={
                    "provider": p.key,
                    "provider_user_id": base.provider_user_id,
                    "login": login,
                    "invited_by": getattr(getattr(user, "profile", None), "invited_by_id", None),
                    "invite_used": bool(invite_token),
                },
            )
    except _Abort as exc:
        return OAuthResult(ok=False, state_row=st, message=exc.message)
    except IntegrityError:
        # ★ 并发注册撞了唯一约束 —— ⚠ 让用户重试一次即可（★ 不多做自动重试，
        #   因为这里撞的可能是 `provider_user_id` 唯一约束，那说明**另一个请求刚建完**）
        return OAuthResult(
            ok=False, state_row=st,
            message="这个账号刚刚已经注册过了，请重新点击登录。",
        )

    return OAuthResult(
        ok=True, action="register", user=user,
        identity=OAuthIdentity.objects.filter(user=user, provider=p.key).first(),
        message="", next_url=st.next_url, remember=base.remember,
        access_token=base.access_token, provider=p.key,
        provider_user_id=base.provider_user_id, login=login,
        state_row=st,
    )


def _create_user(*, login: str):
    """★ 建本站账号。

    ⚠★ 两条：
    ① ★ **`set_unusable_password()`** —— ★ 本站**没有密码登录**（`U4.2`），
       ★ 所以账号从建立的第一天起就**没有可用密码**（⚠ 不是"空密码"）。
    ② ★ **用户名要去重** —— ⚠ 不同 provider 可能有同名 `login`
       （★ 一个 Gitee 用户和一个 GitHub 用户都可能叫 `alice`）。
    """
    User = get_user_model()
    username = _pick_username(get_user_model(), login)

    user = User(username=username)
    user.set_unusable_password()
    # ★ 不写 `email` —— ⚠ `read:user` 拿到的邮箱可能是私有的/不可靠的（`U3.3`）
    user.save()
    return user


def _pick_username(User, base: str) -> str:
    """★ 由 `login` 推出一个**可用的**本站用户名（⚠ 撞了就加后缀）。"""
    cleaned = re.sub(r"[^\w.@+\-]", "_", (base or "").strip())[:120] or "user"
    # ★ 避开 Django 的保留名（⚠ `/admin/` 之类）
    if cleaned.lower() in ("admin", "administrator", "root", "staff"):
        cleaned = f"{cleaned}_user"

    if not User.objects.filter(username=cleaned).exists():
        return cleaned
    for i in range(2, 50):
        cand = f"{cleaned}_{i}"
        if not User.objects.filter(username=cand).exists():
            return cand
    return f"{cleaned}_{secrets.token_hex(4)}"


# ===========================================================================
# ③ Gate 0：归属校验（`U3.1` 第 ②③ 步）—— ★ 用刚拿到的 token **当场**做
# ===========================================================================


@dataclass
class OwnershipVerdict:
    """★ 归属校验结论（★ `U3.1` 第 ②③ 步）。"""

    ok: bool = False
    reason_code: str = ""
    #: ★★ **给用户看的原因** —— ★ 四步里任何一步不过都要能读懂为什么
    message: str = ""
    repo: dict = field(default_factory=dict)


def verify_repo_ownership(
    provider_key: str,
    access_token: str,
    *,
    repo_full_name: str,
    provider_user_id: str,
    fetcher: HttpFetcher | None = None,
) -> OwnershipVerdict:
    """★★ **归属校验**（`U3.1`）：★ 只能拉**你自己的**仓库。

    ★ 判据（★ 全部必须成立）：

    | # | 判据 | 不过时 |
    |---|---|---|
    | **1** | ★★ `repo.owner.id == provider_user_id` | ★ 拒绝（"这不是你的仓库"） |
    | **2** | ★★ `repo.fork == false` | ★ 拒绝（`U3.2` 坑 3：**你是 fork owner，但代码不是你写的**） |
    | **3** | ★★ **个人仓库**（`owner.type != "Organization"`） | ★ 拒绝（`U3.2` 坑 2：★ 一期明确只放行个人仓库；⚠ 组织仓库属**企业版**范畴，见 `PRODUCT-VERSIONS` B3） |

    ⚠★★ **两个必须守的口径**：

    · ★ **比 `provider_user_id`（数字 ID），❌ 不比 `login`** ——
      ⚠ 用户名能改（`U3.2` 坑 1），比 `login` 会让**改个名就绕过校验**。
    · ★ 通过 ≠ 拥有版权 —— ★ 官方文案**只能写「已验证账号归属」**，
      ⚠★ **绝不能写「已验证版权」**（`U3.6` / 契约 §20.7）。
    """
    f = fetcher or _default_fetcher
    full = (repo_full_name or "").strip().strip("/")
    if full.count("/") != 1:
        return OwnershipVerdict(
            ok=False, reason_code="bad_repo",
            message="仓库格式应为 owner/repo，请检查后重试。",
        )

    try:
        p = get_provider(provider_key)
        repo = f.get_json(
            p.repo_url_template.format(full=full),
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": p.user_agent},
        )
    except OAuthError as exc:
        return OwnershipVerdict(ok=False, reason_code="api_error", message=str(exc))

    if not isinstance(repo, dict) or repo.get("id") in (None, "", 0):
        # ⚠★ 特别注意：**拉不到就当通过**是绝对不能有的行为
        return OwnershipVerdict(
            ok=False, reason_code="not_found",
            message="找不到这个仓库（可能是私有仓库，或者名字写错了）。",
        )

    # ⚠ Gitee 把归属放在 `namespace`，GitHub 放在 `owner` —— ★ 两个都试
    owner = repo.get("owner") or repo.get("namespace") or {}

    # ---- ① ★★ 归属：比【数字 ID】（❌ 不比 login）----
    if str(owner.get("id", "")) != str(provider_user_id):
        return OwnershipVerdict(
            ok=False, reason_code="not_owner", repo=repo,
            message=(
                f"这个仓库属于 {owner.get('login') or '其他人'}，不是你的账号。"
                "本站只能发布你自己名下的仓库。"
            ),
        )

    # ---- ② ★★ 拒绝 Fork ----
    if repo.get("fork") is True:
        parent = (repo.get("parent") or {}).get("full_name") or ""
        return OwnershipVerdict(
            ok=False, reason_code="fork", repo=repo,
            message=(
                "这是一个 Fork 仓库。Fork 的代码不是你写的，"
                + (f"请到原作者仓库（{parent}）发布。" if parent else "请到原作者仓库发布。")
            ),
        )

    # ---- ③ ★★ 只放行个人仓库 ----
    if str(owner.get("type") or "").lower() == "organization":
        return OwnershipVerdict(
            ok=False, reason_code="organization", repo=repo,
            message="本站一期只支持个人仓库，组织名下的仓库暂不支持。",
        )

    return OwnershipVerdict(ok=True, reason_code="ok", repo=repo, message="")


# ===========================================================================
# 维护
# ===========================================================================


def purge_expired_states(*, now: datetime | None = None) -> int:
    """★ 清理过期的 `OAuthState`（⚠ 否则这张表会无限增长）。

    ★ 由定时作业调用（同 `heat_flush` 的思路）。
    """
    now = now or timezone.now()
    deleted, _ = OAuthState.objects.filter(expires_at__lt=now).delete()
    return deleted


def identity_of(user, provider: str | None = None) -> OAuthIdentity | None:
    """★ 取某个用户绑定的第三方身份（⚠ 一期一 provider 一条）。"""
    qs = OAuthIdentity.objects.filter(user=user)
    if provider:
        qs = qs.filter(provider=provider)
    return qs.order_by("created_at").first()
