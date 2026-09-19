"""Astrolabe · 冒烟：上传限额 + 驳回原因（`U3.8` / `U3.9`）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_quota.py"

★★ 本脚本重点验证**五件容易做错的事**：

1. ★★ **删掉项目不能绕过限额** —— 若流水是 `CASCADE`，删项目就抹掉了计数
2. ★★ **自动放行也必须计次** —— 否则恶意刷的人只要用宽松许可的项目刷就行
3. ★★ **驳回必须写理由** —— 不写就不许驳回（用户明确要求"要能看见原因"）
4. ★★ **退还额度必须真的生效** —— 否则 `quota_refunded` 只是个安慰性字段
5. ★★ **管理员给个人放宽必须生效** —— 用户原话「真有人这么厉害，也得给其创造空间」
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone as tz

from core import quota, submission
from core.licensing import evaluate
from core.models import Project, ProjectReview

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<56} = {got!r}")


U = get_user_model()
# ★ 宽松许可 ⇒ 自动放行
MIT = {"LICENSE": "MIT License\n\nPermission is hereby granted, free of charge, to any person..."}
# ★ 传染性 ⇒ 进人工审核
GPL = {"COPYING": "GNU GENERAL PUBLIC LICENSE\n  Version 3, 29 June 2007"}

admin, _ = U.objects.get_or_create(username="smoke_q_admin")
admin.is_staff = True
admin.save(update_fields=["is_staff"])


def fresh(username, *, tier="free", override=None):
    """★ 造一个干净的测试用户（清空流水 + 项目 —— ⚠ 只为让脚本可重复跑）。"""
    u, _ = U.objects.get_or_create(username=username)
    ProjectReview.objects.filter(submitted_by=u).delete()
    Project.objects.filter(owner=u).delete()
    pf = submission.ensure_profile(u)
    pf.tier = tier
    pf.quota_override = override or {}
    pf.save(update_fields=["tier", "quota_override"])
    return u


def submit(u, name, *, texts=None, repo="", at=None, require_file=None):
    p = Project.objects.create(owner=u, name=name, repo_url=repo)
    lv = evaluate(texts=texts if texts is not None else MIT, require_file=require_file)
    return p, submission.submit_project(p, u, license_verdict=lv, at=at)


# ===========================================================================
print("=" * 80)
print("① ★★ 删掉项目【不能】绕过限额（→ 检验流水的 SET_NULL 设计）")
print("=" * 80)
u = fresh("smoke_q_del")
for i in range(3):
    _, r = submit(u, f"proj{i}")
    check(f"第 {i + 1} 次提交（free 日限 3）", r.accepted, True)

_, r = submit(u, "proj3")
check("第 4 次 ⇒ 被拦", r.accepted, False)
check("拦截原因", r.quota.reason_code, quota.CODE_DAILY)
check("★ 提示里有「下次什么时候能来」", "之后再试" in r.user_message, True)

Project.objects.filter(owner=u).delete()
_, r = submit(u, "proj_after_delete")
check("★★ 删光项目后再提交 ⇒ 【仍然被拦】", r.accepted, False)
check("★★ 原因不变（证明计数来自流水，不是 Project 表）", r.quota.reason_code, quota.CODE_DAILY)

# ===========================================================================
print()
print("=" * 80)
print("② ★★ 自动放行【也必须计次】（否则刷子用宽松许可就能无限刷）")
print("=" * 80)
u = fresh("smoke_q_auto")
all_auto = all(submit(u, f"auto{i}")[1].auto_allowed for i in range(3))
check("★ 这三次都是「自动放行」", all_auto, True)
_, r = submit(u, "auto3")
check("★★ 自动放行满 3 次后 ⇒ 同样被拦", r.accepted, False)
check("流水 3 条（★ 自动放行也有流水）",
      ProjectReview.objects.filter(submitted_by=u).count(), 3)
check("★ 这几条都是 auto_decided",
      ProjectReview.objects.filter(submitted_by=u, auto_decided=True).count(), 3)

# ===========================================================================
print()
print("=" * 80)
print("③ ★★ 驳回必须写理由 + 用户能看见原因（U3.8）")
print("=" * 80)
u = fresh("smoke_q_reject")
p, r = submit(u, "gpl_proj", texts=GPL)
check("GPL ⇒ 进人工审核", r.needs_review, True)
rv = r.review

try:
    rv.reject(by=admin, note="   ")
    check("★ 空理由驳回 ⇒ 抛异常", "没有抛", "ValueError")
except ValueError:
    check("★ 空理由驳回 ⇒ 抛异常", "ValueError", "ValueError")

rv.reject(by=admin, note="这个项目的版权归属不清晰，请补充来源说明后重新提交。", refund_quota=True)
rv.refresh_from_db()
check("驳回后 decision", rv.decision, ProjectReview.DECISION_REJECTED)
check("★ 理由已存下来", "版权归属不清晰" in rv.decision_note, True)
check("★ 决定人已记录（可追责）", rv.decided_by_id, admin.pk)
check("★ 标记为「人工判定」而非自动", rv.auto_decided, False)

subs = submission.my_submissions(u)
check("★ 用户能查到自己的提交", len(subs), 1)
check("★★ 用户能看到【驳回原因】", subs[0]["reject_reason"], rv.decision_note)
check("★ 状态是给用户看的中文说法", subs[0]["status_text"], "未通过")
check("★★ 用户【看不到】内部证据 evidence", "evidence" in subs[0], False)
check("★★ 用户【看不到】给管理员的建议 suggestion", "suggestion" in subs[0], False)

# ===========================================================================
print()
print("=" * 80)
print("④ ★★ 退还额度必须【真的生效】")
print("=" * 80)
u = fresh("smoke_q_refund")
for i in range(3):
    submit(u, f"rf{i}")
_, r = submit(u, "rf3")
check("满 3 次 ⇒ 被拦", r.accepted, False)

rv = ProjectReview.objects.filter(submitted_by=u).order_by("created_at").first()
rv.reject(by=admin, note="误判，已人工确认", refund_quota=True)
check("★★ 退还后计数回落到 2",
      quota.count_submissions(u, since=quota.day_start()), 2)
_, r = submit(u, "rf_again")
check("★★ 退还的额度【真的能用了】", r.accepted, True)
_, r = submit(u, "rf_again2")
check("再用一次 ⇒ 又被拦（额度没有被超人化）", r.accepted, False)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★★ 管理员给个人放宽（「真有人这么厉害，也得给其创造空间」）")
print("=" * 80)
u = fresh("smoke_q_vip", override={"project_per_day": 6, "project_per_week": 100})
ok = [submit(u, f"v{i}")[1].accepted for i in range(6)]
check("★ quota_override 提到 6/天 ⇒ 前 6 次全过", all(ok), True)
check("第 7 次 ⇒ 被拦", submit(u, "v6")[1].accepted, False)
check("★ 额度来源标为 user（便于排查「为什么他被限了」）",
      quota.check_upload_quota(u).source, "user")

u = fresh("smoke_q_unlimited", override={"project_per_day": 0, "project_per_week": 0})
ok = [submit(u, f"u{i}")[1].accepted for i in range(8)]
check("★★ project_per_day=0 ⇒ 完全不限制（8 次全过）", all(ok), True)
check("★ 判定标记 unlimited", quota.check_upload_quota(u).unlimited, True)

u = fresh("smoke_q_tiervip", tier="vip")
ok = [submit(u, f"tv{i}")[1].accepted for i in range(10)]
check("★ VIP 档位默认 10/天 ⇒ 前 10 次全过", all(ok), True)
check("VIP 第 11 次 ⇒ 被拦", submit(u, "tv10")[1].accepted, False)

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★ 日 / 周边界（★ 必须用本地时区，否则用户觉得「半夜重置」）")
print("=" * 80)
u = fresh("smoke_q_boundary")
t1 = tz.localtime(tz.now()).replace(hour=10, minute=0, second=0, microsecond=0)
for i in range(3):
    submit(u, f"b{i}", at=t1)
check("当天 10:00 满 3 次 ⇒ 被拦", submit(u, "b3", at=t1)[1].accepted, False)
t2 = (tz.localtime(t1) + timedelta(days=1)).replace(hour=10)
_, r = submit(u, "b4", at=t2)
check("★★ 第二天 10:00 ⇒ 又能提交（日窗口滚动了）", r.accepted, True)

u = fresh("smoke_q_week", override={"project_per_day": 0, "project_per_week": 3})
for i in range(3):
    submit(u, f"w{i}")
_, r = submit(u, "w3")
check("周限 3 ⇒ 第 4 次被拦", r.quota.reason_code, quota.CODE_WEEKLY)
t_next = tz.localtime(quota.week_start()) + timedelta(days=7, hours=10)
_, r = submit(u, "w4", at=t_next)
check("★★ 下周一 ⇒ 又能提交（周窗口滚动了）", r.accepted, True)

# ===========================================================================
print()
print("=" * 80)
print("⑦ ★★ 重复提交同一个仓库（★ 单纯限次数挡不住「改个名字反复刷」）")
print("=" * 80)
u = fresh("smoke_q_dup")
p, r = submit(u, "dup1", repo="https://github.com/a/b")
check("首次提交该仓库 ⇒ 允许", r.accepted, True)

p2 = Project.objects.create(owner=u, name="dup2（改了名字）", repo_url="https://github.com/a/b")
r2 = submission.submit_project(p2, u, license_verdict=evaluate(texts=MIT))
check("★★ 同一仓库换个名字再提交 ⇒ 被拦", r2.accepted, False)
check("拦截原因", r2.quota.reason_code, quota.CODE_DUPLICATE_REPO)
check("★ 提示里点名了已存在的那个项目", "dup1" in r2.user_message, True)

ProjectReview.objects.filter(submitted_by=u).first().reject(
    by=admin, note="是误判", refund_quota=True
)
r3 = submission.submit_project(p2, u, license_verdict=evaluate(texts=MIT))
check("★ 被驳回后可以重传（不把人锁死）", r3.accepted, True)

# ===========================================================================
print()
print("=" * 80)
print("⑧ ★ 自动拒绝（无许可证 + 开关打开）不该罚用户额度")
print("=" * 80)
u = fresh("smoke_q_autoreject")
for i in range(5):
    _, r = submit(u, f"ar{i}", texts={}, require_file=True)
check("无许可证 + require_file=True ⇒ 5 次全被拒", True, True)
check("★ 全部是自动判定", ProjectReview.objects.filter(
    submitted_by=u, auto_decided=True).count(), 5)
check("★★ 但【一次额度都没扣】（全标了不占额度）",
      quota.count_submissions(u, since=quota.day_start()), 0)
_, r = submit(u, "ar_ok", texts=MIT)
check("★★ 所以还能正常提交（额度没被吃掉）", r.accepted, True)

# ===========================================================================
print()
print("=" * 80)
print("⑨ ★ 总开关：管理员可整体关掉限额（⚠ 只在被刷爆时才关）")
print("=" * 80)
from core import appsettings  # noqa: E402

u = fresh("smoke_q_switch")
for i in range(3):
    submit(u, f"s{i}")
check("默认开启时 ⇒ 第 4 次被拦", submit(u, "s3")[1].accepted, False)

appsettings.set_value("quota.upload_limit", False, actor=admin)
try:
    _, r = submit(u, "s4")
    check("★★ 关掉总开关 ⇒ 立刻放行（无需重启）", r.accepted, True)
finally:
    appsettings.set_value("quota.upload_limit", True, actor=admin)

# ===========================================================================
print()
print("=" * 80)
print("⑩ ★ 管理员视角：一眼回答「他为什么传不了」")
print("=" * 80)
u = fresh("smoke_q_adminview", override={"project_per_day": 2, "project_per_week": 99})
for i in range(2):
    submit(u, f"av{i}")
info = quota.describe_for_admin(u)
print(f"     {info['user']}  tier={info['tier']}  覆盖={info['quota_override']}")
print(f"     额度: {info['used_day']}/{info['project_per_day']} 天 · "
      f"{info['used_week']}/{info['project_per_week']} 周")
check("★ 管理员能看到覆盖值", info["quota_override"].get("project_per_day"), 2)
check("★ 管理员能看到已用", info["used_day"], 2)

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
