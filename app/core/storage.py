"""Astrolabe · 共享内核：**用户存储空间**（`B152`）

> **用户原话**：「要设立一个**用户存储空间**，用来放用户的源码项目，
> 要是**源码太大，占了太多空间，就不好了**。这样也可以**间接限制图数据的大小**。
> 这也可以是 **VIP 用户的存储空间更大的具体体现**。」

---

# ★★ 这个设计同时解决了三个问题（用户想得比表面更远）

| # | 解决了什么 |
|---|---|
| **1** | ★ **磁盘不会被打爆** —— ★ 用户**自己**的配额，⚠ 不是全站共用一个池子（★ 那样一个人就能拖垮所有人） |
| **2** | ★★ **间接限制图数据大小** —— ★ 图来自源码，★ 源码就那么多，图不可能无限大 |
| **3** | ★★★ **VIP 的"更大"有了具体形态** —— ★ 符合 `U1` 铁律：**只是额度更大，❌ 不是能看更多** |

---

# ⚠★★ 顺带堵掉一个**真实的安全隐患**

★ 在这之前，`publish` 接受一个**用户可控的 `source_path`**（一期权宜）——
⚠★ 那意味着**用户能让服务端去读容器里的任何目录**（`/etc`、别的用户的项目…），
★ 而这台机器上还跑着数据库。

⇒ ★★ 本模块把入口**收成一条**：★ **源码必须先进"用户存储空间"**，
  ★ 作业只从那个目录里读 —— ★ **调用方再也传不进任意路径**。

---

# ★★ 一条硬纪律：路径**只能由 `project_ref` 派生**

★ `project_ref` = `proj_[0-9a-f]{32}` ⇒ ★ **天然不含 `/` 与 `..`**
⇒ ★★ **路径穿越在结构上就不可能**（★ 比"每次小心校验"可靠得多 —— ★ 后者总有一天会漏）。

★ 即便如此，`_safe_project_dir()` 仍会**再校验一次形态** ——
⚠ 因为 `ProjectStorage.project_ref` 理论上可能被别处写入任意值（★ 纵深防御）。

---

# ★ `Storage` 抽象（与 `G6` 同一思路）

★ 一期是**本地文件系统**；★★ 将来换对象存储（S3 / OSS）**只改这一层**，
★ 调用方（发布 / 作业）**一行都不用改**。★ 所以这里定义的是**"按项目存/取源码"的语义**，
❌ 不暴露 `open()` / `pathlib.Path` 这类具体形态。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Iterator

from django.conf import settings

from core import appsettings
from core.refs import is_valid_project_ref

# ===========================================================================
# 常量
# ===========================================================================

#: ★★ **采集时要【跳过】的目录** —— ★ 最要紧的是 **`.git`**：
#:   ⚠ 它常常占整个仓库的**一大半**，而★ **对解析源码毫无用处**。
#:   ★ 不跳过它 = 用户一半的配额被浪费在"我们根本不看的东西"上。
SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".hg", ".svn", "node_modules", "vendor", "__pycache__", ".venv", "venv",
     ".mypy_cache", ".pytest_cache", ".tox", "dist", "build", ".next", "target"}
)


# ===========================================================================
# 路径
# ===========================================================================


def root() -> str:
    """★ 存储根目录（★ 生产应挂在**独立数据卷**上，见 `settings` 注释）。"""
    return getattr(settings, "ASTROLABE_STORAGE_ROOT", "/data/astrolabe/projects")


def project_dir(project_ref: str) -> str:
    """★ 某项目的源码目录（★ **绝对路径**）。

    ⚠★ 形态不对 ⇒ **直接 `ValueError`**（❌ 不"容错地拼接"）——
      ★ 因为能走到这里说明**上游有 bug**，⚠ 而"宽容地拼一个路径"会把它**掩盖成数据事故**。
    """
    if not is_valid_project_ref(project_ref):
        raise ValueError(f"非法的 project_ref：{project_ref!r}（⚠ 路径只允许从合法 project_ref 派生）")
    return os.path.join(root(), project_ref)


def rel_dir(project_ref: str) -> str:
    """★ 相对路径（★ **存库用相对值** ⇒ ⚠ 换根目录时不用改数据）。"""
    if not is_valid_project_ref(project_ref):
        raise ValueError(f"非法的 project_ref：{project_ref!r}")
    return project_ref


def exists(project_ref: str) -> bool:
    try:
        return os.path.isdir(project_dir(project_ref))
    except ValueError:
        return False


# ===========================================================================
# 统计
# ===========================================================================


def dir_size(path: str, *, skip_dirs: frozenset[str] = SKIP_DIRS) -> tuple[int, int]:
    """★ 统计一个目录的 `(字节数, 文件数)` —— ⚠ **跳过 `SKIP_DIRS`**（见常量说明）。

    ⚠★ 用**文件大小之和**，而不是磁盘占用 —— ★ 因为后者与文件系统块大小有关，
      ★ 同一份源码在不同机器上会算出不同的数（⚠ 用户会困惑"为什么换台机器就超了"）。
    """
    total_bytes = 0
    total_files = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                # ⚠ 用 `lstat` 语义（`follow_symlinks=False`）：★ 软链接**不跟随**
                #   —— ⚠ 否则一个指向 `/` 的链接就把它变成"无限大仓库"（★ 也顺带防了环）
                st = os.lstat(fp)
            except OSError:
                continue
            total_bytes += st.st_size
            total_files += 1
    return total_bytes, total_files


def usage_of(user) -> tuple[int, int]:
    """★ 某用户**已用**的 `(字节数, 文件数)`。

    ★ = 他名下所有项目的 **`SUM`**（★ 见 `ProjectStorage` 的说明：
      ⚠ **刻意不存"用户汇总值"** —— 两份记账早晚会不一致）。
    """
    from django.db.models import Sum

    from core.models import ProjectStorage

    if not getattr(user, "pk", None):
        return 0, 0
    agg = ProjectStorage.objects.filter(owner=user).aggregate(
        b=Sum("bytes_used"), f=Sum("files_used")
    )
    return int(agg["b"] or 0), int(agg["f"] or 0)


def project_usage(project_ref: str) -> tuple[int, int]:
    from core.models import ProjectStorage

    row = ProjectStorage.objects.filter(project_ref=project_ref).first()
    return (row.bytes_used, row.files_used) if row else (0, 0)


# ===========================================================================
# 容量
# ===========================================================================


#: ★ 拒绝原因码
CODE_OK = "ok"
CODE_BYTES = "storage_full"
CODE_FILES = "storage_files_full"


@dataclass
class CapacityVerdict:
    """★ 容量判定 —— ★★ **必须带"还剩多少"**（⚠ 用户要能在发布前看到进度条）。"""

    ok: bool = True
    reason_code: str = CODE_OK
    #: ★ 给用户看的说明（★ 同 `U3.9`：**说清原因 + 还差多少**，⚠ 含糊的提示会让用户反复重试）
    message: str = ""

    limit_bytes: int = 0
    used_bytes: int = 0
    limit_files: int = 0
    used_files: int = 0
    #: ★ 额度来自哪一层（`free` / `vip` / `user`）—— ★ 便于回答"为什么他空间比我大"
    source: str = ""

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.limit_bytes - self.used_bytes)

    @property
    def remaining_files(self) -> int:
        return max(0, self.limit_files - self.used_files)

    @property
    def used_ratio(self) -> float:
        return (self.used_bytes / self.limit_bytes) if self.limit_bytes > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason_code": self.reason_code,
            "message": self.message,
            "limit_bytes": self.limit_bytes,
            "used_bytes": self.used_bytes,
            "remaining_bytes": self.remaining_bytes,
            "limit_files": self.limit_files,
            "used_files": self.used_files,
            "remaining_files": self.remaining_files,
            "used_ratio": round(self.used_ratio, 4),
            "source": self.source,
        }


def _human(n: int) -> str:
    """★ 人类可读的大小（★ 给用户看的文案里**不要出现 1073741824 这种数**）。"""
    step = 1024.0
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < step or unit == "TB":
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= step
    return f"{val:.1f} TB"


def check_capacity(
    user, *, add_bytes: int = 0, add_files: int = 0, profile=None
) -> CapacityVerdict:
    """★★ **容量闸门** —— 还能不能再放进这些内容。

    ⚠★ 注意这里的 `add_*` 是**预估值**：★ 复制前我们**并不知道确切大小** ⇒
      ★ 所以它只是**第一道**（早失败）；★★ **真正的兜底在 `ingest()` 里**（边写边数、超了就中止）。
      ★ 两道都需要：★ 第一道给用户**清楚的拒绝**，第二道**保住磁盘**。
    """
    if profile is None:
        profile = getattr(user, "profile", None)
    tier = getattr(profile, "tier", None) or "free"
    quota = appsettings.quota_for(tier, profile)

    limit_bytes = int(quota.get("storage_bytes_max") or 0)
    limit_files = int(quota.get("storage_files_max") or 0)
    source = "user" if (getattr(profile, "quota_override", None) or {}) else tier

    used_bytes, used_files = usage_of(user)
    v = CapacityVerdict(
        limit_bytes=limit_bytes, used_bytes=used_bytes,
        limit_files=limit_files, used_files=used_files, source=source,
    )

    if limit_bytes > 0 and used_bytes + max(0, add_bytes) > limit_bytes:
        v.ok = False
        v.reason_code = CODE_BYTES
        v.message = (
            f"存储空间不足：已用 {_human(used_bytes)} / {_human(limit_bytes)}，"
            f"这个项目还需要 {_human(max(0, add_bytes))}。"
            "你可以先删掉一些旧项目，或者升级到 VIP（空间更大）。"
        )
        return v

    if limit_files > 0 and used_files + max(0, add_files) > limit_files:
        v.ok = False
        v.reason_code = CODE_FILES
        v.message = (
            f"文件数超出上限：已用 {used_files} / {limit_files} 个文件，"
            f"这个项目还有 {max(0, add_files)} 个。"
        )
        return v

    return v


def remaining_for_ingest(user, *, profile=None) -> tuple[int, int]:
    """★ 本次最多还能放多少 `(字节, 文件数)` —— ★ 给 `ingest()` 当**硬闸门**。"""
    v = check_capacity(user, profile=profile)
    return v.remaining_bytes, v.remaining_files


# ===========================================================================
# 采集（把源码放进存储空间）
# ===========================================================================


@dataclass
class IngestResult:
    ok: bool = False
    reason_code: str = CODE_OK
    message: str = ""
    bytes: int = 0
    files: int = 0
    #: ★ 相对 `ASTROLABE_STORAGE_ROOT` 的路径（★ 存库用）
    path: str = ""


class _OverCapacity(Exception):
    """★ 内部：容量撞线 ⇒ 触发**中止 + 清理**（⚠ 消息给用户看）。"""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def ingest(
    project_ref: str,
    source_dir: str,
    *,
    max_bytes: int = 0,
    max_files: int = 0,
    owner=None,
    replace: bool = True,
) -> IngestResult:
    """★★ **把一份源码采集进"这个项目的存储空间"** —— ★ 见模块文档。

    ⚠★★ **边复制边计数**，**超过上限就立即中止并把已写的清掉** ——
      ★ 因为"先复制完再看多大"会把磁盘**先塞满**（⚠ 那正是我们要防的事）。

    ★ 为什么不 `move` 而要 `copy`：★ 一期源码是**调用方放好的目录**（可能是共享的），
      ⚠ `move` 会把它搬走（★ 破坏调用方）。
      ⚠ 二期从远端 `clone` 时，**直接 clone 进存储目录**，❌ 不用复制这一步。

    Args:
        max_bytes / max_files: ★ **本次允许写入的上限**（★ 由 `remaining_for_ingest()` 算出）。
            ⚠ 传 0 表示**不限制**（★ 只该用在管理员 / 调试场景）。
    """
    result = IngestResult()
    try:
        dest = project_dir(project_ref)      # ★ 形态不对 ⇒ 直接 ValueError
    except ValueError as exc:
        result.reason_code = "bad_project_ref"
        result.message = str(exc)
        return result

    if not source_dir or not os.path.isdir(source_dir):
        result.reason_code = "source_missing"
        result.message = "找不到源码目录（一期需要调用方先放好源码）"
        return result

    # ★ 防止"把存储空间自己复制进自己"（⚠ 会无限递归）
    src_abs = os.path.realpath(source_dir)
    root_abs = os.path.realpath(root())
    if src_abs == root_abs or src_abs.startswith(root_abs + os.sep):
        result.reason_code = "bad_source"
        result.message = "源码目录不能是存储空间本身或它的子目录"
        return result

    if replace and os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)

    written_bytes = 0
    written_files = 0
    try:
        for rel, src_path, size in _walk_files(source_dir):
            written_bytes += size
            written_files += 1
            if max_bytes and written_bytes > max_bytes:
                raise _OverCapacity(
                    f"源码太大：光是在复制过程中就已经超过你还剩的 {_human(max_bytes)} 空间。"
                    "请换一个小一点的仓库，或先删掉一些旧项目。",
                    CODE_BYTES,
                )
            if max_files and written_files > max_files:
                raise _OverCapacity(
                    f"文件太多：已经超过你还剩的 {max_files} 个文件额度。",
                    CODE_FILES,
                )
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(src_path, target, follow_symlinks=False)
    except _OverCapacity as exc:
        # ★★ **中止 ⇒ 把已经写进去的清掉**（⚠ 否则留下半个仓库，反而更占空间）
        shutil.rmtree(dest, ignore_errors=True)
        result.reason_code = exc.code
        result.message = exc.message
        return result
    except OSError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        result.reason_code = "io_error"
        result.message = f"复制源码失败：{exc}"[:200]
        return result

    result.ok = True
    result.bytes = written_bytes
    result.files = written_files
    result.path = rel_dir(project_ref)
    # ★ 记账（★ 与复制在**同一个调用**里完成 ⇒ 不会"文件在、账没记"）
    commit(project_ref, owner=owner, bytes_used=written_bytes, files_used=written_files,
           path=result.path)
    return result


def _walk_files(source_dir: str) -> Iterator[tuple[str, str, int]]:
    """★ 遍历可采集的文件（⚠ 跳过 `SKIP_DIRS` 与软链接）。

    ★ 产出的 `rel` 是**相对路径** —— ★ 用它拼目标路径时，⚠ 已经过 `os.walk` 归一，
      ★ 不含 `..`（★ 因为 `os.walk` 只往下走）。
    """
    for dirpath, dirnames, filenames in os.walk(source_dir, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            fp = os.path.join(dirpath, name)
            if os.path.islink(fp):
                continue          # ⚠ 软链接**一律不跟**（★ 防"指向 / 的链接"与环）
            try:
                st = os.lstat(fp)
            except OSError:
                continue
            yield os.path.relpath(fp, source_dir), fp, st.st_size


# ===========================================================================
# 记账
# ===========================================================================


def commit(
    project_ref: str, *, owner=None, bytes_used: int, files_used: int, path: str = ""
) -> None:
    """★ 写/更新记账（★ **幂等** —— 重复采集就是覆盖，不是累加）。

    ⚠★ 用 `update_or_create` 而**不是** `+=` —— ★ 因为这里记的是**"这个项目占了多少"**，
      ★ 是**事实**而不是**增量**（★ 增量式记账一旦重跑就会翻倍）。
    """
    from core.models import ProjectStorage

    ProjectStorage.objects.update_or_create(
        project_ref=project_ref,
        defaults={
            "owner": owner if getattr(owner, "pk", None) else None,
            "bytes_used": int(bytes_used),
            "files_used": int(files_used),
            "path": (path or rel_dir(project_ref))[:512],
        },
    )


def release(project_ref: str) -> int:
    """★★ **释放一个项目的存储**（★ 删除项目时调用）—— 返回释放的字节数。

    ★ 两件事一起做：★ **删目录** + ★ **删记账行** ——
      ⚠★ 只删一个都会出问题：★ 只删目录 ⇒ 记账虚高（用户以为空间满了）；
      ★ 只删记账 ⇒ 磁盘**悄悄泄漏**（⚠ 最难发现的那种）。
    """
    from core.models import ProjectStorage

    row = ProjectStorage.objects.filter(project_ref=project_ref).first()
    freed = row.bytes_used if row else 0

    try:
        shutil.rmtree(project_dir(project_ref), ignore_errors=True)
    except ValueError:
        pass
    ProjectStorage.objects.filter(project_ref=project_ref).delete()
    return freed


def measure(project_ref: str) -> tuple[int, int]:
    """★ **实测**磁盘占用（❌ 不读记账）—— ★ 对账用。"""
    if not exists(project_ref):
        return 0, 0
    return dir_size(project_dir(project_ref))


def audit(*, fix: bool = False) -> list[dict]:
    """★ **对账**：把"记账"与"磁盘实测"比一遍。

    ⚠★ 为什么必须有：★ 记账是**应用层**写的 —— ⚠ 进程被杀 / OSError / 手工删目录
      都会让两边**悄悄分叉**。★ 而分叉的后果是"用户空间虚满"或"磁盘悄悄泄漏"。
      ★ 所以给一个能主动查（甚至修）的入口。
    """
    from core.models import ProjectStorage

    out: list[dict] = []
    for row in ProjectStorage.objects.all().iterator():
        actual_b, actual_f = measure(row.project_ref)
        if (actual_b, actual_f) != (row.bytes_used, row.files_used):
            out.append(
                {
                    "project_ref": row.project_ref,
                    "recorded": (row.bytes_used, row.files_used),
                    "actual": (actual_b, actual_f),
                }
            )
            if fix:
                if actual_f == 0:
                    row.delete()            # ⚠ 目录没了 ⇒ 记账也该没了
                else:
                    row.bytes_used, row.files_used = actual_b, actual_f
                    row.save(update_fields=["bytes_used", "files_used", "measured_at"])
    return out
