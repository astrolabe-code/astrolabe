"""Astrolabe · ① Web 层：**发布**（★ 只负责"发起授权"）

★ 依据 `USERS-AND-AUTH.md` `U3.1`（四步链路）· `B148`（不保存 `access_token`）· `B149`（发布编排）。

---

# ★★★ 为什么发布是**两步**（而不是一个 POST 搞定）

⚠★ 因为本平台**不长期保存 `access_token`**（`B148`）：

```
① POST /api/projects/publish/start/     ← 就是本模块
      ⇒ 拿到 GitHub 授权 URL（★ 顺带把 name/desc/source_path 存进 state）
                        ↓  用户去 GitHub 点授权
② GET  /api/auth/<provider>/callback/    ← ★ 归属校验 + 建项目【都发生在这里】
      ⇒ ★★ 因为此时才第一次、也是唯一一次拿到 token（用完即弃）
```

★ 所以"发布"这个动作**在 `auth.callback` 里完成** —— ⚠ 这不是设计缺陷，
  ★★ 而是**"不保存凭据"必然的代价**（★ 换来的是 token 泄露这一类事故彻底不存在）。

⚠ 一期说明：**服务端拉取源码尚未实现** ⇒ `source_path` 需要是**容器内已放好的目录**。
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from core import invites, oauth
from core.models import OAuthIdentity, OAuthState
from web import permissions
from web.http import fail, ok, read_json, safe_next_url


def validate_repo(raw: str) -> tuple[str, str]:
    """★ 校验 `owner/repo` —— 返回 `(仓库全名, 错误信息)`（⚠ 错误信息为空表示通过）。"""
    full = (raw or "").strip().strip("/")
    if not full:
        return "", "请填写要发布的仓库（格式 owner/repo）"
    if full.count("/") != 1 or any(seg in ("", ".", "..") for seg in full.split("/")):
        return "", "仓库格式应为 owner/repo，请检查后重试"
    return full, ""


@require_http_methods(["POST"])
def start(request: HttpRequest) -> JsonResponse:
    """★ 发起「发布授权」—— ★★ 见模块文档（发布本身发生在回调里）。"""
    user = permissions.current_user(request)
    if user is None:
        return fail("请先登录", 401, code="unauthenticated")

    gate = invites.registration_gate()
    if gate.paused:
        return fail(gate.message or "站点正在维护", 503, code="paused")

    body = read_json(request)
    provider = str(body.get("provider") or "").strip().lower()
    if provider not in oauth.PROVIDERS:
        return fail("provider 必须是 github 或 gitee", 400, code="invalid_provider")

    repo, err = validate_repo(str(body.get("repo") or ""))
    if err:
        return fail(err, 400, code="bad_repo")

    # ★★ 早失败（fail fast）：★ 没绑定过这个 provider 的身份 ⇒ **归属校验一定过不了**
    #   ⚠ 所以别让用户白跑一趟 GitHub（★ 他回来只会看到"这不是你的仓库"）
    if not OAuthIdentity.objects.filter(user=user, provider=provider).exists():
        return fail(
            f"请先用 {provider} 登录一次，确认账号归属后再发布。",
            400,
            code="identity_missing",
        )

    next_url = safe_next_url(str(body.get("next_url") or ""))
    if next_url is None:
        return fail("next_url 不在允许的域名白名单内", 400, code="bad_next_url")

    # ★★ **`source_path` 只对 staff 生效**（`B152`）——
    #   ⚠★ 它能被用来**读容器里的任何目录**（★ 这台机器上还跑着数据库）⇒
    #     ★ 普通用户一律**不收**（★ 他的源码应当由作业层从 `repo_url` 拉取）。
    #   ⚠ 这里**不报错、只是忽略** —— ★ 报错会暴露"有路径检查"这件事给探测者
    #     （★ 与 `_safe_source_path()` 同一口径）。
    source_path = str(body.get("source_path") or "") if user.is_staff else ""

    st = oauth.start(
        provider,
        action=OAuthState.ACTION_PUBLISH,
        repo=repo,
        # ★★ 用户在表单里填的东西必须跨过一次跳转活下来 —— ⚠ 见 `OAuthState.intent` 的说明
        intent={
            "name": str(body.get("name") or ""),
            "desc": str(body.get("desc") or ""),
            "source_path": source_path,
        },
        next_url=next_url,
        remember=True,          # ★ 发布必然要登录，走长档
        base_url=getattr(settings, "ASTROLABE_BASE_URL", "").rstrip("/"),
    )
    return ok({"authorize_url": st.url, "state": st.state.state, "repo": repo})
