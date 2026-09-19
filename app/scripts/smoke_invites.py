"""Astrolabe · 冒烟：邀请机制（`U4.7` / `U4.8`）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_invites.py"

★★★ 本脚本重点验证**三条最要命的**：

1. ★★★ **并发核销不能超发** —— 一次性邀请码被两个请求同时核销 ⇒ **只能成功 1 个**
   （★ 这是邀请制最典型的 bug；不做锁 ⇒ 邀请制**当场失效**）
2. ★★★ **核销与建号必须同生共死** —— 建号失败时，★ **邀请码不能被白白消耗掉**
3. ★★ **邀请不能产生 VIP** —— `U4.7` 规则 4（★ 结构与行为**双重**保证）
"""

import threading
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.utils import timezone as tz

from core import invites, submission
from core.models import Invite

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


U = get_user_model()
admin, _ = U.objects.get_or_create(username="smoke_i_admin")
admin.is_staff = True
# ★ 门禁类参数（`paused`）只有 superuser 能改（U2.5）——
#   ⚠ 脚本要测它，所以这里必须是真的 superuser（★ 这也顺带验证了那道保护确实生效）
admin.is_superuser = True
admin.save(update_fields=["is_staff", "is_superuser"])

# ★ 清掉上一次跑留下的数据（★ 只为让脚本可重复运行）
Invite.objects.filter(created_by=admin).delete()


def fresh_user(username):
    u, _ = U.objects.get_or_create(username=username)
    prof = submission.ensure_profile(u)
    prof.invited_by = None
    prof.tier = "free"
    prof.save(update_fields=["invited_by", "tier"])
    return u


# ===========================================================================
print("=" * 80)
print("① 创建（★ 默认值来自参数中心，❌ 不硬编码）")
print("=" * 80)
inv = invites.create_invite(admin, note="SMOKE 默认值")
check("★ 默认可用次数（AppSetting: invite.default_uses）", inv.max_uses, 1)
# ⚠ 用秒差比较而不是 `.days` —— ★ 后者会因微秒截断把「7 天差一点」算成 6 天
check("★ 默认有效期 ≈ 7 天（容差 60s）",
      abs((inv.expires_at - tz.now()).total_seconds() - 7 * 86400) < 60, True)
check("★★ token 长度（token_urlsafe(24) ⇒ 32 字符，★ 猜不到）", len(inv.token), 32)
check("★ 记录了邀请人（连带责任的起点）", inv.created_by_id, admin.pk)

inv_multi = invites.create_invite(admin, max_uses=3, valid_days=1, note="SMOKE 多次")
check("可指定 max_uses", inv_multi.max_uses, 3)
check("★ 另一个 token 不重复", inv_multi.token != inv.token, True)

# ===========================================================================
print()
print("=" * 80)
print("② 预检 check()（★ 注册流程第一步：先问「能用吗」）")
print("=" * 80)
c = invites.check(inv.token)
check("有效码 ⇒ ok", c.ok, True)
check("★ 空码 ⇒ 拒绝", invites.check("").ok, False)
check("★ 不存在的码 ⇒ 拒绝", invites.check("no-such-token").ok, False)

# ★★ 无效的有效期必须【报错】，❌ 不能静默变成"永不过期"（★ 冒烟抓出的 bug）
try:
    invites.create_invite(admin, valid_days=0, note="SMOKE 非法有效期")
    check("★★ valid_days=0 ⇒ 抛异常（不静默变「永不过期」）", "没有抛", "ValueError")
except ValueError:
    check("★★ valid_days=0 ⇒ 抛异常（不静默变「永不过期」）", "ValueError", "ValueError")

expired = invites.create_invite(admin, note="SMOKE 已过期")
expired.expires_at = tz.now() - timedelta(hours=1)
expired.save(update_fields=["expires_at"])
c = invites.check(expired.token)
check("★ 已过期 ⇒ 拒绝", c.ok, False)
check("★ 且说明了原因（含过期时间）", "过期" in c.message, True)

revoked = invites.create_invite(admin, note="SMOKE 已作废")
invites.revoke(revoked, by=admin)
c = invites.check(revoked.token)
check("★ 已作废 ⇒ 拒绝", c.ok, False)
check("★ 且说明了原因", "作废" in c.message, True)

# ===========================================================================
print()
print("=" * 80)
print("③ ★★★ 并发核销【不能超发】（★ 一次性邀请码被两个请求同时抢）")
print("=" * 80)
token = invites.create_invite(admin, max_uses=1, note="SMOKE 并发").token
u1 = fresh_user("smoke_i_race1")
u2 = fresh_user("smoke_i_race2")

results: dict[int, object] = {}
barrier = threading.Barrier(2)


def _race(i, user):
    try:
        barrier.wait(timeout=15)          # ★ 让两个线程【尽可能同时】冲进去
        results[i] = invites.redeem(token, user).ok
    except Exception as exc:              # noqa: BLE001
        results[i] = f"ERR:{type(exc).__name__}"
    finally:
        connections.close_all()           # ★ 只关本线程的连接


threads = [threading.Thread(target=_race, args=(1, u1)), threading.Thread(target=_race, args=(2, u2))]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=25)

ok_count = sum(1 for v in results.values() if v is True)
inv_row = Invite.objects.get(token=token)
print(f"     线程结果: {results}")
check("★★★ 两个线程同时核销 ⇒ 【只有一个成功】", ok_count, 1)
check("★★★ 且计数【没有超发】", inv_row.used_count, 1)

# ===========================================================================
print()
print("=" * 80)
print("④ ★ 连带责任：记录「谁邀请了谁」（U4.7 规则 3）")
print("=" * 80)
winner = inv_row.created_by_id
check("★ 邀请码记录了邀请人", winner, admin.pk)
who = invites.who_invited(u1) or invites.who_invited(u2)
check("★★ 能反查「这个账号是谁邀请进来的」", who["invited_by"], admin.username)
# ⚠ 断言用 >= 1 而不是 == 1 —— ★ 因为库里可能还有**上一次跑留下的**被邀请用户
check("★ 能看出邀请人一共拉了几个（>= 1）", who["invited_count"] >= 1, True)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★ 邀请【不产生 VIP】（U4.7 规则 4 · U1 铁律）")
print("=" * 80)
u3 = fresh_user("smoke_i_tier")
invites.redeem(invites.create_invite(admin, note="SMOKE tier").token, u3)
u3.refresh_from_db()
check("★★ 核销后 tier 仍是 free（❌ 不能靠邀请拿 VIP）", u3.profile.tier, "free")
check("★ Invite 模型【没有】tier 字段（★ 结构上就做不到）",
      hasattr(Invite, "tier"), False)

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★★ 同一账号不能核销两次")
print("=" * 80)
u3b = fresh_user("smoke_i_twice")     # ⚠ 必须是全新用户（u3 已在 ⑤ 用过了）
tok2 = invites.create_invite(admin, note="SMOKE 重复核销")
check("第一次核销 ⇒ 成功", invites.redeem(tok2.token, u3b).ok, True)
r = invites.redeem(tok2.token, u3b)
check("★ 同一账号再核销 ⇒ 拒绝", r.ok, False)
check("★ 且说明了原因", "已经通过邀请注册过" in r.message, True)

# ===========================================================================
print()
print("=" * 80)
print("⑦ ★★★ 核销与建号【同生共死】：建号失败 ⇒ 邀请码【不能被消耗】")
print("=" * 80)
tok3 = invites.create_invite(admin, note="SMOKE 回滚")
u4 = fresh_user("smoke_i_rollback")
try:
    with transaction.atomic():
        r = invites.redeem(tok3.token, u4)
        if not r.ok:
            raise RuntimeError(f"核销就失败了：{r.message}")
        raise RuntimeError("★ 模拟建号阶段崩了")
except RuntimeError:
    pass

tok3.refresh_from_db()
u4.refresh_from_db()
check("★★★ 外层事务回滚后 ⇒ 邀请码【没有被消耗】", tok3.used_count, 0)
check("★★★ 且用户【没有被记为被邀请】", u4.profile.invited_by_id, None)
check("★★ 所以这个码【还能正常用】（不会白白损失）", invites.redeem(tok3.token, u4).ok, True)

# ===========================================================================
print()
print("=" * 80)
print("⑧ ★★ 注册门禁（U4.6 三开关 —— ★★ U4.8「最容易漏的洞」的唯一入口）")
print("=" * 80)
from core import appsettings  # noqa: E402

g = invites.registration_gate()
print(f"     当前: allowed={g.allowed} invite_required={g.invite_required} "
      f"registration_open={g.registration_open}")
check("★ 默认（registration_open=False）⇒ 不允许注册", g.allowed, False)
check("★ 且说明了原因", "未开放注册" in g.message, True)

# ★★ 门禁类参数只有 superuser 能改（U2.5 纪律 1）—— ★ 顺带验证这道保护真的在
nobody = fresh_user("smoke_i_nobody")
try:
    appsettings.set_value("paused", True, actor=nobody)
    check("★★ 非 superuser 改 paused ⇒ 应被拒绝", "没有拒绝", "PermissionError")
except PermissionError:
    check("★★ 非 superuser 改 paused ⇒ 被拒绝（U2.5）", "PermissionError", "PermissionError")

appsettings.set_value("registration_open", True, actor=admin)
try:
    g = invites.registration_gate()
    check("★ 开注册 ⇒ 允许", g.allowed, True)
    check("★ 且要求邀请码（invite_required=True）", g.invite_required, True)

    # ★ 门禁收敛在【一处】 —— 无论注册表单还是 OAuth 回调，都问它
    appsettings.set_value("paused", True, actor=admin)
    try:
        g = invites.registration_gate()
        check("★★ paused（整站停服）优先级【高于】注册开关", g.paused, True)
        check("★★ 所以停服时不允许注册", g.allowed, False)
    finally:
        appsettings.set_value("paused", False, actor=admin)
finally:
    appsettings.set_value("registration_open", False, actor=admin)

# ===========================================================================
print()
print("=" * 80)
print("⑨ 作废 / 列表 / 用尽")
print("=" * 80)
inv4 = invites.create_invite(admin, max_uses=2, note="SMOKE 用尽")
u5 = fresh_user("smoke_i_exhaust1")
u6 = fresh_user("smoke_i_exhaust2")
check("第 1 次核销 ⇒ 成功", invites.redeem(inv4.token, u5).ok, True)
check("第 2 次核销 ⇒ 成功（max_uses=2）", invites.redeem(inv4.token, u6).ok, True)
c = invites.check(inv4.token)
check("★★ 用尽后 ⇒ 拒绝", c.ok, False)
check("★ 且说明了原因", "已经被用过" in c.message, True)

rows = invites.list_invites(by=admin, limit=100)
check("★ 列表能查到", len(rows) > 0, True)
check("★ 列表里每项都带 usable 标记", all("usable" in r for r in rows), True)

# ===========================================================================
print()
print("=" * 80)
if FAILED:
    print(f"❌ 失败 {len(FAILED)} 项：")
    for f in FAILED:
        print(f"   - {f}")
else:
    print("✅ 全部通过")
print("=" * 80)
