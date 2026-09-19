"""Astrolabe · 冒烟：**服务端拉取源码**（`B153`）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_fetch.py"

★★★ 重点验证**五件最要命的事**（★ **解压是攻击面** —— 这四条都是真会被利用的）：

1. ★★★ **路径穿越** —— 成员名写成 `../../app/core/models.py` ⇒ **必须丢弃**
2. ★★★ **解压炸弹** —— 成员**声称 `size=1` 却流出很多字节** ⇒ ⚠ **只有"边写边数"拦得住**
3. ★★★ **符号链接** —— 解出一个指向 `/etc` 的链接 ⇒ **必须跳过**
4. ★★ **超限 ⇒ 中止 + 清理**（⚠ 不留半个仓库）
5. ★★ **`size` 的单位是 KB**（⚠ 忘了乘 1024 会把上限放宽 1000 倍）
"""

import io
import os
import shutil
import tarfile

from django.conf import settings as dj
from django.contrib.auth import get_user_model
from django.test import override_settings

from core import fetch, storage, submission
from core.models import ProjectStorage
from core.refs import new_project_ref

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


U = get_user_model()

# ★★ 存储根指向 bind mount 内（⚠ `/tmp` 各容器私有 —— B149 踩过）
SMOKE_ROOT = "/app/.smoke_store"
dj.ASTROLABE_STORAGE_ROOT = SMOKE_ROOT
_ctx = override_settings(ALLOWED_HOSTS=["testserver"])
_ctx.enable()

shutil.rmtree(SMOKE_ROOT, ignore_errors=True)


# ---------------------------------------------------------------- 造 archive
def build_tar(entries, *, prefix="repo-abc123/"):
    """★ 造一个内存里的 tar.gz（★ 用来精确构造各种**恶意形态**）。

    `entries`: `[(名字, 内容 or None, 类型)]`，类型 `"f"` 普通文件 / `"l"` 符号链接。
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "l":
                info.type = tarfile.SYMTYPE
                info.linkname = content or "/etc"
                info.size = 0
                tar.addfile(info)
            else:
                data = content or b""
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeFetcher:
    """★ 假的 archive 下载（★ 可精确控制响应头与体积）。"""

    def __init__(self, payload: bytes, *, status=200, content_length=None):
        self.payload = payload
        self.status = status
        self.content_length = len(payload) if content_length is None else content_length
        self.calls: list[str] = []

    def get_json(self, url, *, headers=None):  # noqa: ARG002
        return {}

    def open_stream(self, url, *, headers=None):  # noqa: ARG002
        self.calls.append(url)
        return fetch.StreamResponse(
            status=self.status,
            content_length=self.content_length,
            body=io.BytesIO(self.payload),
            final_url=url,
        )


# ===========================================================================
print("=" * 80)
print("① ★★★ 成员路径清洗（路径穿越 / 绝对路径 / 顶层剥离 / 噪音目录）")
print("=" * 80)
cases = [
    ("★ 正常成员", "repo-abc/src/main.py", "src/main.py"),
    ("★ 剥掉顶层目录", "repo-abc/LICENSE", "LICENSE"),
    ("★★★ `../` 穿越 ⇒ 丢弃", "repo-abc/../../app/core/models.py", None),
    ("★★★ 深层穿越 ⇒ 丢弃", "repo-abc/src/../../../../etc/passwd", None),
    ("★★★ 绝对路径 ⇒ 丢弃", "/etc/passwd", None),
    ("★★ 只遍历顶层 ⇒ 丢弃", "repo-abc/", None),
    ("★ 噪音目录 .git ⇒ 丢弃", "repo-abc/.git/config", None),
    ("★ 噪音目录 node_modules ⇒ 丢弃", "repo-abc/node_modules/x/y.js", None),
    ("★ 反斜杠风格 ⇒ 当分隔符", "repo-abc\\src\\a.py", "src/a.py"),
    ("★ 反斜杠穿越 ⇒ 丢弃", "repo-abc/..\\..\\etc", None),
]
for label, given, want in cases:
    check(label, fetch._safe_member_path(given), want)

# ===========================================================================
print()
print("=" * 80)
print("② ★★★ 完整拉取：能解、能计数、能记账")
print("=" * 80)
u, _ = U.objects.get_or_create(username="smoke_fetch_user")   # ⚠ 可重复运行
u.set_unusable_password()
u.save()
ProjectStorage.objects.filter(owner=u).delete()               # ★ 清掉上一轮的记账
# ⚠★ **也要清掉上一轮的提交流水** —— 否则日额度会被前几轮吃掉，
#   ⑤ 的发布会**因为"限额"失败**（★ 而那与本节要测的东西毫无关系，⚠ 会误诊）
from core.models import ProjectReview  # noqa: E402

ProjectReview.objects.filter(submitted_by=u).delete()
pf = submission.ensure_profile(u)
pf.quota_override = {
    "storage_bytes_max": 10 * 1024 * 1024,
    "storage_files_max": 1000,
    "project_per_day": 0,          # ★ 本节测的是【拉取】，❌ 不是限额
    "project_per_week": 0,
}
pf.save(update_fields=["quota_override"])

ref = new_project_ref()
tar = build_tar([
    ("repo-abc/", None, "f"),
    ("repo-abc/src/main.py", b"def foo():\n    return 1\n", "f"),
    ("repo-abc/src/util.py", b"def bar():\n    return 2\n", "f"),
    ("repo-abc/LICENSE", b"MIT License", "f"),
    ("repo-abc/.git/objects/huge", b"z" * 50000, "f"),      # ★ 应被跳过
    ("repo-abc/evil", "/etc", "l"),                          # ★ 符号链接，应被跳过
    ("repo-abc/../../escape.txt", b"pwned", "f"),            # ★ 穿越，应被丢弃
])
f = FakeFetcher(tar)
r = fetch.fetch_archive(ref, "github", "o/r", owner=u, fetcher=f,
                        max_bytes=10**7, max_files=1000)
check("拉取成功", r.ok, True)
check("★ 只解出 3 个真源码文件（.git/符号链接/穿越都被丢弃）", r.files, 3)
check("★ 跳过计数 = 4（.git · 符号链接 · 穿越 · 顶层目录项）", r.skipped, 4)
check("★ 字节数是源码的 59B（不是那 50KB .git）", r.bytes, 59)
check("★ 顶层目录被剥掉了（main.py 在 src/ 下）",
      os.path.isfile(os.path.join(storage.project_dir(ref), "src", "main.py")), True)
check("★★★ 穿越文件【没有】被写到存储空间外",
      os.path.exists("/app/escape.txt"), False)
check("★★ 也没有解出 evil 这个链接",
      os.path.exists(os.path.join(storage.project_dir(ref), "evil")), False)
check("★ 记账已写（★ 与落盘同一次调用）", storage.project_usage(ref), (59, 3))
check("★ 用的确实是 archive 地址（github ⇒ codeload）",
      f.calls and "codeload.github.com" in f.calls[0], True)

# ===========================================================================
print()
print("=" * 80)
print("③ ★★★ 解压炸弹：成员【声称 size=1】却流出大量字节")
print("=" * 80)
# ★ 正常 tarfile 会按 size 截断 —— ★ 所以我们**用手工的伪造流**来模拟
#   （⚠ 真实攻击是构造一个 size 字段与实际数据不一致的包）
ref2 = new_project_ref()
bomb = build_tar([("repo-x/big.bin", b"a" * 100, "f")])
# ★ 直接测 `_copy_limited`（★ 那才是"边写边数"的落点）
out = io.BytesIO()
try:
    fetch._copy_limited(io.BytesIO(b"a" * 10_000), out, max_bytes=1000, already=0)
    check("★★★ 边写边数 ⇒ 超限抛 _Abort", "没抛", "_Abort")
except fetch._Abort:
    check("★★★ 边写边数 ⇒ 超限抛 _Abort（⚠ 不信 size 字段）", "_Abort", "_Abort")

# ★ 端到端：超过 max_bytes ⇒ 中止 + 清理
r2 = fetch.fetch_archive(ref2, "github", "o/r", owner=u, fetcher=FakeFetcher(bomb),
                         max_bytes=50, max_files=1000)
check("★★ 超过上限 ⇒ 拒绝", r2.ok, False)
check("★ 原因码 = storage_full", r2.reason_code, storage.CODE_BYTES)
check("★★★ 目录已被清掉（不留半个仓库）",
      os.path.isdir(storage.project_dir(ref2)), False)
check("★★ 记账也没写", storage.project_usage(ref2), (0, 0))

# ---- 文件数超限 ----
ref3 = new_project_ref()
r3 = fetch.fetch_archive(ref3, "github", "o/r", owner=u, fetcher=FakeFetcher(tar),
                         max_bytes=10**7, max_files=1)
check("★ 文件数超限 ⇒ 拒绝", r3.ok, False)
check("★ 原因码 = storage_files_full", r3.reason_code, storage.CODE_FILES)
check("★ 同样清干净了", os.path.isdir(storage.project_dir(ref3)), False)

# ---- Content-Length 早拒（★ 下载之前就判）----
ref4 = new_project_ref()
r4 = fetch.fetch_archive(ref4, "github", "o/r", owner=u,
                         fetcher=FakeFetcher(tar, content_length=999_999_999),
                         max_bytes=1000, max_files=1000)
check("★★ Content-Length 过大 ⇒ 早拒", r4.ok, False)
check("★ 原因码 = storage_full", r4.reason_code, storage.CODE_BYTES)
check("★ 提示里用了压缩包大小（不是「解压后」）", "压缩包" in r4.message, True)

# ===========================================================================
print()
print("=" * 80)
print("④ ★★ 第三道闸门：用仓库元数据里的 `size` 预判（★ 零额外请求）")
print("=" * 80)
v = fetch.check_remote_size({"size": 1024}, remaining_bytes=100 * 1024 * 1024)
check("★ 1MB 的仓库放进 100MB 空间 ⇒ 放行", v.ok, True)
check("★★ 且换算乘了 1024 × 0.8（size 单位是 KB）", v.bytes, int(1024 * 1024 * 0.8))

v = fetch.check_remote_size({"size": 100 * 1024}, remaining_bytes=10 * 1024 * 1024)
check("★★ 100MB 的仓库放进 10MB ⇒ 拒绝", v.ok, False)
check("★ 原因码 = storage_full", v.reason_code, storage.CODE_BYTES)
check("★ 提示里给了「还差多少」", "超过你还剩" in v.message, True)

v = fetch.check_remote_size({}, remaining_bytes=1000)
check("★★ 对方没给 size ⇒ 【不拦】（★ 交给下一道硬闸门）", v.ok, True)
check("★ 且标明 unknown", v.known, False)

# ★★ **方向**测试：刚好卡线的仓库应该**放过**（★ 宁可放过，⚠ 后面还有硬闸门）
#   ⚠ 这一条曾经抓到过"注释说放过、代码却更容易拒"的**方向性错误**
v = fetch.check_remote_size({"size": 100}, remaining_bytes=100 * 1024)
check("★★ 刚好卡线的仓库 ⇒ 放过（★ 0.8 保守系数，方向是「宁可放过」）", v.ok, True)
v = fetch.check_remote_size({"size": 100}, remaining_bytes=20 * 1024)
check("★★ 明显放不下 ⇒ 仍然拒绝（★ 「宽松」不能宽松到不管）", v.ok, False)

# ===========================================================================
print()
print("=" * 80)
print("⑤ ★★ 作业端到端：payload 里【没有 path】⇒ 作业自己拉 ⇒ 解析出图")
print("=" * 80)
from core import publish  # noqa: E402
from graph.models import Node  # noqa: E402
from jobs.models import Job  # noqa: E402
from jobs.tasks import execute  # noqa: E402

PID = 840001
from core.models import OAuthIdentity  # noqa: E402

OAuthIdentity.objects.filter(user=u).delete()
OAuthIdentity.objects.create(user=u, provider="github", provider_user_id=str(PID), login="x")


class RepoFetcher:
    """★ 归属校验用的假 fetcher（★ 顺带带上 `size`）。"""

    def __init__(self, size_kb=1):
        self.size_kb = size_kb

    def get_json(self, url, *, headers=None):  # noqa: ARG002
        return {"id": 1, "full_name": "o/r", "fork": False, "size": self.size_kb,
                "owner": {"id": PID, "login": "o", "type": "User"}}


src_tar = build_tar([
    ("repo-z/main.py", b"def foo():\n    return bar()\n\n\ndef bar():\n    return 1\n", "f"),
    ("repo-z/LICENSE", b"MIT License\n\nPermission is hereby granted, free of charge", "f"),
])
# ★ 把"拉取"的假 fetcher 装到模块默认值上（⚠ 作业里没有注入点）
fetch._default_fetcher = FakeFetcher(src_tar)

pub = publish.publish_project(
    u, provider="github", access_token="t", repo_full_name="o/r",
    # ★★ **不给 source_path** —— 普通用户的真实形态
    source_path="", fetcher=RepoFetcher(),
)
if not pub.ok:
    # ★ 失败时把原因打出来 —— ⚠ 否则只能看到"ok=False"，★ 得回去猜是哪一道闸门
    print(f"     [诊断] 发布被拦：{pub.reason_code} —— {pub.message[:100]}")
check("★ 发布受理", pub.ok, True)
check("★★ 走了「仓库大小预检」这一步", "remote_size" in pub.steps, True)
check("★ 作业 payload 里有 provider", pub.job.payload.get("provider"), "github")
check("★ 作业 payload 里有 repo_full_name", pub.job.payload.get("repo_full_name"), "o/r")
check("★★★ 作业 payload 里【没有】path（★ 说明源码要靠拉取）", pub.job.payload.get("path"), "")

job = Job.objects.get(pk=pub.job.pk)
execute(job)
job.refresh_from_db()
check("★★ 作业归宿 = parsed", job.payload.get("outcome"), "parsed")
check("★★★ 图真的出来了（源码是作业自己拉的）",
      Node.objects.filter(project_ref=pub.project_ref).count() > 0, True)
check("★ 源码落在存储空间里",
      os.path.isfile(os.path.join(storage.project_dir(pub.project_ref), "main.py")), True)
check("★★ 且已记账", storage.project_usage(pub.project_ref)[1] >= 2, True)

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★ repo_url → owner/repo 反推（★ 一处写好、一处测）")
print("=" * 80)
for url, want in [
    ("https://github.com/owner/repo", "owner/repo"),
    ("https://github.com/owner/repo.git", "owner/repo"),
    ("https://gitee.com/a/b/", "a/b"),
    ("https://github.com/owner/repo/tree/main", "owner/repo"),
    ("", ""),
    ("not a url", ""),
]:
    check(f"★ {url!r}", fetch.repo_full_from_url(url), want)

# ===========================================================================
# 清理
shutil.rmtree(SMOKE_ROOT, ignore_errors=True)
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
