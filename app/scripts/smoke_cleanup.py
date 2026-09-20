"""Astrolabe · 冒烟：两个定时清理（`B161`）

★ 跑法（在 `app/deploy` 下）：

    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_cleanup.py"

★ 本冒烟要证明的是 **`--days` 宽限期真的按"失效时间"算**，
  而不是只看 `expires_at` —— ⚠ 这是 `--revoke-user` 之后最容易漏的一类记录：

    ★ 一个 token 被【主动撤销】时，它的 `expires_at` **可能还在未来** ⚠
    ★★ 若清理只过滤 `expires_at`，这些行【永远删不掉】⚠
"""

import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from io import StringIO

from core.models import ApiToken, OAuthState

PASSED, FAILED = [], []


def check(label, got, want):
    ok = got == want
    (PASSED if ok else FAILED).append(label)
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


def check_true(label, cond):
    check(label, bool(cond), True)


def run(cmd, **kw):
    """★ 调命令并收集它的 stdout（⚠ 不真去 stdin 等交互）。"""
    out = StringIO()
    call_command(cmd, stdout=out, stderr=StringIO(), **kw)
    return out.getvalue()


NOW = timezone.now()
User = get_user_model()
U = User.objects.create(username=f"smoke_cl_{secrets.token_hex(4)}")

print("=" * 84)
print("① ★ 构造四类令牌 —— 每类的期望都不同（⚠ 这才是本冒烟的重点）")
print("=" * 84)

# ① 有效：还早
t_valid = ApiToken.objects.create(
    user=U, token_hash=secrets.token_hex(32), prefix="valid001",
    expires_at=NOW + timedelta(days=30),
)
# ② 刚过期（1 天前）—— ⚠ 落在 7 天宽限期内 ⇒ ★ 不该删
t_fresh = ApiToken.objects.create(
    user=U, token_hash=secrets.token_hex(32), prefix="fresh002",
    expires_at=NOW - timedelta(days=1),
)
# ③ 过期很久（30 天前）—— ★ 该删
t_old = ApiToken.objects.create(
    user=U, token_hash=secrets.token_hex(32), prefix="old00003",
    expires_at=NOW - timedelta(days=30),
)
# ④ ★★ 已撤销、但 expires_at 还在【未来】（15 天前撤销）—— ★ 这才是最容易漏的
t_revoked = ApiToken.objects.create(
    user=U, token_hash=secrets.token_hex(32), prefix="revoked04",
    expires_at=NOW + timedelta(days=90),
    revoked_at=NOW - timedelta(days=15),
)

check("四类令牌已建好", ApiToken.objects.filter(user=U).count(), 4)
check("★ ③ 已过期 30 天（应被删）", ApiToken.objects.filter(pk=t_old.pk).exists(), True)
check("★★ ④ 已撤销 15 天、但【未过期】（应被删）", ApiToken.objects.filter(pk=t_revoked.pk).exists(), True)

print()
print("=" * 84)
print("② ★ dry-run：必须【一条都不动】")
print("=" * 84)

before = ApiToken.objects.filter(user=U).count()
out = run("cleanup_api_tokens", days=7, dry_run=True)
check("★ dry-run 后有报告", "dry-run" in out, True)
check("★ 且令牌数没变（⚠ 一条都没删）", ApiToken.objects.filter(user=U).count(), before)

print()
print("=" * 84)
print("③ ★★★ 真清理：只删「失效已满 7 天」的两条")
print("=" * 84)

out = run("cleanup_api_tokens", days=7)
print(f"     命令输出: {out.strip()}")

check("★ ① 有效令牌【还在】", ApiToken.objects.filter(pk=t_valid.pk).exists(), True)
check("★★ ② 刚过期 1 天 ⇒ 【保留】（★ 宽限期生效）", ApiToken.objects.filter(pk=t_fresh.pk).exists(), True)
check("★ ③ 过期 30 天 ⇒ 【已删】", ApiToken.objects.filter(pk=t_old.pk).exists(), False)
check("★★★ ④ 已撤销 15 天、未过期 ⇒ 【也删了】（★ 最容易漏的一类）", ApiToken.objects.filter(pk=t_revoked.pk).exists(), False)
check("⇒ 该项目下剩 2 条", ApiToken.objects.filter(user=U).count(), 2)

print()
print("=" * 84)
print("④ ★ 宽限期：--days 0 = 立刻可删（★ 证明 N 真的在起作用）")
print("=" * 84)

out = run("cleanup_api_tokens", days=0)
check("★ --days 0 ⇒ 刚过期那条被删", ApiToken.objects.filter(pk=t_fresh.pk).exists(), False)
check("⇒ 只剩有效的 1 条", ApiToken.objects.filter(user=U).count(), 1)

print()
print("=" * 84)
print("⑤ ★★ --revoke-user：是【撤销】不是删除（⚠ 登出全部设备）")
print("=" * 84)

ApiToken.objects.create(user=U, token_hash=secrets.token_hex(32), prefix="extra005",
                        expires_at=NOW + timedelta(days=30))
check("★ 撤销前有 2 个有效令牌", ApiToken.objects.filter(user=U, revoked_at__isnull=True).count(), 2)

out = run("cleanup_api_tokens", revoke_user=U.username)
print(f"     命令输出: {out.strip()}")

check("★★ 令牌【行还在】（❌ 没被删）", ApiToken.objects.filter(user=U).count(), 2)
check("★★★ 但全部已撤销（⇒ 登出全部设备）", ApiToken.objects.filter(user=U, revoked_at__isnull=True).count(), 0)
check("★ ★ 且记下了撤销时间（可审计）",
      ApiToken.objects.filter(user=U, revoked_at__isnull=False).count(), 2)
check("⇒ is_valid 现在一律为 False", all(not t.is_valid() for t in ApiToken.objects.filter(user=U)), True)

print()
print("=" * 84)
print("⑥ ★ 撤销后【仍不会被立刻清理】（★ 撤销时间才刚开始算）")
print("=" * 84)

out = run("cleanup_api_tokens", days=7)
check("★ 撤销才几秒 ⇒ 两条都还在（⚠ 宽限期对撤销同样生效）",
      ApiToken.objects.filter(user=U).count(), 2)

print()
print("=" * 84)
print("⑦ ★ 不存在的用户 ⇒ 必须报错（❌ 不静默'当成功'）")
print("=" * 84)

try:
    run("cleanup_api_tokens", revoke_user="no_such_user_xyz")
    check("★ 报错", False, True)
except Exception as exc:
    check("★★ 抛异常且说明原因", "no_such_user_xyz" in str(exc), True)

print()
print("=" * 84)
print("⑧ ★ OAuthState：只清过期的，没过期的一律不动")
print("=" * 84)

s_old = OAuthState.objects.create(
    state=secrets.token_hex(16), provider="github",
    expires_at=NOW - timedelta(hours=2),
)
s_new = OAuthState.objects.create(
    state=secrets.token_hex(16), provider="github",
    expires_at=NOW + timedelta(hours=2),
)

out = run("purge_expired_states", dry_run=True)
check("★ dry-run 有报告", "dry-run" in out, True)
check("★ 且一条都没删", OAuthState.objects.filter(pk=s_old.pk).exists(), True)

out = run("purge_expired_states")
print(f"     命令输出: {out.strip()}")

check("★ 过期的 ⇒ 已清", OAuthState.objects.filter(pk=s_old.pk).exists(), False)
check("★★ 未过期的 ⇒ 保留", OAuthState.objects.filter(pk=s_new.pk).exists(), True)

print()
print("=" * 84)
print("⑨ ★ --list 能看清分布")
print("=" * 84)

out = run("cleanup_api_tokens", list=True)
check("★ 有表头", "状态" in out, True)
check("★ 报告了已撤销数", "已撤销" in out, True)

# ---------------------------------------------------------------- 清理
ApiToken.objects.filter(user=U).delete()
OAuthState.objects.filter(pk=s_new.pk).delete()
U.delete()

print()
print("=" * 84)
print(f"✅ 通过 {len(PASSED)} 项" + (f"   ❌ 失败 {len(FAILED)} 项" if FAILED else "，全部通过"))
if FAILED:
    for f in FAILED:
        print(f"   ❌ {f}")
print("=" * 84)
