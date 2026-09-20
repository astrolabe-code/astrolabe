"""Astrolabe · 冒烟：**用户名 + 密码 的登录 / 注册**（`B170` · `U4.9`）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_password_auth.py"

★★★ 本脚本验证**四件事**：

1. ★★★ **`registration_open` 的新语义（`B170`）** —— 这是本批改动的**全部要害**：
   ★ `true`  ⇒ 入口可见 + 可注册
   ★★ `false` ⇒ 入口**隐藏**，★ **但持邀请码者仍可注册** ⚠
   （⚠★ 旧写法 `allowed=False` 会让**所有者发出去的每一个邀请码都变成废纸**）
2. ★★ **注册**：要不要码、弱密码、重名、★ **码被核销**
3. ★★ **登录**：对 / 错 / 停用 / `login_open=false`
4. ★★★ **一条安全底线**：★ **「用户名不存在」与「密码错误」必须返回【同一句话 + 同一个 code】**
   —— ★ 否则等于**免费告诉攻击者哪些用户名存在** ⚠

⚠ 全程**不碰真实第三方**（★ 这条链路本来就不涉及 OAuth）。
"""

import json
import secrets

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.test import Client

from core import appsettings, invites
from core.models import Invite
from web import auth as web_auth

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<56} = {got!r}")


U = get_user_model()
# ⚠★ `django.test.Client` 的 Host 是 `testserver` —— ★ 不在 `ALLOWED_HOSTS` 里会得到一个
#   **空的 400 HTML 页**（★ 什么也不说，⚠ 极易误判成"端点坏了"）
dj_settings.ALLOWED_HOSTS = ["*"]

admin, _ = U.objects.get_or_create(username="smoke_pw_admin")
admin.is_staff = True
admin.is_superuser = True
admin.save(update_fields=["is_staff", "is_superuser"])

c = Client()


def post(path, payload, **kw):
    """★ 统一的 POST —— ⚠★ 显式 `json.dumps`（★ 不依赖 Django 版本是否自动序列化）。

    ⚠ 踩过：★ Django 的 `test.Client` 在某些版本里**不会**把 dict 自动转成 JSON，
      ★ 于是 `read_json()` 读到空、接口回 `400 missing_fields`
      —— ⚠★ 看起来像"端点坏了"，★ 实际是**测试工具的事** ⚠
    """
    # ⚠★★ 注意这里是 **`c.post`**（❌ 不是 `post`）——
    #   ★ 本条曾经写成 `return post(...)` ⇒ **变成无限递归** ⚠
    #   ⚠ 而报错却是 `TypeError: got multiple values for keyword argument 'content_type'`
    #     （★ 递归调自己时那个关键字被重复传），⚠ **极易误判成"参数写重了"** ⚠
    # ⚠★ 顺便忽略调用方可能传的 `content_type` —— ★ 本函数**自己决定**怎么发
    kw.pop("content_type", None)
    return c.post(path, json.dumps(payload), content_type="application/json", **kw)

# 每轮清掉测试账号（★ 让脚本可重复跑）
U.objects.filter(username__startswith="smoke_pw_u").delete()

# 先把开关复位到"可预期"的起点
def _set(key, value):
    appsettings.set_value(key, value, actor=admin)


_set("paused", False)
_set("login_open", True)

print()
print("=" * 80)
print("① ★★★ `registration_gate()` 的三种组合（★ `B170` 改的语义）")
print("=" * 80)
_set("registration_open", True)
_set("invite_required", False)
g = invites.registration_gate()
check("★ 开放 + 不要码 ⇒ allowed", g.allowed, True)
check("★ 且 invite_required", g.invite_required, False)
check("★ 且入口可见（registration_open）", g.registration_open, True)

_set("registration_open", True)
_set("invite_required", True)
g = invites.registration_gate()
check("★ 开放 + 要码 ⇒ allowed", g.allowed, True)
check("★ 且 invite_required", g.invite_required, True)

_set("registration_open", False)
g = invites.registration_gate()
check("★★★ 隐藏入口 ⇒ ★ allowed【仍为 True】（持码者能进）", g.allowed, True)
check("★★★ 且【强制】要码", g.invite_required, True)
check("★ 且入口不可见", g.registration_open, False)
print(f"       提示语：{g.message}")

# ===========================================================================
print()
print("=" * 80)
print("② ★★ 注册：开放且不要码 ⇒ 直接成功")
print("=" * 80)
# ⚠★ 必须**重设** —— ① 的最后一步把它设成了 `False`（★ 那是"隐藏入口 + 强制要码"），
#   ⚠ 不重设的话这里会 **400 bad_invite**（★ 行为是对的，★ 是脚本漏了）⚠
_set("registration_open", True)
_set("invite_required", False)
r = post("/api/auth/register/", {"username": "smoke_pw_u1", "password": "Aa12345678"})
check("★★★ 201", r.status_code, 201)
body = r.json().get("data", {})
check("★★ 拿到了 token", bool(body.get("token")), True)
check("★ 用户名对", body.get("user", {}).get("username"), "smoke_pw_u1")
u1 = U.objects.filter(username="smoke_pw_u1").first()
check("★★★ 密码真的可用（★ 不是 unusable_password）", bool(u1 and u1.has_usable_password()), True)

print()
print("=" * 80)
print("③ ★★ 注册：重名 / 弱密码")
print("=" * 80)
r = post("/api/auth/register/", {"username": "smoke_pw_u1", "password": "Aa12345678"})
check("★★ 重名 ⇒ 409", r.status_code, 409)
check("★ 原因码", r.json()["error"]["code"], "username_taken")

r = post("/api/auth/register/", {"username": "smoke_pw_u2", "password": "12345678"})
check("★★ 纯数字密码 ⇒ 400", r.status_code, 400)
check("★ 原因码 = weak_password", r.json()["error"]["code"], "weak_password")

r = post("/api/auth/register/", {"username": "ab", "password": "Aa12345678"})
check("★ 用户名太短 ⇒ 400", r.status_code, 400)

# ===========================================================================
print()
print("=" * 80)
print("④ ★★★ 注册：隐藏入口 + 要码 ⇒ ★ 无码被拒、★ 有码可注册（B170 的核心）")
print("=" * 80)
_set("registration_open", False)

r = post("/api/auth/register/", {"username": "smoke_pw_u3", "password": "Aa12345678"})
check("★★★ 无码 ⇒ 400", r.status_code, 400)
check("★ 原因码 = bad_invite", r.json()["error"]["code"], "bad_invite")
check("★ 且没有建号", U.objects.filter(username="smoke_pw_u3").exists(), False)

inv = invites.create_invite(admin, note="smoke-password-auth")
r = post("/api/auth/register/",
           {"username": "smoke_pw_u3", "password": "Aa12345678", "invite_token": inv.token})
check("★★★ 带有效码 ⇒ 201（★ 隐藏入口也进得来）", r.status_code, 201)
inv.refresh_from_db()
check("★★ 码被核销（used_count=1）", inv.used_count, 1)

# ★ 同一个码再用 ⇒ 应被拒（★ `invite.default_uses` 默认 1）
r = post("/api/auth/register/",
           {"username": "smoke_pw_u4", "password": "Aa12345678", "invite_token": inv.token})
check("★★★ 同一个码再用 ⇒ 400（用一次即失效）", r.status_code, 400)
check("★ 且第二个号没建成", U.objects.filter(username="smoke_pw_u4").exists(), False)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★★ 登录：★★ 「用户名不存在」与「密码错误」必须【完全一致】")
print("=" * 80)
r1 = post("/api/auth/login/", {"username": "smoke_pw_u1", "password": "WRONG-pass-1"})
r2 = post("/api/auth/login/", {"username": "no_such_user_xyz", "password": "WRONG-pass-1"})
check("★★ 密码错 ⇒ 401", r1.status_code, 401)
check("★★ 用户不存在 ⇒ 401", r2.status_code, 401)
check("★★★ 状态码一致", r1.status_code, r2.status_code)
check("★★★ code 一致（★ code 也必须一样）",
      r1.json()["error"]["code"], r2.json()["error"]["code"])
check("★★★ 文案一致（★ 不能让人看出哪个用户存在）",
      r1.json()["error"]["message"], r2.json()["error"]["message"])
print(f"       统一文案：{r1.json()['error']['message']}")

print()
print("=" * 80)
print("⑥ ★★ 登录：正确凭据 ⇒ 拿到 token，且 token 能用")
print("=" * 80)
r = post("/api/auth/login/", {"username": "smoke_pw_u1", "password": "Aa12345678"})
check("★★★ 200", r.status_code, 200)
tok = r.json().get("data", {}).get("token")
check("★★ 拿到 token", bool(tok), True)

r = Client(HTTP_AUTHORIZATION=f"Bearer {tok}").get("/api/auth/me/")
check("★★★ 用这个 token 能过 /api/auth/me/", r.status_code, 200)
check("★ 身份对", r.json()["data"]["user"]["username"], "smoke_pw_u1")

# ===========================================================================
print()
print("=" * 80)
print("⑦ ★★ `login_open=false` ⇒ 新登录被拦（★ 但已有 token 不受影响 —— U4.6）")
print("=" * 80)
_set("login_open", False)
r = post("/api/auth/login/", {"username": "smoke_pw_u1", "password": "Aa12345678"})
check("★★★ 新登录 ⇒ 503", r.status_code, 503)
check("★ 原因码 = login_closed", r.json()["error"]["code"], "login_closed")
r = Client(HTTP_AUTHORIZATION=f"Bearer {tok}").get("/api/auth/me/")
check("★★★ 已有 token 【照常用】（★ 这就是 login_open 与 paused 的区别）", r.status_code, 200)

# ===========================================================================
print()
print("=" * 80)
print("⑧ ★★ 停用账号 ⇒ 403")
print("=" * 80)
_set("login_open", True)
u1.is_active = False
u1.save(update_fields=["is_active"])
r = post("/api/auth/login/", {"username": "smoke_pw_u1", "password": "Aa12345678"})
# ⚠★★ 期望值是 **401 `bad_credentials`**，❌ **不是 403** ——
#   ★ 因为 Django 的 `ModelBackend.authenticate()` **会先判 `is_active`**
#     ⇒ ★★ 停用用户**直接返回 `None`**（★ 那个 `is_active` 分支走不到）⚠
#   ★★ 而且**这是刻意的** —— ★ 返回"账号已停用"会**确认这个用户名存在**，
#     ⚠ 那就是**免费的用户名枚举信号** ⚠
check("★★ 停用 ⇒ 401（★ 刻意不区分，见下）", r.status_code, 401)
check("★★★ code 与密码错完全一致（★ 不泄露「这个用户名存在」）",
      r.json()["error"]["code"], "bad_credentials")
u1.is_active = True
u1.save(update_fields=["is_active"])

# ===========================================================================
print()
print("=" * 80)
print("⑨ ★★ 管理端：`GET /api/invites/`（★ `B171` 修过一个【必然 500】的 bug）")
print("=" * 80)
# ⚠★ 这一段是**补的** —— ★ 上一轮 AI 凭"代码看起来完备"就断言了"后端已就绪"，
#   ★★ 结果 `GET /api/invites/` 里有个 `body_qs`（**从未定义过**）⇒ **必然 500** ⚠
#   ★ 教训：★ **"接口已实现" ≠ "接口被验证过"** ⚠
admin_raw, _ = web_auth.issue_token(admin)
adm = Client(HTTP_AUTHORIZATION=f"Bearer {admin_raw}")

r = adm.get("/api/invites/")
check("★★★ 管理员能列邀请（★ 修前必然 500）", r.status_code, 200)
check("★★ 返回里是 invites 数组", isinstance(r.json().get("data", {}).get("invites"), list), True)

r = adm.post(
    "/api/invites/",
    json.dumps({"max_uses": 1, "valid_days": 1, "note": "smoke-b171"}),
    content_type="application/json",
)
check("★★ 能生成邀请", r.status_code, 201)
new_inv = r.json().get("data", {})
check("★★ 返回里带 token（★ 管理员本来就要把它发出去）", bool(new_inv.get("token")), True)
check("★ 与 max_uses 一致", new_inv.get("max_uses"), 1)

# ★★★ 非管理员必须被拒 —— ★ 这条是 `B171` 的**核心安全断言**：
#   ⚠★ 前端"藏起管理按钮"【不等于】安全，★ **真正的拦截在后端 `@staff_only`** ⚠
#   ⚠★ 注意两种情形**不是一回事**，别混：
#     · ★ **已登录但非管理员** ⇒ **403**（★ 后端认出你了，只是不给你这个权限）
#     · ★ **匿名**（没带 token）⇒ **401**（★ 后端根本不知道你是谁）
user_raw, _ = web_auth.issue_token(u1)
check(
    "★★★ 已登录但非管理员 ⇒ 403（★ 前端藏按钮 ≠ 安全）",
    Client(HTTP_AUTHORIZATION=f"Bearer {user_raw}").get("/api/invites/").status_code,
    403,
)
check("★ 匿名 ⇒ 401（★ 与 403 不是一回事）", c.get("/api/invites/").status_code, 401)

# ===========================================================================
# 复位开关（★ 让脚本可重复跑、不影响别的冒烟）
# ===========================================================================
_set("registration_open", False)
_set("invite_required", True)
_set("login_open", True)

print()
print("=" * 80)
if FAILED:
    print(f"❌ 失败 {len(FAILED)} 项：")
    for f in FAILED:
        print(f"   · {f}")
else:
    print("★★★★★ 全部通过（注册 / 登录 / 邀请码 / 门禁语义都成立）")
print("=" * 80)
