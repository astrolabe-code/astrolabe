"""Astrolabe · 冒烟：**认证端点**（OAuth + Bearer 令牌）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_auth_api.py"

★★ 用 **Django 测试客户端**跑（❌ 不是直接调函数）—— ★ 因为要验证的正是
   **中间件、CSRF、状态码**这些"只有走完 HTTP 栈才存在"的东西。

★★★ 重点验证**四件最要命的事**：

1. ★★★ **`next_url` 白名单（防 open redirect ⇒ token 泄露）** ——
   ⚠ 含 `//evil.com` 这种**协议相对 URL 绕过**
2. ★★★ **第 ③ 态"不回退 session"** —— 无效 Bearer 必须 401，**哪怕 session 是登录的**
3. ★★ **Bearer 免 CSRF**（★ 且反过来：没有 Bearer 的 POST **必须**被 CSRF 拦）
4. ★★ **token 明文只出现在 fragment 里**（⚠ `?token=` 会进日志）
"""

from datetime import timedelta

from django.conf import settings as dj
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.utils import timezone as tz

from core import oauth
from core.models import OAuthIdentity, OAuthState
from web import auth

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


U = get_user_model()

# ---------------------------------------------------------------- 假第三方
dj.ASTROLABE_OAUTH = {
    "github": {"client_id": "cid", "client_secret": "sec"},
    "gitee": {"client_id": "cid", "client_secret": "sec"},
}
dj.ASTROLABE_BASE_URL = "http://test.local"
dj.ASTROLABE_SPA_URL = "http://spa.test/"
dj.ASTROLABE_ALLOWED_ORIGINS = ("http://spa.test",)
_PID = [810000]


class FakeFetcher:
    def __init__(self, uid=None, login="smoke_api_user"):
        self.uid, self.login = uid, login

    def post_form(self, url, data, *, headers=None):  # noqa: ARG002
        return {"access_token": "gho_fake"}

    def get_json(self, url, *, headers=None):  # noqa: ARG002
        return {"id": self.uid, "login": self.login, "avatar_url": ""}


def install_fetcher(uid=None, login="smoke_api_user"):
    """★ 把假 fetcher 装到模块级默认值上（⚠ 视图不接受注入参数）。"""
    _PID[0] += 1
    oauth._default_fetcher = FakeFetcher(uid or _PID[0], login)
    return _PID[0]


admin, _ = U.objects.get_or_create(username="smoke_api_admin")
admin.is_superuser = admin.is_staff = True
admin.save(update_fields=["is_staff", "is_superuser"])

# ★ 清理
from core import appsettings  # noqa: E402

OAuthState.objects.all().delete()
# ⚠★ **必须排除 admin 自己** —— `smoke_api_admin` 也匹配这个前缀！
#   ⚠ 删掉它之后，后面 `appsettings.set_value(..., actor=admin)` 会写一个
#     **指向已删除用户的 `updated_by_id`** ⇒ FK 违例（踩过一次）。
for u in U.objects.filter(username__startswith="smoke_api_").exclude(pk=admin.pk):
    OAuthIdentity.objects.filter(user=u).delete()
    u.api_tokens.all().delete()
    u.delete()

# ⚠ 测试客户端用 `testserver` 做 Host
_ctx = override_settings(ALLOWED_HOSTS=["testserver", "localhost", "test.local"])
_ctx.enable()

c = Client()                            # ★ 默认不强制 CSRF
c_csrf = Client(enforce_csrf_checks=True)  # ★ 用来验证 CSRF 边界


# ===========================================================================
print("=" * 80)
print("① /api/auth/providers/ —— ★ 登录页要什么就给什么")
print("=" * 80)
r = c.get("/api/auth/providers/")
body = r.json()
check("状态码", r.status_code, 200)
check("★ 有 github / gitee", [p["key"] for p in body["data"]["providers"]], ["github", "gitee"])
check("★★ 暴露了注册门禁状态（前端要在【点之前】就告知）",
      "registration" in body["data"], True)
check("★ 且含 invite_required", "invite_required" in body["data"]["registration"], True)

# ===========================================================================
print()
print("=" * 80)
print("② /api/auth/me/ 无令牌 ⇒ 401 且【带 code】")
print("=" * 80)
r = c.get("/api/auth/me/")
check("状态码", r.status_code, 401)
check("★ 带 error.code（★ 前端必须对它分支）", r.json()["error"]["code"], "unauthenticated")

# ===========================================================================
print()
print("=" * 80)
print("③ ★★★ next_url 白名单（防 open redirect ⇒ **token 泄露**）")
print("=" * 80)
r = c.post("/api/auth/github/start/", {"next_url": "https://evil.com"}, content_type="application/json")
check("★★★ 外站域名 ⇒ 拒绝", r.status_code, 400)
check("★★ 原因码 = bad_next_url", r.json()["error"]["code"], "bad_next_url")

# ⚠★ 这条是最容易漏的：`//evil.com` 是**协议相对 URL**，浏览器会当成 https://evil.com
r = c.post("/api/auth/github/start/", {"next_url": "//evil.com"}, content_type="application/json")
check("★★★ 协议相对 //evil.com ⇒ 也必须拒绝（经典绕过）", r.status_code, 400)

r = c.post("/api/auth/github/start/", {"next_url": "/\\evil.com"}, content_type="application/json")
check("★★ 反斜杠 /\\\\evil.com ⇒ 拒绝", r.status_code, 400)

r = c.post("/api/auth/github/start/", {"next_url": "/p/proj_x"}, content_type="application/json")
check("★ 站内相对路径 ⇒ 放行", r.status_code, 200)
check("★ 且返回了授权 URL", "github.com/login/oauth/authorize" in r.json()["data"]["authorize_url"], True)

r = c.post("/api/auth/github/start/", {"next_url": "http://spa.test/me"}, content_type="application/json")
check("★ 白名单内的 origin ⇒ 放行", r.status_code, 200)

# ===========================================================================
print()
print("=" * 80)
print("④ 完整一轮：start → callback（注册）→ me → logout")
print("=" * 80)
uid = install_fetcher()
appsettings.set_value("registration_open", True, actor=admin)
appsettings.set_value("invite_required", False, actor=admin)

r = c.post("/api/auth/github/start/", {"next_url": "/me"}, content_type="application/json")
state = r.json()["data"]["state"]
check("★ 拿到了 state", bool(state), True)

r = c.get(f"/api/auth/github/callback/?code=abc&state={state}&format=json")
check("回调状态码", r.status_code, 200)
data = r.json()["data"]
check("★★ 签发了令牌", bool(data["token"]), True)
check("★★ token 带可辨识前缀 `ast_`", data["token"].startswith("ast_"), True)
check("★ action = register（首次登录 = 注册）", data["action"], "register")
check("★ 返回了用户投影", data["user"]["username"], "smoke_api_user")
check("★★ 用户投影【不含】email（★ 多给一个字段就多一分泄露面）",
      "email" in data["user"], False)

token = data["token"]
c_bearer = Client(HTTP_AUTHORIZATION=f"Bearer {token}")

r = c_bearer.get("/api/auth/me/")
check("★ 带令牌 ⇒ 200", r.status_code, 200)
check("★ 认出了同一个人", r.json()["data"]["user"]["username"], "smoke_api_user")
check("★ 返回了 exp", bool(r.json()["data"]["exp"]), True)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★★ 第 ③ 态：无效 Bearer ⇒ 401，且【不回退 session】")
print("=" * 80)
r = c.get("/api/auth/me/", HTTP_AUTHORIZATION="Bearer ast_bad_token_xxxxxxxxxxxxxxxx")
check("★★ 无效令牌 ⇒ 401", r.status_code, 401)
check("★★ 且 code = unauthenticated", r.json()["error"]["code"], "unauthenticated")

# ★★ 关键：**同一个客户端先建立 session 登录，再带坏 token** —— 必须仍然 401
c_mixed = Client()
c_mixed.force_login(admin)          # ★ session 已登录
r = c_mixed.get("/api/auth/me/")
check("★ 纯 session 登录 ⇒ 能认出来（第 ① 态）", r.status_code, 200)
r = c_mixed.get("/api/auth/me/", HTTP_AUTHORIZATION="Bearer ast_bad_token_xxxxxxxx")
check("★★★ 同一客户端 + 坏 token ⇒ 【仍然 401，不回退 session】", r.status_code, 401)

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★★ CSRF 边界（契约 §7）")
print("=" * 80)
# ★ 带 Bearer ⇒ 免 CSRF（★ 中间件置了 _dont_enforce_csrf_checks）
r = c_csrf.post("/api/auth/logout/", content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token}")
check("★★ Bearer POST 免 CSRF（强制 CSRF 的客户端也放行）", r.status_code, 200)

# ★ 不带 Bearer 的写请求 ⇒ 必须被 CSRF 拦（★ 否则就是 CSRF 漏洞）
r = c_csrf.post("/api/auth/logout/", content_type="application/json")
check("★★★ 无 Bearer 的 POST ⇒ 被 CSRF 拦（403）", r.status_code, 403)

# ===========================================================================
print()
print("=" * 80)
print("⑦ 登出 / 幂等 / 登出全部设备")
print("=" * 80)
install_fetcher(login="smoke_api_user2")
r = c.post("/api/auth/github/start/", {"next_url": "/me"}, content_type="application/json")
st2 = r.json()["data"]["state"]
token2 = c.get(f"/api/auth/github/callback/?code=x&state={st2}&format=json").json()["data"]["token"]
c2 = Client(HTTP_AUTHORIZATION=f"Bearer {token2}")

check("★ 登出 ⇒ revoked=True", c2.post("/api/auth/logout/").json()["data"]["revoked"], True)
check("★★ 登出后 me ⇒ 401（令牌已撤销）", c2.get("/api/auth/me/").status_code, 401)
# ★★ 幂等：⚠ 典型场景是"响应丢了、前端重试"—— 必须**不报错**
r = c2.post("/api/auth/logout/")
check("★★★ 重复登出 ⇒ 200 且 revoked=False（幂等）", r.status_code, 200)
check("★★ 且返回体形态正确", r.json()["data"]["revoked"], False)

# ---- 登出全部设备（★ 用一条【新的】令牌 —— ⚠ 上面那条已经被撤销了）----
install_fetcher(login="smoke_api_user4")
st5 = c.post("/api/auth/github/start/", {"next_url": "/me"},
             content_type="application/json").json()["data"]["state"]
fresh = c.get(f"/api/auth/github/callback/?code=w&state={st5}&format=json").json()["data"]["token"]
c4 = Client(HTTP_AUTHORIZATION=f"Bearer {fresh}")

r = c4.get("/api/auth/tokens/")
check("★ 能列出登录设备", len(r.json()["data"]["tokens"]) >= 1, True)
check("★★ 设备列表【绝不含明文】（只有前缀）",
      any("token" in t for t in r.json()["data"]["tokens"]), False)

n = c4.post("/api/auth/logout-all/").json()["data"]["revoked"]
check("★★ 登出全部成功", n >= 1, True)
check("★★ 全部撤销后 me ⇒ 401", c4.get("/api/auth/me/").status_code, 401)

# ===========================================================================
print()
print("=" * 80)
print("⑧ ★★ token 明文只进 fragment（⚠ `?token=` 会进 nginx 日志）")
print("=" * 80)
install_fetcher(login="smoke_api_user3")
r = c.post("/api/auth/github/start/", {"next_url": "/me"}, content_type="application/json")
st3 = r.json()["data"]["state"]
r = c.get(f"/api/auth/github/callback/?code=y&state={st3}")
check("★ 默认是 302 重定向", r.status_code, 302)
location = r["Location"]
check("★★★ token 在 **fragment**（`#`）里，❌ 不是 query（`?`）", "#token=" in location, True)
check("★★ 且 URL 里没有 `?token=`", "?token=" in location, False)
check("★ 跳到了 next_url", location.startswith("http://spa.test/me") or location.startswith("/me"), True)

# ===========================================================================
print()
print("=" * 80)
print("⑨ state 一次性（防重放）+ 令牌生命周期")
print("=" * 80)
r = c.post("/api/auth/github/start/", {"next_url": "/me"}, content_type="application/json")
st4 = r.json()["data"]["state"]
r1 = c.get(f"/api/auth/github/callback/?code=z&state={st4}&format=json")
check("首次回调 ⇒ 成功", r1.status_code, 200)
r2 = c.get(f"/api/auth/github/callback/?code=z&state={st4}&format=json")
check("★★ 同一个 state 再回调 ⇒ 被拒（防重放）", r2.status_code, 401)

# ★ 令牌过期 ⇒ 校验失败
raw, tok = auth.issue_token(U.objects.get(username="smoke_api_user3"), remember=True)
check("★ 有效令牌能被校验", auth.verify_token(raw) is not None, True)
from core.models import ApiToken  # noqa: E402

ApiToken.objects.filter(pk=tok.pk).update(expires_at=tz.now() - timedelta(seconds=1))
check("★★ 过期令牌 ⇒ 校验失败", auth.verify_token(raw) is None, True)

raw2, tok2 = auth.issue_token(U.objects.get(username="smoke_api_user3"))
check("★ 库里存的是哈希（❌ 不是明文）", tok2.token_hash != raw2, True)
check("★ 哈希长度 = 64（blake2b digest_size=32 的 hex）", len(tok2.token_hash), 64)
check("★★ 且明文的 8 位前缀可辨认", tok2.prefix, raw2[:12])

# ===========================================================================
# 清理
appsettings.set_value("registration_open", False, actor=admin)
appsettings.set_value("invite_required", True, actor=admin)
_ctx.disable()

print()
print("=" * 80)
if FAILED:
    print(f"❌ 失败 {len(FAILED)} 项：")
    for f in FAILED:
        print(f"   - {f}")
else:
    print("✅ 全部通过")
print("=" * 80)
