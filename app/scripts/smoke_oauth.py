"""Astrolabe · 冒烟：OAuth（`U4` · `U4.8` · `U3.1`）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_oauth.py"

★★★ 本脚本重点验证**四件最要命的事**：

1. ★★★ **`U4.8` 的洞** —— 「从 GitHub 登录」这条路**也必须过邀请校验**，
   ⚠★ 否则**任何人都能靠"用 OAuth 登录一次"绕过邀请制**
2. ★★★ **老用户不能被一起关掉** —— 邀请期 `registration_open=false` 时，
   ★ **已绑定过的账号必须还能登录**（⚠ 否则那是 `paused`，不是"关注册"）
3. ★★ **`U4.8` 两条纪律** —— 邀请码「**校验通过前不消耗**」+「**核销与建号同事务**」
4. ★★ **Gate 0 归属校验** —— `U3.1` 四步里的第 ②③ 步（★ 比数字 ID + 拒 Fork + 拒组织）

⚠ 全程**不连真实 GitHub** —— 用一个假 fetcher（★ 测试才快、才确定）。
"""

from datetime import timedelta

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.utils import timezone as tz

from core import appsettings, invites, oauth
from core.models import OAuthIdentity, OAuthState

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


U = get_user_model()

# ★ 直接用假凭据跑（⚠ 不碰真实第三方）
dj_settings.ASTROLABE_OAUTH = {
    "github": {"client_id": "cid-test", "client_secret": "sec-test"},
    "gitee": {"client_id": "cid-test", "client_secret": "sec-test"},
}
dj_settings.ASTROLABE_BASE_URL = "http://test.local"


class FakeFetcher:
    """★ 假的第三方（★ 可配置成各种失败形态）。"""

    def __init__(self, *, profile=None, repo=None, token_ok=True):
        self.profile = profile if profile is not None else {"id": 4242, "login": "alice", "avatar_url": "http://a/x.png"}
        self.repo = repo if repo is not None else {}
        self.token_ok = token_ok

    def post_form(self, url, data, *, headers=None):
        if not self.token_ok:
            return {"error": "bad_verification_code", "error_description": "授权码无效"}
        return {"access_token": "gho_FAKE_TOKEN"}

    def get_json(self, url, *, headers=None):
        if url.endswith("/user"):
            return self.profile
        return self.repo


admin, _ = U.objects.get_or_create(username="smoke_o_admin")
admin.is_staff = True
admin.is_superuser = True
admin.save(update_fields=["is_staff", "is_superuser"])

# ★ 清掉上一次跑留下的数据（⚠ 只为让脚本【可重复运行】）
invites.Invite.objects.filter(created_by=admin).delete()
for nm in ("alice", "alice_2", "alice_3", "bob", "carol"):
    U.objects.filter(username=nm).delete()

# ★ dummy 要能被【反复】用作"邀请码消耗者" ⇒ 每次跑前清掉它的 invited_by
DummyUser, _ = U.objects.get_or_create(username="smoke_o_dummy")
DummyUser.set_unusable_password()
DummyUser.save()
from core import submission  # noqa: E402

_dp = submission.ensure_profile(DummyUser)
_dp.invited_by = None
_dp.save(update_fields=["invited_by"])

# ★ 固定三个开关，测完恢复
_orig = {k: appsettings.get(k) for k in ("registration_open", "invite_required", "login_open", "paused")}
print(f"   （原标题：registration_open={_orig['registration_open']} "
      f"invite_required={_orig['invite_required']} login_open={_orig['login_open']}）")


def set_gate(*, registration_open=True, invite_required=True, login_open=True):
    appsettings.set_value("registration_open", registration_open, actor=admin)
    appsettings.set_value("invite_required", invite_required, actor=admin)
    appsettings.set_value("login_open", login_open, actor=admin)


# ===========================================================================
print("=" * 80)
print("① 发起授权：state 落库 + 授权 URL 正确（★ 只申请最小权限）")
print("=" * 80)
st = oauth.start("github", action=OAuthState.ACTION_LOGIN, invite_token="tok-abc", next_url="/me")
check("★ 授权 URL 指向 GitHub", st.url.startswith("https://github.com/login/oauth/authorize?"), True)
check("★★ scope 只有 read:user（❌ 不申请任何读私有仓库的权限）", "scope=read%3Auser" in st.url, True)
check("★ client_id 已带上", "client_id=cid-test" in st.url, True)
check("★★ state 落库（★ 因为本平台不保存 token，意图必须塞进 state）",
      OAuthState.objects.filter(state=st.state.state).exists(), True)
check("★ state 里带上了邀请码（U4.8 流程第 ② 步）", st.state.invite_token, "tok-abc")
check("★ 有有效期（⚠ 不是永久门票）", (st.state.expires_at - tz.now()).total_seconds() > 0, True)

check("★ 未配置的 provider 不会出现在登录页上",
      [p["key"] for p in oauth.enabled_providers()], ["github", "gitee"])

# ===========================================================================
print()
print("=" * 80)
print("② ★★★ U4.8 的洞：『从 OAuth 登录』这条路【也必须过邀请校验】")
print("=" * 80)
set_gate(registration_open=False, invite_required=True, login_open=True)

# ---- 2a. registration_open=False ⇒ 新用户一律拒绝 ----
st = oauth.start("github", invite_token="")
r = oauth.callback("github", code="c1", state=st.state.state, fetcher=FakeFetcher())
check("★★ registration_open=False ⇒ 新用户被拒", r.ok, False)
check("★★ message 是【可读原因】（U4.8 纪律 3）", "未开放注册" in r.message, True)
check("★★ 而且【没有建账号】", U.objects.filter(username="alice").exists(), False)

# ---- 2b. 开了注册 + 邀请制 ⇒ 没带邀请码也不行 ----
set_gate(registration_open=True, invite_required=True, login_open=True)
st = oauth.start("github", invite_token="")
r = oauth.callback("github", code="c2", state=st.state.state, fetcher=FakeFetcher())
check("★★ 邀请制下没带邀请码 ⇒ 拒绝", r.ok, False)
check("★ 且说明是邀请制", "邀请制" in r.message, True)
check("★★ 仍然没有建账号（★ 洞被堵住）", U.objects.filter(username="alice").exists(), False)

# ---- 2c. 带上有效邀请码 ⇒ 注册成功 ----
inv = invites.create_invite(admin, note="SMOKE OAuth 注册")
st = oauth.start("github", invite_token=inv.token)
r = oauth.callback("github", code="c3", state=st.state.state, fetcher=FakeFetcher())
check("★★ 有效邀请码 ⇒ 注册成功", r.ok, True)
check("★ action = register", r.action, "register")
check("★ 建出了本站账号", r.user.username if r.user else None, "alice")
check("★★ 账号【没有可用密码】（U4.2：本站没有密码登录）", r.user.has_usable_password(), False)
check("★★ 绑定了第三方身份", r.identity.provider_user_id, "4242")
check("★★ 记下了 invited_by（U4.7 规则 3 连带责任）", r.user.profile.invited_by_id, admin.pk)
inv.refresh_from_db()
check("★★ 邀请码被核销了", inv.used_count, 1)
check("★★ 新用户的 tier 是 free（❌ 邀请不产生 VIP）", r.user.profile.tier, "free")

# ===========================================================================
print()
print("=" * 80)
print("③ ★★★ 老用户不能被一起关掉（邀请期 registration_open=False 仍必须能登录）")
print("=" * 80)
set_gate(registration_open=False, invite_required=True, login_open=True)
st = oauth.start("github")
r = oauth.callback("github", code="c4", state=st.state.state, fetcher=FakeFetcher())
check("★★★ 已绑定的账号 ⇒ 关注册期间【照样能登录】", r.ok, True)
check("★★ action = login（不是 register）", r.action, "login")
check("★ 认出了是同一个账号", r.user.pk, U.objects.get(username="alice").pk)

# ---- login_open=False ⇒ 连老用户也拦（★ 但它仍【不踢已登录的人】）----
set_gate(registration_open=False, invite_required=True, login_open=False)
st = oauth.start("github")
r = oauth.callback("github", code="c5", state=st.state.state, fetcher=FakeFetcher())
check("★ login_open=False ⇒ 新登录被拦", r.ok, False)
check("★ 且说明原因", "暂停登录" in r.message, True)

# ===========================================================================
print()
print("=" * 80)
print("④ ★★★ U4.8 纪律 1：邀请码「校验通过前【不消耗】」")
print("=" * 80)
set_gate(registration_open=True, invite_required=True, login_open=True)
inv2 = invites.create_invite(admin, note="SMOKE 失败不消耗")
# ★ 让第三方换 token 就失败（模拟用户授权页点了取消 / 网络断了）
st = oauth.start("github", invite_token=inv2.token)
r = oauth.callback("github", code="c6", state=st.state.state, fetcher=FakeFetcher(token_ok=False))
check("★ 换 token 失败 ⇒ 回调失败", r.ok, False)
inv2.refresh_from_db()
check("★★★ 但邀请码【一点没被消耗】（纪律 1）", inv2.used_count, 0)
check("★★ 而且该码【还能正常用】", invites.check(inv2.token).ok, True)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★★ U4.8 纪律 2：核销与建号【同生共死】")
print("=" * 80)
from unittest import mock  # noqa: E402

# ★ 造一个【已用尽】的邀请码
inv3 = invites.create_invite(admin, max_uses=1, note="SMOKE 已用尽")
invites.redeem(inv3.token, DummyUser)
inv3.refresh_from_db()
check("前提：这个码已经用尽", inv3.used_count, 1)

# ★★ 关键：必须【显式模拟那个竞态窗口】——
#    「预检时还有额度、核销时已被别人抢走」。
#    ⚠ 直接用已用尽的码测不出这一条：`check()` 会**提前**拦住，
#      那就根本走不到「建号 + 核销」的事务里，纪律 2 也就没被验证到。
st = oauth.start("github", invite_token=inv3.token)
fake_ok = invites.InviteCheck(ok=True, invite=inv3)     # ← 谎称预检通过（★ 模拟竞态）
with mock.patch.object(invites, "check", return_value=fake_ok):
    r = oauth.callback(
        "github", code="c7", state=st.state.state,
        # ⚠ 必须用一个【没绑定过】的第三方 id，否则走的是"登录"而不是"注册"
        fetcher=FakeFetcher(profile={"id": 55555, "login": "carol"}),
    )
check("★ 核销失败 ⇒ 注册整体失败", r.ok, False)
check("★★★ 而且【账号被一起回滚了】（不留半个账号）",
      U.objects.filter(username="carol").exists(), False)
check("★★★ 也没有孤立的第三方身份（否则会变成「幽灵绑定」）",
      OAuthIdentity.objects.filter(provider_user_id="55555").exists(), False)
check("★ 原有账号没受影响", U.objects.filter(username="alice").count(), 1)

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★★ state 一次性（防重放）/ 过期 / provider 不匹配")
print("=" * 80)
set_gate(registration_open=True, invite_required=False, login_open=True)
st = oauth.start("gitee")
r1 = oauth.callback("gitee", code="c8", state=st.state.state,
                    fetcher=FakeFetcher(profile={"id": 777, "login": "bob"}))
check("首次回调 ⇒ 成功", r1.ok, True)
r2 = oauth.callback("gitee", code="c8", state=st.state.state,
                    fetcher=FakeFetcher(profile={"id": 777, "login": "bob"}))
check("★★ 同一个 state 再回调一次 ⇒ 被拒（★ 防重放）", r2.ok, False)
# ★ 提示必须说【真正的原因】—— ⚠ 含糊的"无效或已过期"会让用户以为服务端坏了、反复重试
check("★ 且说清是「已经用过」而不是「无效」", "已经用过" in r2.message, True)

st2 = oauth.start("gitee")
r3 = oauth.callback("github", code="c9", state=st2.state.state, fetcher=FakeFetcher())
check("★ state 与 provider 不匹配 ⇒ 被拒", r3.ok, False)

st3 = oauth.start("gitee")
OAuthState.objects.filter(state=st3.state.state).update(expires_at=tz.now() - timedelta(minutes=1))
r4 = oauth.callback("gitee", code="c10", state=st3.state.state, fetcher=FakeFetcher())
check("★ state 过期 ⇒ 被拒", r4.ok, False)
check("★ 且说明「请重新发起」", "重新发起" in r4.message, True)

check("★ 清理过期 state 的接口存在", oauth.purge_expired_states() >= 1, True)

# ===========================================================================
print()
print("=" * 80)
print("⑦ ★★ 用户名去重（⚠ 不同 provider 可能撞名）")
print("=" * 80)
U.objects.filter(username__startswith="alice").exclude(username="alice").delete()
# ★ 造一个新的 GitHub 身份，但 login 也叫 alice
st = oauth.start("github", invite_token=invites.create_invite(admin, note="SMOKE 重名").token)
r = oauth.callback("github", code="c11", state=st.state.state,
                   fetcher=FakeFetcher(profile={"id": 999, "login": "alice"}))
check("★★ 同名 login 仍能注册（★ 自动加后缀）", r.ok, True)
check("★ 落到了 alice_2", r.user.username, "alice_2")

# ===========================================================================
print()
print("=" * 80)
print("⑧ ★★★ Gate 0 归属校验（U3.1 第 ②③ 步）—— ★ 四类判据")
print("=" * 80)
TOKEN = "gho_FAKE_TOKEN"


def repo(**kw):
    base = {"id": 1, "full_name": "alice/demo",
            "owner": {"id": 4242, "login": "alice", "type": "User"}, "fork": False}
    base.update(kw)
    return base


v = oauth.verify_repo_ownership("github", TOKEN, repo_full_name="alice/demo",
                                provider_user_id="4242", fetcher=FakeFetcher(repo=repo()))
check("★ 自己的仓库 ⇒ 通过", v.ok, True)

v = oauth.verify_repo_ownership("github", TOKEN, repo_full_name="alice/demo",
                                provider_user_id="4242",
                                fetcher=FakeFetcher(repo=repo(owner={"id": 111, "login": "someone", "type": "User"})))
check("★★ 别人的仓库 ⇒ 拒绝", v.ok, False)
check("★ 且点出「这不是你的账号」", "不是你的账号" in v.message, True)

v = oauth.verify_repo_ownership("github", TOKEN, repo_full_name="alice/demo",
                                provider_user_id="4242",
                                fetcher=FakeFetcher(repo=repo(fork=True, parent={"full_name": "up/demo"})))
check("★★ Fork ⇒ 拒绝（U3.2 坑 3）", v.ok, False)
check("★ 且指向原作者仓库", "up/demo" in v.message, True)

v = oauth.verify_repo_ownership("github", TOKEN, repo_full_name="acme/demo",
                                provider_user_id="4242",
                                fetcher=FakeFetcher(repo=repo(owner={"id": 4242, "login": "acme", "type": "Organization"})))
check("★★ 组织仓库 ⇒ 拒绝（U3.2 坑 2）", v.ok, False)

v = oauth.verify_repo_ownership("github", TOKEN, repo_full_name="alice/demo",
                                provider_user_id="4242", fetcher=FakeFetcher(repo={}))
check("★★ 拉不到 ⇒ 拒绝（❌ 绝不「拉不到就当通过」）", v.ok, False)

v = oauth.verify_repo_ownership("github", TOKEN, repo_full_name="badformat",
                                provider_user_id="4242", fetcher=FakeFetcher())
check("★ 仓库格式不对 ⇒ 拒绝", v.ok, False)

# ★★★ 最关键的一条：用户名改了，但数字 ID 没变 ⇒ 归属【仍然成立】
v = oauth.verify_repo_ownership("github", TOKEN, repo_full_name="alice/demo",
                                provider_user_id="4242",
                                fetcher=FakeFetcher(repo=repo(owner={"id": 4242, "login": "alice-renamed", "type": "User"})))
check("★★★ 用户改了名但 id 没变 ⇒ 归属【仍然通过】（U3.2 坑 1）", v.ok, True)

# ===========================================================================
print()
print("=" * 80)
print("⑨ ★★ 不保存 access_token（★ 结构上就做不到）")
print("=" * 80)
check("★★ OAuthIdentity【没有】token 字段",
      any(f in ("access_token", "token", "refresh_token") for f in
          [x.name for x in OAuthIdentity._meta.get_fields()]), False)
check("★★ 但回调【返回了】token（★ 供发布流程当场校验、用完即弃）", bool(r1.access_token), True)

# ===========================================================================
# 恢复开关
for k, v in _orig.items():
    appsettings.set_value(k, v, actor=admin)

print()
print("=" * 80)
if FAILED:
    print(f"❌ 失败 {len(FAILED)} 项：")
    for f in FAILED:
        print(f"   - {f}")
else:
    print("✅ 全部通过")
print("=" * 80)
