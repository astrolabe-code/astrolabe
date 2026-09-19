"""Astrolabe · 冒烟：**业务端点**（邀请 / 我的 / 发布 / 管理员审核）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_api_biz.py"

★★★ 重点验证**五件最要命的事**：

1. ★★★ **管理员端点不能被普通用户碰到**（邀请生成 / 审核队列）
2. ★★★ **审核队列必须给出「为什么进审核」**（`U3.7` 四要素）
3. ★★★ **驳回必须带理由**（★ 且是 400 不是 500）
4. ★★ **用户侧看不到内部字段**（`evidence` / `suggestion` 不能泄露）
5. ★★ **发布端到端**：start → OAuth 回调（★ 发布只在这一刻发生）→ 项目 + 作业 + 审核项
"""

import os
import tempfile

from django.conf import settings as dj
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.utils import timezone as tz

from core import oauth, submission
from core.models import OAuthIdentity, OAuthState, Project, ProjectReview
from graph.models import Node
from jobs.models import Job
from jobs.tasks import execute
from web import auth

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


U = get_user_model()
PROVIDER = "github"
_PID = [820000]

dj.ASTROLABE_OAUTH = {
    "github": {"client_id": "cid", "client_secret": "sec"},
    "gitee": {"client_id": "cid", "client_secret": "sec"},
}
dj.ASTROLABE_BASE_URL = "http://test.local"
dj.ASTROLABE_SPA_URL = "http://spa.test/"
dj.ASTROLABE_ALLOWED_ORIGINS = ("http://spa.test",)

SMOKE_TMP = "/app/.smoke_tmp"


class FakeFetcher:
    def __init__(self, uid, login):
        self.uid, self.login = uid, login
        # ⚠ 默认空串 —— ★ 否则 `get_json` 在 `repo` 还没设时会是 `AttributeError`
        self.repo = "smoke_biz_owner/repo"

    def post_form(self, url, data, *, headers=None):  # noqa: ARG002
        return {"access_token": "gho_fake"}

    def get_json(self, url, *, headers=None):  # noqa: ARG002
        if url.endswith("/user"):
            return {"id": self.uid, "login": self.login, "avatar_url": ""}
        # ★ 仓库信息（★ 归属校验用）
        return {
            "id": 9, "full_name": self.repo, "fork": False,
            "owner": {"id": self.uid, "login": self.repo.split("/")[0], "type": "User"},
        }


def run_and_wait(job: Job, timeout: float = 30.0) -> Job:
    """★ 跑作业并**等它真的结束**。

    ⚠★ 为什么要等：★ `execute()` 里是**原子抢占**（`B149`），⚠ 而真 worker 一直在跑 ——
      ★ 谁先抢到谁跑，另一个**直接返回**。⇒ ★ 不等就可能**在作业跑完前就断言**
      （⚠ 实测踩到：日志里"作业已被其他进程领取，跳过"，★ 而断言立刻说"没出图"）。
    """
    from time import monotonic, sleep

    execute(job)                      # ★ 抢不到 ⇒ 内部直接返回，什么都不做
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job.refresh_from_db()
        if job.state in (Job.STATE_DONE, Job.STATE_FAILED, Job.STATE_CANCELED):
            break
        sleep(0.1)
    return job


def make_repo(lic):
    os.makedirs(SMOKE_TMP, exist_ok=True)
    d = tempfile.mkdtemp(prefix="biz_", dir=SMOKE_TMP)
    if lic is not None:
        with open(os.path.join(d, "LICENSE"), "w") as fh:
            fh.write(lic)
    with open(os.path.join(d, "main.py"), "w") as fh:
        fh.write("def foo():\n    return bar()\n\n\ndef bar():\n    return 1\n")
    return d


MIT = "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy"
GPL = "GNU GENERAL PUBLIC LICENSE\n  Version 3, 29 June 2007"

admin, _ = U.objects.get_or_create(username="smoke_biz_admin")
admin.is_superuser = admin.is_staff = True
admin.save(update_fields=["is_staff", "is_superuser"])

# ---- 清理（⚠ 排除 admin 自己，否则 AppSetting.updated_by 会指向已删除用户）----
from core import appsettings  # noqa: E402

OAuthState.objects.all().delete()
for u in U.objects.filter(username__startswith="smoke_biz_").exclude(pk=admin.pk):
    Project.objects.filter(owner=u).delete()
    ProjectReview.objects.filter(submitted_by=u).delete()
    OAuthIdentity.objects.filter(user=u).delete()
    u.api_tokens.all().delete()
    u.delete()

_ctx = override_settings(ALLOWED_HOSTS=["testserver", "localhost", "test.local"])
_ctx.enable()
appsettings.set_value("registration_open", True, actor=admin)
appsettings.set_value("invite_required", False, actor=admin)

c = Client()

# ---- 造一个"已登录且有 GitHub 身份"的用户 ----
_PID[0] += 1
# ⚠★ **必须把它记下来** —— 后面还有别的测试用户会让 `_PID[0]` 继续自增；
#   如果那时再去读 `_PID[0]`，假 fetcher 就会用一个**错的数字 ID**，
#   ⇒ ⚠ 回调会认不出这个身份、**改走注册**（建出一个重名用户），
#   而测试断言却在找原用户 ⇒ **看起来像"发布没建流水"**（踩过一次）
MY_PID = _PID[0]
u, _ = U.objects.get_or_create(username="smoke_biz_user")
OAuthIdentity.objects.filter(user=u).delete()
OAuthIdentity.objects.create(
    user=u, provider=PROVIDER, provider_user_id=str(MY_PID), login="smoke_biz_user"
)
pf = submission.ensure_profile(u)
pf.tier, pf.quota_override = "free", {"project_per_day": 0, "project_per_week": 0}
pf.save(update_fields=["tier", "quota_override"])

raw_token, _ = auth.issue_token(u, provider=PROVIDER)
admin_token, _ = auth.issue_token(admin)
cu = Client(HTTP_AUTHORIZATION=f"Bearer {raw_token}")        # 普通用户
ca = Client(HTTP_AUTHORIZATION=f"Bearer {admin_token}")      # 管理员

# ===========================================================================
print("=" * 80)
print("① 邀请：★ 匿名可预检，★ 但生成 / 作废只有管理员能做")
print("=" * 80)
check("★ 匿名 GET 列表 ⇒ 401", c.get("/api/invites/").status_code, 401)
check("★★ 普通用户 GET 列表 ⇒ 403", cu.get("/api/invites/").status_code, 403)
check("★★ 普通用户 POST 生成 ⇒ 403", cu.post("/api/invites/", {}).status_code, 403)

# ★★ 匿名预检 —— `U4.8` 流程第 ② 步（没账号的人要先能校验）
r = c.post("/api/invites/check/", {"token": "no-such"}, content_type="application/json")
check("★★★ 匿名 POST check ⇒ 200（★ 必须匿名可用）", r.status_code, 200)
check("★ 无效码 ⇒ ok=false", r.json()["data"]["ok"], False)
check("★★ 且给了可读原因", bool(r.json()["data"]["message"]), True)

r = ca.post("/api/invites/", {"max_uses": 2, "valid_days": 3, "note": "SMOKE BIZ"},
            content_type="application/json")
check("★ 管理员生成 ⇒ 201", r.status_code, 201)
inv = r.json()["data"]
check("★ 返回了 token", len(inv["token"]), 32)
check("★ 返回了可分享链接", inv["url"].startswith("http://spa.test/invite/"), True)

r = c.post("/api/invites/check/", {"token": inv["token"]}, content_type="application/json")
check("★ 有效码 ⇒ ok=true", r.json()["data"]["ok"], True)
check("★★ 且告诉他【是谁】邀请的（连带责任对用户也可见）",
      r.json()["data"]["invited_by"], admin.username)

r = ca.post("/api/invites/", {"valid_days": 0}, content_type="application/json")
check("★★ 非法有效期 ⇒ 400（❌ 不是 500）", r.status_code, 400)
check("★ 原因码 = bad_valid_days", r.json()["error"]["code"], "bad_valid_days")

check("★ 作废 ⇒ 200", ca.post(f"/api/invites/{inv['token']}/revoke/").status_code, 200)
r = c.post("/api/invites/check/", {"token": inv["token"]}, content_type="application/json")
check("★ 作废后 ⇒ ok=false", r.json()["data"]["ok"], False)

# ===========================================================================
print()
print("=" * 80)
print("② 我的：额度 + 提交记录（★ U3.8 驳回原因）")
print("=" * 80)
check("★ 匿名 ⇒ 401", c.get("/api/me/upload/").status_code, 401)
r = cu.get("/api/me/upload/")
check("★ 已登录 ⇒ 200", r.status_code, 200)
check("★ 返回了剩余额度", "remaining_day" in r.json()["data"], True)

r = cu.get("/api/me/submissions/")
check("★ 提交记录（初始为空）", r.json()["data"]["submissions"], [])
check("★ 带计数（前端做空状态文案）", r.json()["data"]["counts"]["total"], 0)

# ===========================================================================
print()
print("=" * 80)
print("③ 发布：★ 只负责「发起授权」（⚠ 真正的发布在回调里）")
print("=" * 80)
check("★ 匿名 ⇒ 401", c.post("/api/projects/publish/start/", {}).status_code, 401)

# ---- 未绑定身份 ----
_PID[0] += 1
u2, _ = U.objects.get_or_create(username="smoke_biz_user2")
raw2, _ = auth.issue_token(u2)
cu2 = Client(HTTP_AUTHORIZATION=f"Bearer {raw2}")
r = cu2.post("/api/projects/publish/start/",
             {"provider": "gitee", "repo": "x/y"}, content_type="application/json")
check("★★ 没绑定过该 provider 的身份 ⇒ 早失败", r.status_code, 400)
check("★ 原因码 = identity_missing", r.json()["error"]["code"], "identity_missing")

# ---- 非法仓库格式 ----
r = cu.post("/api/projects/publish/start/",
            {"provider": PROVIDER, "repo": "badformat"}, content_type="application/json")
check("★ 仓库格式不对 ⇒ 400", r.status_code, 400)
check("★ 原因码 = bad_repo", r.json()["error"]["code"], "bad_repo")

# ---- ★★ open redirect ----
r = cu.post("/api/projects/publish/start/",
            {"provider": PROVIDER, "repo": "owner/repo", "next_url": "https://evil.com"},
            content_type="application/json")
check("★★★ 发布端点同样挡住外站 next_url", r.status_code, 400)
check("★ 原因码 = bad_next_url", r.json()["error"]["code"], "bad_next_url")

# ===========================================================================
print()
print("=" * 80)
print("④ ★★★ 发布端到端：start → 回调（★ 发布只在这一刻发生）")
print("=" * 80)
# ★ 装假 fetcher（⚠ 视图不接受注入，只能覆盖模块级默认值）
_FF = FakeFetcher(MY_PID, "smoke_biz_user")     # ★ 用记下来的那个 id，⚠ 不是 _PID[0]
_FF.repo = "smoke_biz_owner/gpl_repo"
oauth._default_fetcher = _FF

src = make_repo(GPL)
r = cu.post("/api/projects/publish/start/",
            {"provider": PROVIDER, "repo": _FF.repo, "name": "冒烟 GPL 项目",
             "source_path": src, "next_url": "/me"},
            content_type="application/json")
check("★ 发起授权 ⇒ 200", r.status_code, 200)
state = r.json()["data"]["state"]
check("★ 返回授权 URL", "github.com/login/oauth/authorize" in r.json()["data"]["authorize_url"], True)

r = c.get(f"/api/auth/{PROVIDER}/callback/?code=abc&state={state}&format=json")
check("★ 回调 ⇒ 200", r.status_code, 200)
data = r.json()["data"]
check("★★ 回调里【顺带签发了令牌】（用户由此登录）", bool(data["token"]), True)
check("★★★ 回调里【完成了发布】", "publish" in data, True)
pub = data["publish"]
check("★★ 发布成功", pub["ok"], True)
check("★ 给出了 project_ref", pub["project_ref"].startswith("proj_"), True)
check("★ 给出了 job_id", bool(pub["job_id"]), True)
check("★★ 且说明了状态（★ 用户要能看懂下一步）", bool(pub["message"]), True)

review = ProjectReview.objects.filter(submitted_by=u).order_by("-created_at").first()
check("★★★ 建出了审核流水（★ 「待核验」）", review.reason_code, "license_pending")
check("★ 项目状态 = 待审核", Project.objects.get(project_ref=pub["project_ref"]).review_state,
      Project.REVIEW_PENDING)

# ---- 作业跑起来 ⇒ 许可核验把流水【就地更新】----
job = run_and_wait(Job.objects.get(pk=pub["job_id"]))
review.refresh_from_db()
check("★★ 作业归宿 = awaiting_review（GPL 要人工看）", job.payload.get("outcome"), "awaiting_review")
check("★★ 流水被更新成真结论（不再是「待核验」）", review.reason_code, "copyleft")

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★★ 管理员审核队列（★ U3.7 四要素必须在）")
print("=" * 80)
check("★ 普通用户 ⇒ 403", cu.get("/api/admin/reviews/").status_code, 403)
check("★ 普通用户 approve ⇒ 403", cu.post(f"/api/admin/reviews/{review.pk}/approve/").status_code, 403)

r = ca.get("/api/admin/reviews/")
check("★ 管理员 ⇒ 200", r.status_code, 200)
q = r.json()["data"]
check("★ 有待办", q["counts"]["pending"] >= 1, True)
item = next(x for x in q["reviews"] if x["id"] == review.pk)
check("★★ ① 进审核的原因（人类可读）", bool(item["reason_text"]), True)
check("★★ ② 检测证据", bool(item["evidence"]), True)
check("★★ ③ 系统建议", bool(item["suggestion"]), True)
check("★★ ④ 提交者（★ 连带责任）", item["submitted_by"], "smoke_biz_user")
print(f"       进审核原因：{item['reason_text'][:56]}…")
print(f"       系统建议　：{item['suggestion'][:56]}")

# ---- 驳回：必须带理由 ----
r = ca.post(f"/api/admin/reviews/{review.pk}/reject/", {}, content_type="application/json")
check("★★★ 无理由驳回 ⇒ 400（❌ 不是 500）", r.status_code, 400)
check("★★ 原因码 = missing_reason", r.json()["error"]["code"], "missing_reason")

r = ca.post(f"/api/admin/reviews/{review.pk}/reject/",
            {"note": "版权归属不清晰，请补充来源说明", "refund_quota": True},
            content_type="application/json")
check("★ 有理由驳回 ⇒ 200", r.status_code, 200)
check("★★ 且已退还额度", r.json()["data"]["refunded"], True)

# ---- 重复处理 ----
r = ca.post(f"/api/admin/reviews/{review.pk}/reject/", {"note": "再驳一次"},
            content_type="application/json")
check("★★ 重复处理 ⇒ 409（⚠ 不覆盖已做出的决定）", r.status_code, 409)
check("★ 原因码 = already_decided", r.json()["error"]["code"], "already_decided")

# ---- ★★ 用户侧：能看到驳回原因，看不到内部字段 ----
r = cu.get("/api/me/submissions/")
subs = r.json()["data"]["submissions"]
mine = next(s for s in subs if s["id"] == review.pk)
check("★★★ 用户能看到【驳回原因】", mine["reject_reason"], "版权归属不清晰，请补充来源说明")
check("★★ 用户【看不到】evidence", "evidence" in mine, False)
check("★★ 用户【看不到】suggestion", "suggestion" in mine, False)
check("★★ 用户【看不到】reason_text（含判断要点）", "reason_text" in mine, False)
check("★ 计数正确", r.json()["data"]["counts"]["rejected"], 1)

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★★ 放行：没有图时必须给 source_path（⚠ 否则项目页会永远空着）")
print("=" * 80)
# 再提交一个项目（这次用 MIT ⇒ 自动放行，先造一个"待审核"的）
_FF2 = FakeFetcher(MY_PID, "smoke_biz_user")
_FF2.repo = "smoke_biz_owner/gpl_repo2"
oauth._default_fetcher = _FF2
src2 = make_repo(GPL)
st = cu.post("/api/projects/publish/start/",
             {"provider": PROVIDER, "repo": _FF2.repo, "name": "冒烟待审 2",
              "source_path": src2, "next_url": "/me"},
             content_type="application/json").json()["data"]["state"]
c.get(f"/api/auth/{PROVIDER}/callback/?code=c2&state={st}&format=json")
rv2 = ProjectReview.objects.filter(submitted_by=u).order_by("-created_at").first()
run_and_wait(Job.objects.filter(project_ref=rv2.project_ref).order_by("-id").first())

r = ca.post(f"/api/admin/reviews/{rv2.pk}/approve/", {}, content_type="application/json")
check("★★ 没有图且没给 source_path ⇒ 400", r.status_code, 400)
check("★★ 原因码 = source_required", r.json()["error"]["code"], "source_required")

r = ca.post(f"/api/admin/reviews/{rv2.pk}/approve/",
            {"note": "提交者即权利人本人", "source_path": src2},
            content_type="application/json")
check("★ 给上 source_path ⇒ 200", r.status_code, 200)
body = r.json()["data"]
check("★★★ 且【自动重投了作业】（★ 否则项目页永远是空的）", body["dispatched"], True)
check("★ 返回了 job_id", bool(body["job_id"]), True)

job2 = run_and_wait(Job.objects.get(pk=body["job_id"]))
check("★★★ 放行后真的解析出图了",
      Node.objects.filter(project_ref=rv2.project_ref).count() > 0, True)

# ===========================================================================
# 清理
appsettings.set_value("registration_open", False, actor=admin)
appsettings.set_value("invite_required", True, actor=admin)
import shutil  # noqa: E402

shutil.rmtree(SMOKE_TMP, ignore_errors=True)
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
