"""Astrolabe · 冒烟：**用户存储空间**（`B152`）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_storage.py"

★★★ 重点验证**五件最要命的事**：

1. ★★★ **路径只能由 `project_ref` 派生**（★ 结构上不可穿越）
2. ★★★ **超限必须【中止 + 清理】**（⚠ 不能留下半个仓库 —— 那反而更占空间）
3. ★★ **`.git` 必须跳过**（⚠ 它常占仓库一大半，而我们对它毫无用处）
4. ★★ **软链接不跟随**（⚠ 否则一个指向 `/` 的链接就变成"无限大仓库"）
5. ★★★ **`source_path` 不再对普通用户开放**（★ 否则能读容器里任何目录）
"""

import os
import shutil
import tempfile

from django.conf import settings as dj
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from core import appsettings, publish, storage, submission
from core.models import OAuthIdentity, Project, ProjectStorage
from web import auth

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


U = get_user_model()
PROVIDER = "github"
_PID = [830000]

# ★★ 存储根目录指到**共享挂载内**（`/app` 是 bind mount —— B149 踩过 `/tmp` 各容器私有的坑）
SMOKE_ROOT = "/app/.smoke_store"
dj.ASTROLABE_STORAGE_ROOT = SMOKE_ROOT
dj.ASTROLABE_OAUTH = {
    "github": {"client_id": "cid", "client_secret": "sec"},
    "gitee": {"client_id": "cid", "client_secret": "sec"},
}
dj.ASTROLABE_BASE_URL = "http://test.local"
dj.ASTROLABE_SPA_URL = "http://spa.test/"
dj.ASTROLABE_ALLOWED_ORIGINS = ("http://spa.test",)


def make_source(*, with_git=True, with_link=False, size_kb=0):
    """★ 造一份"源码"（★ 含 `.git` 与软链接这两个陷阱）。"""
    d = tempfile.mkdtemp(prefix="src_", dir="/app/.smoke_tmp")
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    with open(os.path.join(d, "src", "main.py"), "w") as fh:
        fh.write("def foo():\n    return 1\n")
    with open(os.path.join(d, "LICENSE"), "w") as fh:
        fh.write("MIT License\n\nPermission is hereby granted, free of charge, to any person")
    if size_kb:
        with open(os.path.join(d, "big.bin"), "wb") as fh:
            fh.write(b"x" * (size_kb * 1024))
    if with_git:
        os.makedirs(os.path.join(d, ".git", "objects"), exist_ok=True)
        with open(os.path.join(d, ".git", "objects", "huge.bin"), "wb") as fh:
            fh.write(b"y" * 200_000)      # ★ 200KB 的"git 对象"
    if with_link:
        # ⚠★ 指向 `/etc` —— ★ 若不跳过软链接，这份"源码"会大得离谱
        os.symlink("/etc", os.path.join(d, "evil_link"))
    return d


admin, _ = U.objects.get_or_create(username="smoke_st_admin")
admin.is_superuser = admin.is_staff = True
admin.save(update_fields=["is_staff", "is_superuser"])

# ---- 清理 ----
os.makedirs("/app/.smoke_tmp", exist_ok=True)
for u in U.objects.filter(username__startswith="smoke_st_").exclude(pk=admin.pk):
    for pr in ProjectStorage.objects.filter(owner=u).values_list("project_ref", flat=True):
        storage.release(pr)
    Project.objects.filter(owner=u).delete()
    OAuthIdentity.objects.filter(user=u).delete()
    u.api_tokens.all().delete()
    u.delete()
shutil.rmtree(SMOKE_ROOT, ignore_errors=True)

_ctx = override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
_ctx.enable()


def fresh(name, *, override=None, tier="free"):
    _PID[0] += 1
    u, _ = U.objects.get_or_create(username=name)
    p = submission.ensure_profile(u)
    p.tier, p.quota_override = tier, (override or {})
    p.save(update_fields=["tier", "quota_override"])
    return u


# ===========================================================================
print("=" * 80)
print("① ★★★ 路径安全：只能由 project_ref 派生（结构上不可穿越）")
print("=" * 80)
okref = "proj_" + "a" * 32
check("★ 合法 ref ⇒ 路径落在存储根下",
      storage.project_dir(okref).startswith(SMOKE_ROOT), True)
for bad in ("../../etc", "proj_../../x", "/etc/passwd", "proj_ZZZ", "", "a/b"):
    try:
        storage.project_dir(bad)
        check(f"★★ 非法 ref {bad!r} ⇒ 应该 raise", "没抛", "ValueError")
    except ValueError:
        check(f"★★ 非法 ref {bad!r} ⇒ raise（❌ 不容错拼接）", "ValueError", "ValueError")

# ===========================================================================
print()
print("=" * 80)
print("② ★★ ingest：复制进存储空间 + 记账（★ 跳过 .git / 不跟软链接）")
print("=" * 80)
u = fresh("smoke_st_user")
src = make_source(with_git=True, with_link=True)

ref = okref
r = storage.ingest(ref, src, owner=u, max_bytes=10 * 1024 * 1024, max_files=100)
check("采集成功", r.ok, True)
# ★ 源码真实内容 = main.py(24B) + LICENSE(约 80B) —— ⚠ .git 的 200KB **不该被算进去**
check("★★ `.git` 被跳过（字节数远小于 200KB）", r.bytes < 1000, True)
check("★★ 软链接没被跟随（否则会是几 MB）", r.bytes < 1000, True)
check("★ 文件数 = 2（main.py + LICENSE）", r.files, 2)
check("★ 写进了存储目录", os.path.isdir(storage.project_dir(ref)), True)
check("★ 记账已写", storage.project_usage(ref), (r.bytes, 2))
check("★ 用户用量 = SUM", storage.usage_of(u), (r.bytes, 2))

# ★ 源码**原地保留**（★ 一期用 copy 而不是 move —— ⚠ move 会破坏调用方）
check("★ 源目录仍在（copy 不是 move）", os.path.isdir(src), True)

# ===========================================================================
print()
print("=" * 80)
print("③ ★★★ 超限 ⇒ 【中止 + 清理】（不留半个仓库）")
print("=" * 80)
u2 = fresh("smoke_st_user2")
ref2 = "proj_" + "b" * 32
src2 = make_source(size_kb=200, with_git=False)     # ★ 约 200KB

r2 = storage.ingest(ref2, src2, owner=u2, max_bytes=50 * 1024, max_files=100)
check("★★ 超过上限 ⇒ 拒绝", r2.ok, False)
check("★★ 原因码 = storage_full", r2.reason_code, storage.CODE_BYTES)
check("★★ 且给了可读原因（含「还剩多少」）", "复制过程中" in r2.message, True)
check("★★★ **没有留下半个仓库**（目录已被清掉）",
      os.path.isdir(storage.project_dir(ref2)), False)
check("★★ 记账也没写", storage.project_usage(ref2), (0, 0))

# ---- 文件数超限 ----
r3 = storage.ingest("proj_" + "c" * 32, src2, owner=u2, max_bytes=0, max_files=1)
check("★ 文件数超限 ⇒ 拒绝", r3.ok, False)
check("★ 原因码 = storage_files_full", r3.reason_code, storage.CODE_FILES)
check("★ 同样清干净了", os.path.isdir(storage.project_dir("proj_" + "c" * 32)), False)

# ===========================================================================
print()
print("=" * 80)
print("④ ★★ 容量判定 + ★★★ VIP 空间更大（用户要的「具体体现」）")
print("=" * 80)
cap_free = storage.check_capacity(u)
cap_vip = storage.check_capacity(fresh("smoke_st_vip", tier="vip"))
print(f"     free: {cap_free.limit_bytes / 1024 / 1024:.0f} MB   "
      f"vip: {cap_vip.limit_bytes / 1024 / 1024:.0f} MB")
check("★★★ VIP 的存储上限【明显更大】", cap_vip.limit_bytes > cap_free.limit_bytes * 5, True)
check("★ 判定带 used_ratio（前端画进度条）", 0 <= cap_free.used_ratio <= 1, True)

# ---- 管理员给个人放宽 ----
u3 = fresh("smoke_st_user3", override={"storage_bytes_max": 7 * 1024 * 1024 * 1024})
cap3 = storage.check_capacity(u3)
check("★★ 用户级覆盖生效（7GB）", cap3.limit_bytes, 7 * 1024 * 1024 * 1024)
check("★ 且标明来源是 user（便于排查）", cap3.source, "user")

# ---- 空间不足的提示 ----
u4 = fresh("smoke_st_user4", override={"storage_bytes_max": 10})
cap4 = storage.check_capacity(u4, add_bytes=1000)
check("★★ 空间不足 ⇒ 拒绝", cap4.ok, False)
check("★★ 原因码 = storage_full", cap4.reason_code, storage.CODE_BYTES)
check("★ 提示里建议了「删旧项目 或 升级 VIP」", "VIP" in cap4.message, True)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★★ source_path 不再对普通用户开放（★ 否则能读容器里任何目录）")
print("=" * 80)
targets = {
    "普通用户传 /etc ⇒ 降级为空": publish._safe_source_path("/etc", u),
    "普通用户传 /app ⇒ 降级为空": publish._safe_source_path("/app", u),
    "普通用户传存储空间内 ⇒ 放行": publish._safe_source_path(storage.project_dir(ref), u),
    "staff 传 /etc ⇒ 放行（内部调试）": publish._safe_source_path("/etc", admin),
    "空 ⇒ 空（★ 作业会明确失败：拉取尚未实现）": publish._safe_source_path("", u),
}
check("★★ /etc ⇒ 空（*关键*）", targets["普通用户传 /etc ⇒ 降级为空"], "")
check("★★ /app ⇒ 空（*关键*）", targets["普通用户传 /app ⇒ 降级为空"], "")
check("★ 存储空间内 ⇒ 放行", targets["普通用户传存储空间内 ⇒ 放行"],
      os.path.realpath(storage.project_dir(ref)))
check("★ staff ⇒ 放行", targets["staff 传 /etc ⇒ 放行（内部调试）"], "/etc")
check("★ 空 ⇒ 空", targets["空 ⇒ 空（★ 作业会明确失败：拉取尚未实现）"], "")

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★★ 发布时的容量预检（★ 早点失败，❌ 别让用户等到作业跑完才失败）")
print("=" * 80)


class FakeFetcher:
    def __init__(self, uid):
        self.uid = uid

    def get_json(self, url, *, headers=None):  # noqa: ARG002
        return {"id": 1, "full_name": "o/r", "fork": False,
                "owner": {"id": self.uid, "login": "o", "type": "User"}}


u5 = fresh("smoke_st_user5")
u5_pid = _PID[0]
OAuthIdentity.objects.create(
    user=u5, provider=PROVIDER, provider_user_id=str(u5_pid), login="x"
)

# ★★ 关键：**必须先真的占掉空间**（"已满"才判得出来）——
#   ⚠ 只把上限设小是**没用的**：★ 此刻还不知道仓库多大，
#     ★ 预检能准确判断的**只有"已经满了"**这一件事（见 `publish.py` 的两道闸门说明）。
r5 = storage.ingest("proj_" + "e" * 32, make_source(), owner=u5,
                    max_bytes=10**7, max_files=1000)
check("前提：先占了点空间", r5.bytes > 0, True)
p5 = submission.ensure_profile(u5)
p5.quota_override = {"storage_bytes_max": 1}      # ★ 1 字节 ⇒ **已满**
p5.save(update_fields=["quota_override"])

pub = publish.publish_project(
    u5, provider=PROVIDER, access_token="t", repo_full_name="o/r", source_path="",
    fetcher=FakeFetcher(u5_pid),     # ★ 仓库 owner 必须**与本人数字 ID 一致**，否则先被归属拦住
)
check("★★ 空间已满 ⇒ 发布被拦", pub.ok, False)
# ★ 注意顺序：**归属（Gate 0）在前，存储在後** —— ★ 这是刻意的：
#   ⚠ 归属过不了就不该往下走（★ 那些后续步骤都很贵）
check("★ 拦在 storage 这一步", pub.reason_code, storage.CODE_BYTES)
check("★★★ 且【没有建项目】（★ 不留孤儿）", Project.objects.filter(owner=u5).count(), 0)

# ===========================================================================
print()
print("=" * 80)
print("⑦ ★★ 释放 / 对账 / 用户侧接口")
print("=" * 80)
before = storage.usage_of(u)[0]
freed = storage.release(ref)
check("★★ 释放返回了释放的字节数", freed, before)
check("★ 目录真的没了", os.path.isdir(storage.project_dir(ref)), False)
check("★ 记账也没了", storage.project_usage(ref), (0, 0))
check("★ 用户用量归零", storage.usage_of(u)[0], 0)

# ---- 对账 ----
r6 = storage.ingest("proj_" + "d" * 32, make_source(), owner=u, max_bytes=10**7, max_files=100)
check("★ 对账：一致时返回空", storage.audit(), [])
# ★ 手工把记账改坏（模拟"进程被杀"那类分叉）
ProjectStorage.objects.filter(project_ref="proj_" + "d" * 32).update(bytes_used=999999)
bad = storage.audit()
check("★★ 对账能发现分叉", len(bad), 1)
storage.audit(fix=True)
check("★★ --fix 后恢复一致", storage.audit(), [])
check("★ 修正后的值与实测一致",
      ProjectStorage.objects.get(project_ref="proj_" + "d" * 32).bytes_used, r6.bytes)

# ---- 用户侧接口 ----
raw, _ = auth.issue_token(u)
c = Client(HTTP_AUTHORIZATION=f"Bearer {raw}")
resp = c.get("/api/me/storage/")
check("★ GET /api/me/storage/ ⇒ 200", resp.status_code, 200)
data = resp.json()["data"]
check("★ 含已用 / 上限 / 剩余", {"used_bytes", "limit_bytes", "remaining_bytes"} <= set(data), True)
check("★ 含单项目上限（★ 两个都要给前端）", "repo_bytes_max" in data, True)
check("★ 含每个项目的占用（★ 用户据此决定删哪个）", len(data["projects"]), 1)
check("★ 匿名 ⇒ 401", Client().get("/api/me/storage/").status_code, 401)

# ===========================================================================
# 清理
shutil.rmtree(SMOKE_ROOT, ignore_errors=True)
shutil.rmtree("/app/.smoke_tmp", ignore_errors=True)
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
