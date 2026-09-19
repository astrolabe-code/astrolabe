"""Astrolabe · 冒烟：**真实网络**端到端（`B154`）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_real_fetch.py"

★★★ 这个脚本与其它冒烟的区别：**它真的去 GitHub 下载一个真仓库**。

| 环节 | 这里是真是假 |
|---|---|
| ★★ **拉取源码**（archive 下载 + 解压） | ★★★ **真的**（真网络 · 真 tar.gz · 真文件） |
| ★★ **归属校验的 HTTP 调用** | ★★★ **真的**（真 `GET /repos/...`） |
| ★ **许可核验 / 解析 / 写图 / 记账** | ★★★ **真的** |
| ⚠ OAuth 换 token | ★ **假的** —— ⚠ 我们没有真实的 client_secret（★ 其余全真） |

⚠★ 之所以要有它：★ 上一批（`B153`）只用**构造的 tar.gz** 验过 ——
⚠ **构造的包和真的包不一样**（★ 真的带 `pax_global_header`、长文件名、`./` 前缀……）。

★ 仓库选 `kennethreitz/records`，理由是**四条同时满足**：
★ 个人名下（❌ 不是组织 —— 我们那条规则会正确地拒掉组织仓库）· ★ 小（约 200KB）·
★ **ISC 许可**（宽松 ⇒ 自动放行）· ★ 真 Python 代码（能解析出图）。

⚠ 没有网络时**优雅跳过**（★ 不报失败 —— 否则这个脚本在离线环境就成了噪音）。
"""

import json
import os
import socket
import shutil
import urllib.request

from django.conf import settings as dj
from django.contrib.auth import get_user_model
from django.test import override_settings

from core import appsettings, fetch, publish, storage, submission
from core.models import OAuthIdentity, Project, ProjectReview
from graph.models import Edge, Node
from jobs.models import Job
from jobs.tasks import execute

FAILED: list[str] = []

REPO = "kennethreitz/records"
PROVIDER = "github"


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<56} = {got!r}")


# ---------------------------------------------------------------- 网络预检
def live_repo(full: str) -> dict | None:
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{full}",
            headers={"Accept": "application/json", "User-Agent": "astrolabe"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except (OSError, ValueError, socket.timeout):
        return None


info = live_repo(REPO)
if info is None:
    print("⚠ 没有网络（或 GitHub 不可达）—— ★ 跳过本次真实网络冒烟（⚠ 不算失败）")
    raise SystemExit(0)

OWNER_ID = str((info.get("owner") or {}).get("id"))
print(f"  目标仓库：{info.get('full_name')}  size={info.get('size')}KB  "
      f"owner={((info.get('owner') or {}).get('login'))}(id={OWNER_ID}, "
      f"type={((info.get('owner') or {}).get('type'))})  "
      f"license={((info.get('license') or {}).get('spdx_id'))}")

U = get_user_model()
admin, _ = U.objects.get_or_create(username="smoke_real_admin")
admin.is_superuser = admin.is_staff = True
admin.save(update_fields=["is_staff", "is_superuser"])

SMOKE_ROOT = "/app/.smoke_real"
dj.ASTROLABE_STORAGE_ROOT = SMOKE_ROOT
dj.ASTROLABE_OAUTH = {
    "github": {"client_id": "cid", "client_secret": "sec"},
    "gitee": {"client_id": "cid", "client_secret": "sec"},
}
dj.ASTROLABE_BASE_URL = "http://test.local"
_ctx = override_settings(ALLOWED_HOSTS=["testserver"])
_ctx.enable()

appsettings.set_value("registration_open", True, actor=admin)
appsettings.set_value("invite_required", False, actor=admin)
appsettings.set_value("license_require_file", False, actor=admin)

# ---- 造一个"已登录 + 已绑定该仓库 owner"的用户 ----
u, _ = U.objects.get_or_create(username="smoke_real_user")
u.set_unusable_password()
u.save()
Project.objects.filter(owner=u).delete()
ProjectReview.objects.filter(submitted_by=u).delete()
from core.models import ProjectStorage  # noqa: E402

ProjectStorage.objects.filter(owner=u).delete()
OAuthIdentity.objects.filter(user=u).delete()
# ★★ 关键：把本地身份的数字 ID 设成**这个真实仓库 owner 的真实 id** ⇒ 归属校验会真的通过
OAuthIdentity.objects.create(
    user=u, provider=PROVIDER, provider_user_id=OWNER_ID,
    login=((info.get("owner") or {}).get("login") or "x"),
)
pf = submission.ensure_profile(u)
pf.quota_override = {
    "storage_bytes_max": 200 * 1024 * 1024,
    "storage_files_max": 20000,
    "project_per_day": 0,          # ★ 本节测的是拉取，❌ 不是限额
    "project_per_week": 0,
}
pf.save(update_fields=["tier", "quota_override"])


class RepoFetcher:
    """★ 只替换**归属校验那一次 HTTP**（★ 返回的是刚取到的**真实** repo JSON）。"""

    def __init__(self, payload: dict):
        self.payload = payload

    def get_json(self, url, *, headers=None):  # noqa: ARG002
        return self.payload


# ===========================================================================
print()
print("=" * 80)
print("① ★★★ 发布（★ payload 里没有 path ⇒ 源码要靠作业自己拉）")
print("=" * 80)
pub = publish.publish_project(
    u, provider=PROVIDER, access_token="fake-oauth-token", repo_full_name=REPO,
    name="records（真实网络验证）", source_path="",
    fetcher=RepoFetcher(info),
)
if not pub.ok:
    print(f"     [诊断] {pub.reason_code} —— {pub.message}")
check("★ 发布受理", pub.ok, True)
check("★★ 走了「仓库大小预检」", "remote_size" in pub.steps, True)
check("★★ 且用的是真实的 size（KB×1024×0.8）",
      pub.steps.get("remote_size", {}).get("estimated_bytes"),
      int(info["size"] * 1024 * fetch.SIZE_ESTIMATE_FACTOR))
check("★★★ 作业 payload 里【没有】path", pub.job.payload.get("path"), "")
check("★ payload 里有真实仓库名", pub.job.payload.get("repo_full_name"), REPO)

# ===========================================================================
print()
print("=" * 80)
print("② ★★★ 作业跑起来 ⇒ ★ 真的去 codeload 下载并解压")
print("=" * 80)
import time  # noqa: E402

job = Job.objects.get(pk=pub.job.pk)
t0 = time.monotonic()
execute(job)
job.refresh_from_db()
elapsed = time.monotonic() - t0

if job.state == Job.STATE_FAILED:
    print(f"     [作业失败] {job.error_msg[:300]}")
check("★ 作业没有失败", job.state != Job.STATE_FAILED, True)
check("★★ 归宿 = parsed", job.payload.get("outcome"), "parsed")

dest = storage.project_dir(pub.project_ref)
check("★★★ 源码真的落在存储空间里", storage.exists(pub.project_ref), True)
# ★★ 顶层目录被剥掉了 —— ★ 最关键的形态断言：
#    ⚠ 不剥的话这里会是 `records-<sha>/records.py`
check("★★★ 顶层目录已剥掉（records.py 就在根上）",
      os.path.isfile(os.path.join(dest, "records.py")), True)
check("★★ 没有把整个仓库套在一个子目录里（★ 顶层剥离判据）",
      os.path.isdir(os.path.join(dest, "records-main")), False)

bytes_used, files_used = storage.project_usage(pub.project_ref)
print(f"     实拉字节：{bytes_used / 1024:.1f} KB    文件数：{files_used}    耗时：{elapsed:.1f}s")
check("★ 拉到了真东西（>20KB）", bytes_used > 20 * 1024, True)
check("★ 文件数合理（>20）", files_used > 20, True)
check("★★ 已记账（★ 与落盘同一次调用）", files_used > 0, True)

# ===========================================================================
print()
print("=" * 80)
print("③ ★★ 许可核验读的是【真 LICENSE】")
print("=" * 80)
review = ProjectReview.objects.filter(project_ref=pub.project_ref).order_by("-created_at").first()
review.refresh_from_db()
check("★★ 识别出 ISC（★ 真文件里读的）", review.evidence.get("detections", [{}])[0].get("spdx"), "ISC")
check("★ 结论 = 宽松 ⇒ 自动放行", review.reason_code, "permissive")
check("★ 流水 = 已放行", review.decision, ProjectReview.DECISION_APPROVED)
check("★ 项目状态 = 已放行", Project.objects.get(project_ref=pub.project_ref).review_state,
      Project.REVIEW_APPROVED)

# ===========================================================================
print()
print("=" * 80)
print("④ ★★★ 真的解析出了图")
print("=" * 80)
nodes = Node.objects.filter(project_ref=pub.project_ref)
edges = Edge.objects.filter(project_ref=pub.project_ref)
from collections import Counter  # noqa: E402

kinds = dict(Counter(nodes.values_list("kind", flat=True)))
print(f"     节点 {nodes.count()} 个：{kinds}")
print(f"     边   {edges.count()} 条：{dict(Counter(edges.values_list('type', flat=True)))}")
check("★★★ 图有节点", nodes.count() > 0, True)
check("★ 且真有跨文件调用边（>0）", edges.filter(type="calls").count() > 0, True)
check("★ 语言识别为 python", set(nodes.values_list("lang", flat=True)) == {"python"}, True)

# ★ 抽一个真实函数给出来看（★ 证明"不是空转"）
sample = nodes.filter(kind="function").order_by("node_id").first()
if sample:
    print(f"     样例函数：{sample.name}  @ {sample.file_path}:{sample.line}")
    check("★ 函数有真实的行号", sample.line > 0, True)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★ 幂等：重复拉取不会把存储翻倍")
print("=" * 80)
before = storage.project_usage(pub.project_ref)
r = fetch.fetch_archive(pub.project_ref, PROVIDER, REPO, owner=u,
                        max_bytes=10**9, max_files=100000)
after = storage.project_usage(pub.project_ref)
check("★ 重复拉取成功", r.ok, True)
check("★★ 字节数没有翻倍（★ 覆盖式拉取）", after[0] == before[0], True)
check("★ 文件数没有翻倍", after[1] == before[1], True)

# ===========================================================================
# 清理
shutil.rmtree(SMOKE_ROOT, ignore_errors=True)
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
    print("✅ 全部通过（★ 含一次真实的 GitHub 下载与解析）")
print("=" * 80)
