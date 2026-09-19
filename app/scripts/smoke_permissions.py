"""Astrolabe · 冒烟：权限地基（能力表 · 参数中心 · 审计）

★ 依据 `docs/README.md` 写入纪律 3：**测试脚本留在仓库内**（❌ 不落 /tmp）。

用法（在容器里）：
    docker compose exec -T web python manage.py shell < /app/scripts/smoke_permissions.py

★★ 本脚本用 `manage.py shell` 的 stdin 执行 —— ⚠ 不用 `python -c`，
   因为内嵌引号会被 shell 吃掉（★ 这个坑真实踩过一次）。
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from core import appsettings
from core.capabilities import (
    CAP_ADMIN_SETTINGS,
    CAP_ANALYSIS_DEEP,
    CAP_PROJECT_PUBLISH_ANY,
    CAP_PROJECT_REVIEW,
    CAP_READ_PUBLIC,
    CAP_UGC_WRITE,
    can,
    tier_name,
)
from core.models import AuditLog, UserProfile

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<52} = {got!r}")


# ===========================================================================
print("=" * 78)
print("① 参数中心默认值（★ 一期口径）")
print("=" * 78)
s = appsettings.all_settings()
check("paused（整站停服）", s["paused"], False)
check("registration_open（★ 一期应为 False = 邀请制）", s["registration_open"], False)
check("login_open（★ 只拦新登录）", s["login_open"], True)
check("invite_required", s["invite_required"], True)
check("license_require_file（★ 现在关，B143）", s["license_require_file"], False)
check("quota.free.project_max", s["quota.free"]["project_max"], 3)
check("quota.vip.project_max", s["quota.vip"]["project_max"], 20)
check("quota.vip.queue_priority（★ VIP 先出图）", s["quota.vip"]["queue_priority"], 10)

# ===========================================================================
print()
print("=" * 78)
print("② 能力判定 —— ★ 三条正交线（登录态 / 职权 / 订阅）")
print("=" * 78)
U = get_user_model()

# ★★ 用真正的 AnonymousUser（⚠ 不是 `U()` —— 见下）
guest = AnonymousUser()
check("游客 · read.public（★ 能完整地读）", can(guest, CAP_READ_PUBLIC), True)
check("游客 · ugc.write（★ 不能写）", can(guest, CAP_UGC_WRITE), False)
check("游客 · admin.settings", can(guest, CAP_ADMIN_SETTINGS), False)
check("游客 · tier_name", tier_name(guest), "anonymous")

# --------------------------------------------------------------------------
# ★★★ B144：两个"半成品用户"必须被当作游客（⚠ 这是真实踩过的坑）
# --------------------------------------------------------------------------
unsaved = U(username="never_saved")
check("★ 未保存 User ⇒ 视为游客（ugc.write）", can(unsaved, CAP_UGC_WRITE), False)
check("★ 未保存 User ⇒ tier_name", tier_name(unsaved), "anonymous")

disabled, _ = U.objects.get_or_create(username="smoke_disabled")
disabled.is_active = False
disabled.save(update_fields=["is_active"])
check("★★ 停用账号 ⇒ 视为游客（ugc.write）", can(disabled, CAP_UGC_WRITE), False)
check("★★ 停用账号 ⇒ 连 read.public 也降为游客口径", can(disabled, CAP_READ_PUBLIC), True)
check("★★ 停用账号 ⇒ tier_name", tier_name(disabled), "anonymous")

u, _ = U.objects.get_or_create(username="smoke_user")
# ★★ 显式重置 —— ⚠ 本脚本必须**幂等**（可重复跑）：
#    ⚠ 上一轮会把 u 提成 superuser，不重置就会让下一轮从"超管"开始判
u.is_staff = False
u.is_superuser = False
u.is_active = True
u.save(update_fields=["is_staff", "is_superuser", "is_active"])
profile, _ = UserProfile.objects.get_or_create(user=u)
profile.tier = UserProfile.TIER_FREE
profile.save(update_fields=["tier"])
u.profile = profile
check("普通 · ugc.write", can(u, CAP_UGC_WRITE), True)
check("普通 · analysis.deep（★ 这是 VIP 的）", can(u, CAP_ANALYSIS_DEEP), False)
check("普通 · project.review（★ 这是 staff 的）", can(u, CAP_PROJECT_REVIEW), False)

profile.tier = UserProfile.TIER_VIP
profile.save()
check("VIP · ugc.write（★ VIP 是超集）", can(u, CAP_UGC_WRITE), True)
check("VIP · analysis.deep", can(u, CAP_ANALYSIS_DEEP), True)
check("VIP · project.review（★ VIP ❌ 不能管站）", can(u, CAP_PROJECT_REVIEW), False)
check("VIP · admin.settings（★ VIP ❌ 不能改参数）", can(u, CAP_ADMIN_SETTINGS), False)

u.is_staff = True
check("VIP+staff · project.review", can(u, CAP_PROJECT_REVIEW), True)
check("VIP+staff · admin.settings（★ staff ❌ 不能改参数）", can(u, CAP_ADMIN_SETTINGS), False)
check("VIP+staff · tier_name", tier_name(u), "staff")

u.is_superuser = True
check("超管 · admin.settings", can(u, CAP_ADMIN_SETTINGS), True)
check("超管 · project.publish.any（★ 特批）", can(u, CAP_PROJECT_PUBLISH_ANY), True)
check("超管 · ugc.write（★ 超管天然含 VIP 能力）", can(u, CAP_UGC_WRITE), True)

# ===========================================================================
print()
print("=" * 78)
print("③ 改参数会自动留审计（U2.5 纪律 1）")
print("=" * 78)
before = AuditLog.objects.count()
appsettings.set_value("registration_open", True, actor=u)
log = AuditLog.objects.order_by("-id").first()
check("审计条数 +1", AuditLog.objects.count(), before + 1)
check("action", log.action, "setting.change")
check("target_id", log.target_id, "registration_open")
check("detail.before", log.detail["before"], False)
check("detail.after", log.detail["after"], True)
check("能读回新值", appsettings.get("registration_open"), True)
appsettings.set_value("registration_open", False, actor=u)
check("恢复后能读回", appsettings.get("registration_open"), False)

# ===========================================================================
print()
print("=" * 78)
if FAILED:
    print(f"❌ 失败 {len(FAILED)} 项：")
    for f in FAILED:
        print(f"   - {f}")
else:
    print("✅ 全部通过")
print("=" * 78)
