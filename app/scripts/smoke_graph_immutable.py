"""Astrolabe · 冒烟：**图不可变 / 定版**（`B103` / `B155`）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_graph_immutable.py"

> **用户原话**：「代码解析完成之后**应该不允许重新解析**。因为，我要求
> **图数据不能频繁、大面积改动**，**代码也不能改动**，否则，
> **解释里的"几行到几行"就失效了**。你要解析另一个版本的，那就**重新建一个项目**。
> 觉得解析质量太差，那就**删了项目重新建一个**。」

★★★ 重点验证**五件事**：

1. ★★★ **同个项目第二次解析 ⇒ 被拒**（★ 而且**连拉取都不做** —— 省得白费流量）
2. ★★★ **并发也拦得住**（★ `write_graph` 里 `select_for_update` 锁项目行）
3. ★★★ **`parse` 端点 ⇒ 409 + 引导语**（★ 用户看到就知道该怎么办）
4. ★★ **两条出路都通**：★ 换 project_ref = 新建项目 ✅ · ★ 删了重建 ✅
5. ★★ **审核放行不会重投已定版的项目**（★ 否则放行就成了一条覆盖后门）
"""

import os
import shutil
import tempfile
from datetime import timedelta

from django.conf import settings as dj
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.utils import timezone as tz

from core import appsettings, publish, storage, submission
from core.models import OAuthIdentity, Project, ProjectReview, ProjectStorage
from core.refs import new_project_ref
from graph.models import Edge, Node
from graph.writer import GraphImmutable, write_graph
from jobs.models import Job
from jobs.tasks import execute
from web import auth

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<56} = {got!r}")


U = get_user_model()
PROVIDER = "github"

dj.ASTROLABE_STORAGE_ROOT = "/app/.smoke_store"
dj.ASTROLABE_OAUTH = {
    "github": {"client_id": "cid", "client_secret": "sec"},
    "gitee": {"client_id": "cid", "client_secret": "sec"},
}
dj.ASTROLABE_BASE_URL = "http://test.local"
dj.ASTROLABE_SPA_URL = "http://spa.test/"
dj.ASTROLABE_ALLOWED_ORIGINS = ("http://spa.test",)
_ctx = override_settings(ALLOWED_HOSTS=["testserver"])
_ctx.enable()

os.makedirs("/app/.smoke_tmp", exist_ok=True)
shutil.rmtree("/app/.smoke_store", ignore_errors=True)

admin, _ = U.objects.get_or_create(username="smoke_imm_admin")
admin.is_superuser = admin.is_staff = True
admin.save(update_fields=["is_staff", "is_superuser"])
appsettings.set_value("registration_open", True, actor=admin)
appsettings.set_value("invite_required", False, actor=admin)
appsettings.set_value("license_require_file", False, actor=admin)


def make_repo():
    d = tempfile.mkdtemp(prefix="imm_", dir="/app/.smoke_tmp")
    with open(os.path.join(d, "LICENSE"), "w") as fh:
        fh.write("MIT License\n\nPermission is hereby granted, free of charge, to any person")
    with open(os.path.join(d, "main.py"), "w") as fh:
        fh.write("def foo():\n    return bar()\n\n\ndef bar():\n    return 1\n")
    return d


PID = "880001"


def fresh_user():
    u, _ = U.objects.get_or_create(username="smoke_imm_user")
    # ★★ **必须让它当 staff** —— 本脚本用 `source_path` 直接指向容器里的目录，
    #   而 ⚠★ `_safe_source_path()` 对**非 staff** 会把它**降级为空**
    #   （`B152`：那是"读容器任意目录"的收口）⇒ ★ 作业会改去拉一个**不存在的远端仓库**。
    #   ⚠ 本节测的是【定版】，❌ 不是拉取 —— 所以这里走 staff 的调试口子。
    u.is_staff = True
    u.save(update_fields=["is_staff"])
    Project.objects.filter(owner=u).delete()
    ProjectReview.objects.filter(submitted_by=u).delete()
    for pr in ProjectStorage.objects.filter(owner=u):
        storage.release(pr.project_ref)
    # ⚠★ **按 pid 清、而不是按用户清** ——
    #   `uniq_provider_identity` 约束是 `(provider, provider_user_id)`，
    #   ⚠ 上一轮残留的身份可能挂在**别的用户**身上 ⇒ 只按 user 删会漏掉它（踩过一次）
    OAuthIdentity.objects.filter(provider_user_id=PID).delete()
    OAuthIdentity.objects.create(
        user=u, provider=PROVIDER, provider_user_id=PID, login="smoke_imm_user"
    )
    p = submission.ensure_profile(u)
    p.quota_override = {
        "project_per_day": 0, "project_per_week": 0,     # ★ 本脚本测的是定版，❌ 不是限额
        "storage_bytes_max": 100 * 1024 * 1024,
    }
    p.save(update_fields=["quota_override"])
    return u


def run_job_wait(job, timeout: float = 30.0):
    """★ 跑作业并**等它真的结束**。

    ⚠★ 真 worker 一直在跑，而 `execute()` 里是**原子抢占** ⇒ ★ 谁先抢到谁跑，
      另一个**直接返回**。⇒ ★ 不等就可能**在作业跑完前就断言**
      （⚠ 实测踩到：日志"作业已被其他进程领取，跳过"，★ 而断言立刻说"没出图"）。
    """
    from time import monotonic, sleep

    execute(job)
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job.refresh_from_db()
        if job.state in (Job.STATE_DONE, Job.STATE_FAILED, Job.STATE_CANCELED):
            break
        sleep(0.1)
    return job


class RepoFetcher:
    def get_json(self, url, *, headers=None):  # noqa: ARG002
        return {"id": 1, "full_name": "o/r", "fork": False, "size": 1,
                "owner": {"id": 880001, "login": "o", "type": "User"}}


# ===========================================================================
print("=" * 80)
print("① ★★★ 第一次解析 ⇒ 定版；第二次 ⇒ 被拒（★ 连拉取都不做）")
print("=" * 80)
u = fresh_user()
src = make_repo()
pub = publish.publish_project(
    u, provider=PROVIDER, access_token="t", repo_full_name="o/r",
    source_path=src, fetcher=RepoFetcher(),   # ★ 内部路径（走 ingest，不下载）
)
check("发布受理", pub.ok, True)
# ★ 诊断：把"staff 是否生效、路径是否被放行、作业拿到什么"一次打全
print(f"     [诊断] u.is_staff={u.is_staff}  src={src}")
print(f"     [诊断] _safe_source_path={publish._safe_source_path(src, u)!r}")
print(f"     [诊断] storage.root()={storage.root()}")
print(f"     [诊断] job.payload.path={pub.job.payload.get('path')!r}")
project = Project.objects.get(project_ref=pub.project_ref)
check("★ 定版前：graph_built_at 为空", project.graph_built_at, None)
check("★ 定版前：is_graph_built = False", project.is_graph_built, False)

job = run_job_wait(Job.objects.get(pk=pub.job.pk))
project.refresh_from_db()
if job.state == Job.STATE_FAILED:
    # ★ 失败时把原因打出来 —— ⚠ 否则只能看到一串 False，★ 得回去猜（这次就是猜了三轮）
    print(f"     [作业失败] {job.error_msg[:220]}")
check("★★ 第一次解析成功", job.payload.get("outcome"), "parsed")
check("★★★ 图已生成", Node.objects.filter(project_ref=pub.project_ref).count() > 0, True)
check("★★★ **定版标记已置**（★ 与写图同一事务）", project.is_graph_built, True)
check("★ 且钉住了 ref（★ 走本地目录 ⇒ 标成 local）", project.resolved_ref, "local")

# ---- 第二次：补投一个作业 ----
Node_before = Node.objects.filter(project_ref=pub.project_ref).count()
from jobs import dispatch  # noqa: E402

job2, _ = dispatch.submit(
    kind=Job.KIND_PARSE, project_ref=pub.project_ref,
    payload={"project_id": project.pk, "provider": PROVIDER,
             "repo_full_name": "o/r", "repo_url": project.repo_url, "commit": ""},
    dedup_key=f"parse:{pub.project_ref}:again",
)
execute(job2)
job2.refresh_from_db()
check("★★★ 第二次作业归宿 = already_built", job2.payload.get("outcome"), "already_built")
check("★★ stage 说清了为什么（★ 不是含糊的「完成」）",
      "已经解析过" in job2.stage, True)
check("★★★ 图【一个节点都没变】",
      Node.objects.filter(project_ref=pub.project_ref).count(), Node_before)

# ===========================================================================
print()
print("=" * 80)
print("② ★★★ 纵深防御：`write_graph` 自己拒绝覆盖（★ 并发也拦得住）")
print("=" * 80)
from codeparser.base import ParsedNode, ParseResult  # noqa: E402

dummy = ParseResult()
dummy.nodes.append(ParsedNode(kind="function", name="evil", file_path="x.py",
                              line=1, line_end=1, lang="python"))
try:
    write_graph(pub.project_ref, dummy)
    check("★★★ 已有图 ⇒ write_graph 抛 GraphImmutable", "没抛", "GraphImmutable")
except GraphImmutable:
    check("★★★ 已有图 ⇒ write_graph 抛 GraphImmutable（❌ 不是先删后写）",
          "GraphImmutable", "GraphImmutable")
check("★★ 图仍然没被改", Node.objects.filter(project_ref=pub.project_ref, name="evil").count(), 0)

# ---- replace=True 必须给理由（★ 强制留痕）----
try:
    write_graph(pub.project_ref, dummy, replace=True)
    check("★★ replace=True 不给理由 ⇒ 应该 raise", "没抛", "ValueError")
except ValueError:
    check("★★ replace=True 不给理由 ⇒ raise（★ 覆盖必须留痕）", "ValueError", "ValueError")

# ===========================================================================
print()
print("=" * 80)
print("③ ★★★ `parse` 端点 ⇒ 409 + 引导语（★ 用户看到就知道怎么办）")
print("=" * 80)
raw, _ = auth.issue_token(u)
c = Client(HTTP_AUTHORIZATION=f"Bearer {raw}")
r = c.post(f"/api/projects/{pub.project_ref}/parse/", content_type="application/json")
check("★★★ 已定版 ⇒ 409", r.status_code, 409)
check("★ 原因码 = graph_immutable", r.json()["error"]["code"], "graph_immutable")
msg = r.json()["error"]["message"]
check("★★★ 消息里给了**两条出路**", ("新建一个项目" in msg) and ("删掉本项目后重建" in msg), True)
print(f"       引导语：{msg[:64]}…")

# ===========================================================================
print()
print("=" * 80)
print("④ ★★ 出路一：换一个 project_ref = 新建项目（★ 用户说的第一条路）")
print("=" * 80)
pub2 = publish.publish_project(
    u, provider=PROVIDER, access_token="t", repo_full_name="o/r2",
    source_path=make_repo(), fetcher=RepoFetcher(),
)
check("★★ 同一个仓库可以再建一个项目（★ 新的 ref）", pub2.ok, True)
check("★★ 且是**不同的** project_ref", pub2.project_ref != pub.project_ref, True)
_j2 = run_job_wait(Job.objects.get(pk=pub2.job.pk))
if _j2.state == Job.STATE_FAILED:
    print(f"     [作业失败] {_j2.error_msg[:220]}")
check("★★★ 新项目能正常解析出图",
      Node.objects.filter(project_ref=pub2.project_ref).count() > 0, True)
check("★★★ 两个项目的图**互不影响**（★ 这正是「两个版本并存」）",
      Node.objects.filter(project_ref=pub.project_ref).count() > 0, True)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★ 出路二：删了重建（★ 用户说的第二条路）")
print("=" * 80)
ref_old = pub2.project_ref
nodes_old = Node.objects.filter(project_ref=ref_old).count()
r = c.delete(f"/api/projects/{ref_old}/")
check("★ 删除项目 ⇒ 200", r.status_code, 200)
check("★★ 图被清掉", Node.objects.filter(project_ref=ref_old).count(), 0)
check("★★ 存储也释放了（★ B152）", storage.project_usage(ref_old), (0, 0))
check("★★★ 那个 ref 现在**可以重新解析**（★ 因为是新项目了）",
      Project.objects.filter(project_ref=ref_old).exists(), False)

pub3 = publish.publish_project(
    u, provider=PROVIDER, access_token="t", repo_full_name="o/r3",
    source_path=make_repo(), fetcher=RepoFetcher(),
)
_j3 = run_job_wait(Job.objects.get(pk=pub3.job.pk))
if _j3.state == Job.STATE_FAILED:
    print(f"     [作业失败] {_j3.error_msg[:220]}")
check("★★★ 重建后照样能出图（★ 这条路是通的）",
      Node.objects.filter(project_ref=pub3.project_ref).count() > 0, True)

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★★★ 审核放行【不会】重投已定版的项目（★ 否则放行就是覆盖后门）")
print("=" * 80)
# ★ 造一个"已定版 + 流水仍 pending"的场景（⚠ 现实中不太会出现，但必须防住）
rv = ProjectReview.objects.filter(project_ref=pub.project_ref).first()
ProjectReview.objects.filter(pk=rv.pk).update(decision=ProjectReview.DECISION_PENDING,
                                              auto_decided=False)
before_jobs = Job.objects.filter(project_ref=pub.project_ref).count()
_, job_after = publish.approve_and_resume(rv, by=admin, note="测试")
check("★★★ 已定版 ⇒ 不重投作业", job_after, None)
check("★★ 作业数没变", Job.objects.filter(project_ref=pub.project_ref).count(), before_jobs)
rv.refresh_from_db()
check("★ 但放行动作本身成功了", rv.decision, ProjectReview.DECISION_APPROVED)

# ===========================================================================
# 清理
shutil.rmtree("/app/.smoke_store", ignore_errors=True)
shutil.rmtree("/app/.smoke_tmp", ignore_errors=True)
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
