"""Astrolabe · 冒烟：**拉取代码的归属闸门**（`B169`）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_ownership_gate.py"

★★★ 本脚本验证**四件事**（★ 都是 `B169` 的核心断言）：

1. ★★★ **`POST …/fetch/` 只【发起授权】，❌ 不投递任何作业**
   —— ★ 这是 `B169` 的**全部要害**：★ 投递必须发生在**拿到 `access_token` 之后**的回调里
   （⚠ 因为本平台**不保存 token** —— `B148`）⇒ ★ 少了这一条，"拉代码"就**没有闸门** ⚠
2. ★★★ **归属【不符】⇒ 拒绝 + 【不投递】+ 留痕**
3. ★★ **归属【通过】⇒ 投递 + 留痕**（★ 且 `detail` 里有设计要求的三项）
4. ★★ **已定版 ⇒ 409**（★ 所有者裁定：★ 成功拉下**并解析**后，才不许再发起）

⚠ 全程**不连真实 GitHub** —— 用 `mock` 打掉 `verify_repo_ownership`（★ 测试才快、才确定）
★ 依据：`backend-design.md` 的 `[Gate 0]` ——「★ **未通过 ⇒ 服务端不代为拉取**」
"""

import secrets
from datetime import timedelta
from unittest import mock

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone as tz

from core import oauth
from core.models import AuditLog, OAuthIdentity, OAuthState, Project
from jobs.models import Job
from web import auth as web_auth
from web.views import auth as views_auth

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<56} = {got!r}")


U = get_user_model()

# ★ 假凭据（⚠ 不碰真实第三方）—— `oauth.start()` 需要 client_id/secret 才肯拼授权 URL
dj_settings.ASTROLABE_OAUTH = {
    "github": {"client_id": "cid-test", "client_secret": "sec-test"},
    "gitee": {"client_id": "cid-test", "client_secret": "sec-test"},
}
dj_settings.ASTROLABE_BASE_URL = "http://test.local"
# ⚠★★ `django.test.Client` 用的 Host 是 `testserver` ——
#   ★ 若不在 `ALLOWED_HOSTS` 里，Django 会**直接返回一个空的 400 HTML 页**
#   （⚠ 页面上什么都不说 ⇒ ★ 极容易被误判成"端点坏了"，★ 本次就踩了一次）
dj_settings.ALLOWED_HOSTS = ["*"]

# ===========================================================================
# 准备：一个用户 + 一个 GitHub 身份 + 一个项目
# ===========================================================================
user, _ = U.objects.get_or_create(username="smoke_gate_owner")
# ⚠★ `OAuthIdentity` 上有 `unique(provider, provider_user_id)` ——
#   ★ 所以**不能随便挑一个 ID**（`smoke_oauth.py` 已经占用了 `4242`）⚠
#   ⇒ ★ 这里用一个**本脚本专用**的 ID，并把该用户的旧身份先清掉（★ 让脚本可重复跑）
OAuthIdentity.objects.filter(user=user).delete()
ident = OAuthIdentity.objects.create(
    user=user, provider="github",
    provider_user_id="900042", login="alice", avatar_url="",
)

project, _ = Project.objects.get_or_create(
    name="冒烟-拉取闸门",
    defaults=dict(
        owner=user, provider="github",
        repo_url="https://github.com/alice/demo",
        state=Project.STATE_ACTIVE,
    ),
)
# ⚠ 每次跑都先把它复位成"未定版"（★ 否则上一轮的 ④ 会让本轮 ②③ 直接 409）
Project.objects.filter(pk=project.pk).update(graph_built_at=None, resolved_ref="")
project.refresh_from_db()
# ⚠ 清掉上一轮留下的作业/留痕（★ 让断言计数是干净的）
Job.objects.filter(project_ref=project.project_ref).delete()
AuditLog.objects.filter(target_id=project.project_ref).delete()

REF = project.project_ref
raw, _ = web_auth.issue_token(user)
c = Client(HTTP_AUTHORIZATION=f"Bearer {raw}")

print()
print("=" * 80)
print("① ★★★ `POST …/fetch/` 只【发起授权】—— ⚠ 不投递任何作业")
print("=" * 80)
jobs_before = Job.objects.filter(project_ref=REF).count()
r = c.post(f"/api/projects/{REF}/fetch/", content_type="application/json")
if r.status_code != 200:
    # ★ 诊断：★ 把真实响应打出来 —— ⚠ 否则只看到一个 400，只能回去猜（★ 这次不猜）
    print(f"     [诊断] status={r.status_code} ct={r.get('Content-Type')}")
    print(f"     [诊断] body={r.content[:600]!r}")
check("★★★ HTTP 200（拿到了授权 URL）", r.status_code, 200)
body = r.json().get("data", {}) if r.status_code == 200 else {}
check("★★ 返回了 authorize_url", bool(body.get("authorize_url")), True)
check("★★ 并且带上了 state", bool(body.get("state")), True)
check("★★★ ★ 没有产生任何作业（★ 这才是要害）",
      Job.objects.filter(project_ref=REF).count(), jobs_before)

# 🚫 未登录 —— ⚠★ **注意期望值**：★ 私有项目对匿名用户是 **404**（★ 与"不存在"不可区分），
#    ★★ 这是**刻意的安全口径**（★ 不让探测者靠状态码分辨"哪些项目存在"）——
#    ⚠ **不是 401**（★ 401 只在"带了无效 Bearer"时由中间件给出）
anon = Client()
r = anon.post(f"/api/projects/{REF}/fetch/", content_type="application/json")
check("★★ 未登录 + 私有项目 ⇒ 404（★ 与不存在不可区分）", r.status_code, 404)

# 🚫 未登录 + **公开**项目 ⇒ 看得到，但改不了 ⇒ 403
Project.objects.filter(pk=project.pk).update(is_public=True)
r = anon.post(f"/api/projects/{REF}/fetch/", content_type="application/json")
check("★★ 未登录 + 公开项目 ⇒ 403（★ 可见但不可操作）", r.status_code, 403)
Project.objects.filter(pk=project.pk).update(is_public=False)


def _state(repo: str) -> OAuthState:
    """★ 造一个 `ACTION_FETCH` 的 state（★ 模拟"用户从授权页回来了"）。

    ⚠★ `expires_at` 是**非空字段** —— `oauth.start()` 建的时候会填
      （★ 取自 `oauth.state_ttl_seconds`）；★ 这里手工建就**必须自己填**，
      ⚠ 否则直接 `NotNullViolation`（★ 本次踩过）。
    """
    return OAuthState.objects.create(
        state=secrets.token_urlsafe(16),
        provider="github",
        action=OAuthState.ACTION_FETCH,
        project_ref=REF,
        repo=repo,
        next_url="/app/workspace",
        expires_at=tz.now() + timedelta(minutes=10),
    )


def _result() -> oauth.OAuthResult:
    """★ 构造一个"登录成功、拿到 access_token"的回调结论（★ 与真实回调同形）。"""
    return oauth.OAuthResult(
        ok=True, action="login", user=user, identity=ident,
        provider="github", access_token="gho_FAKE", login="alice",
    )


# ===========================================================================
print()
print("=" * 80)
print("② ★★★ 归属【不符】⇒ 拒绝 + 【不投递】+ 留痕 rejected")
print("=" * 80)
verdict_bad = oauth.OwnershipVerdict(
    ok=False, reason_code="not_owner", message="这不是你的仓库。"
)
with mock.patch.object(oauth, "verify_repo_ownership", return_value=verdict_bad):
    out = views_auth._run_fetch(_result(), _state("someone-else/demo"))

check("★★★ ok = False", out.get("ok"), False)
check("★ 原因码透传出来了", out.get("reason_code"), "not_owner")
check("★★★ ★ 没有投递任何作业",
      Job.objects.filter(project_ref=REF).count(), jobs_before)
check("★★ 留痕写了 rejected",
      AuditLog.objects.filter(action="project.ownership_rejected", target_id=REF).count(), 1)
rej = AuditLog.objects.filter(action="project.ownership_rejected", target_id=REF).first()
check("★★ 留痕里记了「验的是哪个库」", rej.detail.get("repo"), "someone-else/demo")

# ===========================================================================
print()
print("=" * 80)
print("③ ★★ 归属【通过】⇒ 投递作业 + 留痕 verified")
print("=" * 80)
verdict_ok = oauth.OwnershipVerdict(
    ok=True, reason_code="", message="", repo={"id": 1, "full_name": "alice/demo"}
)
with mock.patch.object(oauth, "verify_repo_ownership", return_value=verdict_ok):
    out = views_auth._run_fetch(_result(), _state("alice/demo"))

check("★★★ ok = True", out.get("ok"), True)
check("★★ 拿到了 job_id", bool(out.get("job_id")), True)
check("★★★ ★ 投递了作业（★ 拉取 + 解析是同一个作业）",
      Job.objects.filter(project_ref=REF).count(), jobs_before + 1)
verify_qs = AuditLog.objects.filter(action="project.ownership_verified", target_id=REF)
check("★★ 留痕写了 verified", verify_qs.count(), 1)
detail = verify_qs.first().detail
check("★★★ detail 里有设计要求的三项",
      all(k in detail for k in ("verify_provider", "verify_account", "verified_at")), True)
check("★ verify_provider 对", detail.get("verify_provider"), "github")

# ===========================================================================
print()
print("=" * 80)
print("④ ★★ 已定版 ⇒ 409（★ 所有者裁定：成功拉下【并解析】后才不许再发起）")
print("=" * 80)
Project.objects.filter(pk=project.pk).update(graph_built_at=tz.now(), resolved_ref="deadbeef")
r = c.post(f"/api/projects/{REF}/fetch/", content_type="application/json")
check("★★★ 已定版 ⇒ 409", r.status_code, 409)
check("★ 原因码 = graph_immutable", r.json()["error"]["code"], "graph_immutable")
msg = r.json()["error"]["message"]
check("★★ 消息里给了两条出路",
      ("新建一个项目" in msg) and ("删掉本项目后重建" in msg), True)

# ★ 复位（★ 让脚本可重复跑）
Project.objects.filter(pk=project.pk).update(graph_built_at=None, resolved_ref="")

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★ 纵深防御：`_run_fetch` 自己也会拦「已定版」")
print("=" * 80)
Project.objects.filter(pk=project.pk).update(graph_built_at=tz.now())
jobs_now = Job.objects.filter(project_ref=REF).count()
with mock.patch.object(oauth, "verify_repo_ownership", return_value=verdict_ok):
    out = views_auth._run_fetch(_result(), _state("alice/demo"))
check("★★★ 直接调 `_run_fetch` 也被拦（★ 不靠视图那一层）", out.get("ok"), False)
check("★ 原因码", out.get("reason_code"), "graph_immutable")
check("★★★ 且没有投递", Job.objects.filter(project_ref=REF).count(), jobs_now)
Project.objects.filter(pk=project.pk).update(graph_built_at=None, resolved_ref="")

# ===========================================================================
print()
print("=" * 80)
if FAILED:
    print(f"❌ 失败 {len(FAILED)} 项：")
    for f in FAILED:
        print(f"   · {f}")
else:
    print("★★★★★ 全部通过（归属闸门成立：未验证 ⇒ 服务端不代为拉取）")
print("=" * 80)
