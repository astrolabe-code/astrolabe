"""Astrolabe · 冒烟：**发布全链路**（把 `core/` 六个模块串起来）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_publish.py"

★★★ 这是第一次真正走通：

```
① 归属校验 → ② 建项目 + 限额闸门 → ③ 投递作业
                                      ↓
                     ④ 作业：许可核验 → 解析 → 写图
                                      ↓
                     ⑤ 管理员放行 ⇒ 重投 ⇒ 出图
```

★★ 重点验证**四件容易做错的事**：

1. ★★ **限额拦住时【不留孤儿项目】** —— ⚠ 用户被拦了却多出一个空项目，很荒谬
2. ★★ **许可不过 ⇒ 【不解析】** —— `U3.1` 第 ④ 步：通过后才允许解析
3. ★★ **「待核验」不能被算成「没有许可证」** —— ⚠ 否则管理员看到的原因是错的
4. ★★ **人工放行后必须真的重投作业** —— ⚠ 否则"点了放行、项目页永远是空的"
"""

import os
import tempfile

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model

from core import appsettings, licensing, oauth, publish, quota, submission
from core.models import OAuthIdentity, Project, ProjectReview
from graph.models import Edge, Node
from jobs.models import Job
from jobs.tasks import run_parse_job

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


U = get_user_model()
PROVIDER = "github"

# ---------------------------------------------------------------- 假第三方
dj_settings.ASTROLABE_OAUTH = {
    "github": {"client_id": "cid", "client_secret": "sec"},
    "gitee": {"client_id": "cid", "client_secret": "sec"},
}
dj_settings.ASTROLABE_BASE_URL = "http://test.local"
#: ★ 每个测试用户一个**独立**的第三方数字 ID
#:   ⚠ 因为 `uniq_provider_identity` 约束住「一个 provider 身份只能绑一个账号」
_PID = [700000]


class FakeFetcher:
    def __init__(self, repo=None):
        self.repo = repo if repo is not None else {
            "id": 7, "full_name": "smoke_owner/demo",
            "owner": {"id": 0, "login": "smoke_owner", "type": "User"},
            "fork": False,
        }

    def post_form(self, url, data, *, headers=None):  # noqa: ARG002
        return {"access_token": "tok"}

    def get_json(self, url, *, headers=None):  # noqa: ARG002
        return self.repo


# ---------------------------------------------------------------- 造源码目录
MIT = "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy"
GPL = "GNU GENERAL PUBLIC LICENSE\n  Version 3, 29 June 2007"


#: ★★ 源码目录必须建在 **bind mount 内**（`/app` 是宿主机挂进来的）
#: ⚠★ 教训：一开始用 `tempfile.mkdtemp()` 建在 **web 容器的 `/tmp`** ⇒
#:   **worker 容器看不到**（`/tmp` 是各容器私有的）⇒ 作业真的跑起来时**找不到路径**。
#:   ★ 而这恰恰说明**真 worker 在正常工作**（它会真的来抢这个作业）。
SMOKE_TMP = "/app/.smoke_tmp"


def make_repo(license_text=None):
    """★ 造一个最小的源码目录（★ 含真实文件，★ 作业会真的去扫它）。

    ⚠ 放在 `/app/.smoke_tmp` 而不是 `/tmp` —— 见上面的说明。
    """
    os.makedirs(SMOKE_TMP, exist_ok=True)
    d = tempfile.mkdtemp(prefix="repo_", dir=SMOKE_TMP)
    if license_text is not None:
        with open(os.path.join(d, "LICENSE"), "w") as fh:
            fh.write(license_text)
    with open(os.path.join(d, "main.py"), "w") as fh:
        fh.write("def foo():\n    return bar()\n\n\ndef bar():\n    return 1\n")
    return d


# ---------------------------------------------------------------- 造用户 / 身份
admin, _ = U.objects.get_or_create(username="smoke_pub_admin")
admin.is_superuser = admin.is_staff = True
admin.save(update_fields=["is_staff", "is_superuser"])


def fresh_user(name):
    """★ 造一个干净的发布者（★ 每次给一个新的第三方数字 ID）。"""
    _PID[0] += 1
    u, _ = U.objects.get_or_create(username=name)
    OAuthIdentity.objects.filter(user=u).delete()
    OAuthIdentity.objects.create(
        user=u, provider=PROVIDER, provider_user_id=str(_PID[0]), login=name
    )
    p = submission.ensure_profile(u)
    p.tier, p.quota_override = "free", {"project_per_day": 0, "project_per_week": 0}
    p.save(update_fields=["tier", "quota_override"])
    Project.objects.filter(owner=u).delete()
    ProjectReview.objects.filter(submitted_by=u).delete()
    return u


user = fresh_user("smoke_pub_user")
appsettings.set_value("license_require_file", False, actor=admin)


def pid_of(u) -> str:
    return OAuthIdentity.objects.get(user=u, provider=PROVIDER).provider_user_id


def repo_of(full, owner_id):
    return {"id": 7, "full_name": full,
            "owner": {"id": int(owner_id), "login": full.split("/")[0], "type": "User"},
            "fork": False}


def do_publish(u, full, root):
    """★ 发布（★ 假仓库的 owner.id 与这个用户绑定的数字 ID 一致）。"""
    return publish.publish_project(
        u, provider=PROVIDER, access_token="tok", repo_full_name=full,
        name=full.split("/")[-1], source_path=root,
        fetcher=FakeFetcher(repo_of(full, pid_of(u))),
    )


def run_job(job, timeout: float = 30.0):
    """★ 跑作业（★ **走 `tasks.execute()`** —— 与 worker **同一个入口**）。

    ★★ 关键：`execute()` 里做的是**原子抢占**（`started_at IS NULL`）——
      ⇒ ★ **谁先抢到谁跑，另一个直接跳过**。⚠ 真 worker 一直在跑，
        所以这里**不再有"两个进程同时跑同一个作业"的问题**。

    ★ 抢不到就**等它跑完**（★ 断言才不会看到中间状态）。
    """
    from time import monotonic, sleep

    from jobs import queue
    from jobs.tasks import execute

    try:
        queue.remove(job.pk)     # ⚠ 只是尽量不让 worker 抢；抢不到也无所谓
    except Exception:  # noqa: BLE001
        pass

    execute(job)                 # ★ 抢不到 ⇒ 内部直接返回，什么都不做

    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job.refresh_from_db()
        if job.state in (Job.STATE_DONE, Job.STATE_FAILED, Job.STATE_CANCELED):
            break
        sleep(0.1)
    return job


# ===========================================================================
print("=" * 80)
print("① 发布：归属校验 → 建项目 → 限额闸门 → 投递作业")
print("=" * 80)
r = do_publish(user, "smoke_owner/mit_demo", make_repo(MIT))
check("★ 发布受理", r.ok, True)
check("★ 归属校验通过", r.steps.get("ownership", {}).get("ok"), True)
check("★ 建出了项目", r.project is not None, True)
check("★ 投出了作业", r.job is not None, True)
check("★ 作业类型是 parse", r.job.kind, Job.KIND_PARSE)
check("★★ 作业 payload 带上了 project_id（★ 作业要回写许可结论）",
      r.job.payload.get("project_id"), r.project.pk)
check("★ 项目状态 = 待审核", r.project.review_state, Project.REVIEW_PENDING)
check("★★ 流水的原因码是【待核验】而不是 `no_license`（★ 两者是不同的事）",
      r.review.reason_code, licensing.CODE_PENDING)

# ===========================================================================
print()
print("=" * 80)
print("② 作业跑起来：许可宽松 ⇒ 放行 ⇒ 解析 ⇒ 出图")
print("=" * 80)
ref1 = r.project.project_ref
job = run_job(r.job)
check("★ 作业归宿 = parsed", job.payload.get("outcome"), "parsed")
check("★ 解析出了节点", Node.objects.filter(project_ref=ref1).count() > 0, True)
check("★ 解析出了边", Edge.objects.filter(project_ref=ref1).count() > 0, True)

r.review.refresh_from_db()
r.project.refresh_from_db()
check("★★ 流水被【就地更新】成真结论（不再是「待核验」）",
      r.review.reason_code, "permissive")
check("★★ 只更新了那一条，没有多出一条（★ 否则限额会算两次）",
      ProjectReview.objects.filter(submitted_by=user, project_ref=ref1).count(), 1)
check("★ 项目许可字段已写上", r.project.license_spdx, "MIT")
check("★ 项目状态 = 已放行", r.project.review_state, Project.REVIEW_APPROVED)

# ===========================================================================
print()
print("=" * 80)
print("③ ★★ GPL ⇒ 停在「待人工审核」⇒ ★【不解析】（U3.1 第 ④ 步）")
print("=" * 80)
r2 = do_publish(user, "smoke_owner/gpl_demo", make_repo(GPL))
ref2 = r2.project.project_ref
print(f"     [插桩] ref2={ref2} job={r2.job.pk} 跑之前节点={Node.objects.filter(project_ref=ref2).count()}")
job2 = run_job(r2.job)
print(f"     [插桩] 跑之后节点={Node.objects.filter(project_ref=ref2).count()} "
      f"| ref2 的作业={list(Job.objects.filter(project_ref=ref2).values_list('pk', 'state', 'stage'))}")
check("★ 作业归宿 = awaiting_review", job2.payload.get("outcome"), "awaiting_review")
check("★★★ **没有解析**（图是空的）", Node.objects.filter(project_ref=ref2).count(), 0)
check("★ 作业【不是 failed】（★ 业务结论 ≠ 系统故障）",
      job2.state != Job.STATE_FAILED, True)

r2.review.refresh_from_db()
check("★ 流水结论 = 传染性（★ 管理员看到的是真原因）", r2.review.reason_code, "copyleft")
check("★ 且带了「为什么」（人类可读）", "衍生" in r2.review.reason_text, True)
check("★ 流水仍是待审核", r2.review.decision, ProjectReview.DECISION_PENDING)
check("★ 项目状态 = 待审核", Project.objects.get(pk=r2.project.pk).review_state,
      Project.REVIEW_PENDING)

# ---- ⑤ 管理员放行 ⇒ ★ 重投作业 ⇒ 出图 ----
print()
print("  ── ⑤ 管理员放行 + 自动重投作业 ──")
rv, job3 = publish.approve_and_resume(
    r2.review, by=admin, note="提交者即权利人本人，放行",
    source_path=make_repo(GPL),
)
check("★★ 放行时【自动重投】了作业（★ 否则项目页永远是空的）", job3 is not None, True)
job3 = run_job(job3)
check("★★ 重投后归宿 = parsed", job3.payload.get("outcome"), "parsed")
check("★★★ 图出来了", Node.objects.filter(project_ref=ref2).count() > 0, True)
r2.review.refresh_from_db()
check("★ 人工结论被保留（★ 核验不会推翻人的判断）",
      r2.review.decision, ProjectReview.DECISION_APPROVED)
check("★ 决定人已记录", r2.review.decided_by_id, admin.pk)

# ===========================================================================
print()
print("=" * 80)
print("④ ★★ 无许可证 + require_file=True ⇒ 自动拒绝 ⇒ 不解析 ⇒ 不扣额度")
print("=" * 80)
appsettings.set_value("license_require_file", True, actor=admin)
try:
    u4 = fresh_user("smoke_pub_u4")
    r4 = do_publish(u4, "smoke_owner/nolic_demo", make_repo(None))
    job4 = run_job(r4.job)
    check("★ 作业归宿 = rejected", job4.payload.get("outcome"), "rejected")
    check("★★ 没有解析", Node.objects.filter(project_ref=r4.project.project_ref).count(), 0)
    r4.review.refresh_from_db()
    check("★ 流水 = 自动拒绝", r4.review.decision, ProjectReview.DECISION_REJECTED)
    check("★★ 且【不占额度】（材料不全，不该罚用户）", r4.review.quota_refunded, True)
    check("★ 计数确实是 0", quota.count_submissions(u4, since=quota.day_start()), 0)
finally:
    appsettings.set_value("license_require_file", False, actor=admin)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★ 限额拦住 ⇒ 【不留孤儿项目】")
print("=" * 80)
u5 = fresh_user("smoke_pub_u5")
# ★ 把日额度压到 1
p5 = submission.ensure_profile(u5)
p5.quota_override = {"project_per_day": 1, "project_per_week": 1}
p5.save(update_fields=["quota_override"])

before = Project.objects.filter(owner=u5).count()
r5a = do_publish(u5, "smoke_owner/q1", make_repo(MIT))
check("第 1 次发布 ⇒ 成功", r5a.ok, True)
check("★ 项目数 +1", Project.objects.filter(owner=u5).count(), before + 1)

r5b = do_publish(u5, "smoke_owner/q2", make_repo(MIT))
check("第 2 次发布 ⇒ 被限额拦住", r5b.ok, False)
check("★ 原因码 = daily", r5b.reason_code, quota.CODE_DAILY)
check("★★★ **没有留下孤儿项目**（★ 事务回滚）",
      Project.objects.filter(owner=u5).count(), before + 1)
check("★ 也没留下多余流水",
      ProjectReview.objects.filter(submitted_by=u5).count(), 1)

# ---- 重复仓库 ----
r5c = do_publish(u5, "smoke_owner/q1", make_repo(MIT))
check("★ 同一仓库重复发布 ⇒ 被拦", r5c.ok, False)
check("★ 原因码 = duplicate_repo", r5c.reason_code, quota.CODE_DUPLICATE_REPO)

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★★ 归属校验不过 ⇒ 连项目都不建")
print("=" * 80)
u6 = fresh_user("smoke_pub_u6")
n_before = Project.objects.count()

r6 = publish.publish_project(
    u6, provider=PROVIDER, access_token="tok", repo_full_name="someone_else/demo",
    source_path=make_repo(MIT),
    fetcher=FakeFetcher(),      # ★ 默认 repo 的 owner.id = 4242，但演示时换个仓库名
)
check("★ 别人的仓库 ⇒ 拒绝", r6.ok, False)
check("★★★ 并且【没有建任何项目】", Project.objects.count(), n_before)

r6b = publish.publish_project(
    u6, provider=PROVIDER, access_token="tok", repo_full_name="smoke_owner/forky",
    source_path=make_repo(MIT),
    fetcher=FakeFetcher(repo={**repo_of("smoke_owner/forky", pid_of(u6)), "fork": True}),
)
check("★ Fork ⇒ 拒绝", r6b.ok, False)
check("★ 原因码 = fork", r6b.reason_code, "fork")
check("★★ 同样没建项目", Project.objects.count(), n_before)

# ---- 没绑定身份 ----
u6b = fresh_user("smoke_pub_u6b")
OAuthIdentity.objects.filter(user=u6b).delete()
r6c = publish.publish_project(
    u6b, provider=PROVIDER, access_token="tok", repo_full_name="x/y", source_path=""
)
check("★ 没绑定身份 ⇒ 提示先登录", r6c.ok, False)
check("★ 原因码 = identity_missing", r6c.reason_code, "identity_missing")

# ===========================================================================
print()
print("=" * 80)
print("⑦ ★★ 列表查询集：只有【已放行】的才该出现在列表里")
print("=" * 80)
refs = set(publish.public_projects().values_list("project_ref", flat=True))
check("★ 已放行的 MIT 项目在列表里", ref1 in refs, True)
check("★ 放行后的 GPL 项目也在", ref2 in refs, True)
check("★★ 但【被自动拒绝】的项目不在列表里",
      r4.project.project_ref in refs, False)
check("★ 而它的【页面】仍然可访问（is_public=True）★ 便于作者自己看状态",
      Project.objects.get(pk=r4.project.pk).is_public, True)

# ===========================================================================
print()
print("=" * 80)
print("⑧ 用户视角：能看到自己的提交与驳回原因")
print("=" * 80)
subs = submission.my_submissions(u4)
check("★ 用户能查到提交记录", len(subs) >= 1, True)
rejected = [s for s in subs if s["status"] == "rejected"]
check("★ 其中有一条是被拒绝的", len(rejected), 1)
check("★★★ 而且用户【能看到拒绝原因】", bool(rejected[0]["reject_reason"]), True)
check("★ 提示里说明「不占额度」", rejected[0]["quota_refunded"], True)
print(f"       驳回原因：{rejected[0]['reject_reason'][:60]}…")

# ===========================================================================
appsettings.set_value("license_require_file", False, actor=admin)

# ★ 清掉临时源码目录（⚠ 它建在 /app 里，不留残渣）
import shutil  # noqa: E402

shutil.rmtree(SMOKE_TMP, ignore_errors=True)

print()
print("=" * 80)
if FAILED:
    print(f"❌ 失败 {len(FAILED)} 项：")
    for f in FAILED:
        print(f"   - {f}")
else:
    print("✅ 全部通过")
print("=" * 80)
