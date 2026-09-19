"""Astrolabe · 共享内核：**服务端拉取源码**（`B109` / `B153`）

> ★ 这是发布链路上**最后缺的一环**（`B149` / `B151` 都把它标成待办）：
> ★ 在这之前，`source_path` 得是"容器里已放好的目录" ⇒ **只有我们自己能发布**。

---

# ★★ 为什么用 **archive 快照**，而不是 `git clone`

| | `git clone` | ★★ **archive 快照** |
|---|---|---|
| ★ 拉到什么 | ⚠★ **完整历史**（★ 很多仓库的历史**比源码大十倍**） | ★★ **只有某个 commit 的树** |
| ★ 依赖 | ⚠ 需要 **git 二进制**（容器里还得装） | ✅ **只要 HTTP**（stdlib 就够） |
| ★ 大小控制 | ⚠ **拉到一半才知道**多大 | ★★ 有 `Content-Length` ⇒ **可以提前拒** |
| ★ 速度 | 慢（要解析 pack、走多个请求） | ✅ 一次 HTTP |

★★★ 而**我们本来就只要"某个 commit 的源码快照"**（`B109`：源码只能服务端获取）——
  ★ git 历史对我们**毫无用处**（★ 这也正是 `storage.SKIP_DIRS` 要跳过 `.git` 的原因）。

---

# ★★★ 三道闸门（`B152` 里说好的第三道，在这里落地）

| # | 在哪 | 靠什么判断 |
|---|---|---|
| **1** | 发布时（`publish.publish_project`） | ★ 用户**已经满了** |
| **2** | ★★ **这里 · 拉取前** | ★★★ **归属校验那次请求**已经拿到了 `repo.size`（★ GitHub 单位是 **KB**）—— ⚠ **零额外开销** |
| **3** | ★ **这里 · 解压时** | ★★ **边解边计数，超了立即中止并清理** |

⚠ 第 2 道是**估计值**（`size` 是 GitHub 自己算的、且随分支变化）⇒ ★ **不能当唯一判据**，
  ★ 所以第 3 道必须留着。

---

# ⚠★★★ 解压是**攻击面**，三件事必须做

★ tar / zip **不是"安全的数据格式"** —— 一个恶意 archive 可以做三件事：

| # | 攻击 | 防御 |
|---|---|---|
| **1** | ★★ **路径穿越** —— 成员名写成 `../../app/core/models.py` ⇒ **覆盖我们的代码** | ★ `_safe_member_path()`：**含 `..` 一律丢弃** + 最终再 `realpath` 校验一次 |
| **2** | ★★ **符号链接** —— 解出一个指向 `/etc` 的链接，后面写它 = 写到 `/etc` | ★ **只接受 `isfile()` / `isdir()`**，❌ 链接 / 设备文件一律跳过 |
| **3** | ★★ **解压炸弹** —— 100KB 的 archive 解出 100GB | ★★★ **边解边计数 + 硬上限**（★ 这是唯一有效的防御 —— ⚠ 看成员声明的 `size` 是没用的，那是**攻击者写的**） |

★ 顺带第 4 件：★ **剥掉 archive 的顶层目录**（通常是 `repo-<sha>/`）——
  ⚠ 不剥掉的话，源码会躺在我们要找的路径**下一层**（★ 解析会扫到空）。
"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import BinaryIO
from urllib.parse import urlparse

from core import storage

#: ★ 单次下载的读取块（★ 64KB —— ⚠ 太小会慢，太大则"超限"发现得晚）
CHUNK = 64 * 1024

#: ★★ 用 `repo.size` 估大小时的**保守系数** —— ★ **必须 < 1**（★ 见 `check_remote_size` 的说明：
#:   ⚠ `size` 含 `.git`，而我们跳过它 ⇒ ★ 真实值通常更小；**宁可放过，不要误杀**）
SIZE_ESTIMATE_FACTOR = 0.8

#: ★ 下载超时（秒）—— ★ 连接 + 读取分别设（⚠ 只设一个会有一边挂死）
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30


class FetchError(Exception):
    """★ 拉取失败 —— ⚠ **消息是给用户看的**。"""


# ===========================================================================
# HTTP（★ 可注入 —— 冒烟不真的去连 GitHub）
# ===========================================================================


@dataclass
class StreamResponse:
    status: int
    #: ★ `-1` 表示对方没给（★ 那就只能靠"边解边数"兜底）
    content_length: int
    body: BinaryIO
    final_url: str = ""


class ArchiveFetcher:
    """★ 默认实现：**标准库**（❌ 不引入 `requests` / `httpx` —— 少一套依赖）。"""

    def get_json(self, url: str, *, headers: dict | None = None) -> dict:
        req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8", "replace") or "{}")
        except (urllib.error.HTTPError, OSError, ValueError) as exc:
            raise FetchError(f"查询仓库信息失败：{exc}") from exc

    def open_stream(self, url: str, *, headers: dict | None = None) -> StreamResponse:
        req = urllib.request.Request(
            url, headers={"Accept": "*/*", "User-Agent": "astrolabe", **(headers or {})}
        )
        try:
            resp = urllib.request.urlopen(req, timeout=READ_TIMEOUT)
        except urllib.error.HTTPError as exc:
            raise FetchError(f"下载源码失败（HTTP {exc.code}）—— 仓库可能是私有的，或地址不对。") from exc
        except OSError as exc:
            raise FetchError(f"下载源码失败：{exc}") from exc

        length = resp.headers.get("Content-Length")
        return StreamResponse(
            status=getattr(resp, "status", 200),
            content_length=int(length) if (length or "").isdigit() else -1,
            body=resp,                      # ⚠ 调用方负责关（用 `contextlib.closing`）
            final_url=getattr(resp, "url", url),
        )


_default_fetcher = ArchiveFetcher()


# ===========================================================================
# ① archive 地址
# ===========================================================================


def archive_url(provider: str, repo_full_name: str, ref: str = "") -> str:
    """★ archive 快照地址（★ 公开仓库**不需要鉴权**）。

    ⚠★ 不同 provider 的路径差别**很大** —— ★ 必须显式写（⚠ 靠"推导"会拼错，
      这条纪律在 `B148` 已经吃过一次亏：Gitee 的 `/api/v5/` 前缀漏了）。
    """
    full = (repo_full_name or "").strip().strip("/")
    target = (ref or "").strip() or "HEAD"
    if provider == "github":
        # ★ `codeload` 是 GitHub 专门发 archive 的域名（★ 比 api.github.com 的 tarball 端点省一次跳转）
        return f"https://codeload.github.com/{full}/tar.gz/{target}"
    if provider == "gitee":
        return f"https://gitee.com/{full}/repository/archive/{target}.tar.gz"
    raise FetchError(f"不支持的托管平台：{provider}")


# ===========================================================================
# ② ★★ 第三道闸门：用归属校验**已有**的 `size` 提前拒
# ===========================================================================


@dataclass
class RemoteSizeVerdict:
    ok: bool = True
    reason_code: str = "ok"
    message: str = ""
    #: ★ 估计的字节数（`0` = **对方没给**，⚠ 那就只能靠边解边数兜底）
    bytes: int = 0
    known: bool = False


def check_remote_size(repo_json: dict, *, remaining_bytes: int) -> RemoteSizeVerdict:
    """★★ 用**仓库元数据里已有的 `size`** 预判（★ 见模块文档：**零额外请求**）。

    ⚠★ `size` 的坑（★ 两条，都必须认）：

    ① ★ **单位是 KB**（不是字节）—— ⚠ 忘了乘 1024 会**把上限放宽 1000 倍**；
    ② ★ 它是 **GitHub 自己算的**，且**随默认分支变化** ⇒ ★★ **只是估计值**，
       ❌ **不能当唯一判据**（★ 所以"边解边数"那道必须留着）。

    ★★ **保守系数 0.8 —— 方向是"宁可放过"**（⚠ 这一条**被冒烟抓回来过**）：

    ⚠★ 我一开始写的是 `* 1.2`，**注释说"宁可放过"，代码却在"更容易拒"** ——
      ★★ **方向完全反了**（★ 注释与代码互相矛盾，⚠ 是最难自查的一类错）。

    ★ 而且方向应该是**往下**的，理由很实在：

    | 事实 | 结论 |
    |---|---|
    | ★ `size` 包含 **`.git`**，★ 而我们**跳过 `.git`** | ★★ 真实解出来的通常**更小** |
    | ★ `size` 是 GitHub **自己算的**、随默认分支变 | ★ 本来就是个**粗估** |

    ⇒ ★★ 所以按 `0.8` 估，**宁可放过一个稍大的**（★ 后面还有**硬闸门**兜着）；
      ⚠ 也不要**误杀**一个本来放得下的 —— ★ 那会让用户**莫名其妙被拒**。
    """
    if not isinstance(repo_json, dict):
        return RemoteSizeVerdict()                    # ★ 拿不到 ⇒ 不拦（交给下一道）
    raw = repo_json.get("size")
    if raw in (None, "", 0):
        return RemoteSizeVerdict()                    # ★ 对方没给 ⇒ 不拦

    try:
        kb = int(raw)
    except (TypeError, ValueError):
        return RemoteSizeVerdict()

    est = int(kb * 1024 * SIZE_ESTIMATE_FACTOR)
    if remaining_bytes > 0 and est > remaining_bytes:
        return RemoteSizeVerdict(
            ok=False,
            reason_code="storage_full",
            message=(
                f"这个仓库约 {est / 1024 / 1024:.1f} MB，"
                f"超过你还剩的 {remaining_bytes / 1024 / 1024:.1f} MB 存储空间。"
                "请先删掉一些旧项目，或升级到 VIP（空间更大）。"
            ),
            bytes=est,
            known=True,
        )
    return RemoteSizeVerdict(bytes=est, known=True)


# ===========================================================================
# ③ ★★★ 拉取 + 解压（边解边数）
# ===========================================================================


@dataclass
class FetchResult:
    ok: bool = False
    reason_code: str = "ok"
    message: str = ""
    bytes: int = 0
    files: int = 0
    #: ★ 跳过多少项（★ 软链接 / 越界路径 / 噪音目录）—— ★ 便于回答"为什么文件数比预想少"
    skipped: int = 0
    path: str = ""


class _Abort(Exception):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def fetch_archive(
    project_ref: str,
    provider: str,
    repo_full_name: str,
    *,
    ref: str = "",
    max_bytes: int = 0,
    max_files: int = 0,
    owner=None,
    fetcher: ArchiveFetcher | None = None,
) -> FetchResult:
    """★★ **把远端仓库的源码快照拉进"这个项目的存储空间"**。

    ★ 全程**边下边解边计数** —— ⚠ 一旦超过 `max_bytes` / `max_files` **立即中止并清理**
      （★ 见模块文档的"三道闸门"与"解压是攻击面"）。

    ★ 成功后**自动记账**（`storage.commit`）—— ★ 让"文件已落盘"与"账已记"**在同一次调用里完成**
      （⚠ 分开做就会出现"文件在、账没记"的窗口）。
    """
    result = FetchResult()
    f = fetcher or _default_fetcher

    try:
        dest = storage.project_dir(project_ref)      # ★ 形态不对 ⇒ ValueError
    except ValueError as exc:
        result.reason_code = "bad_project_ref"
        result.message = str(exc)
        return result

    try:
        url = archive_url(provider, repo_full_name, ref)
    except FetchError as exc:
        result.reason_code = "bad_provider"
        result.message = str(exc)
        return result

    # ★ 清掉旧的（★ 覆盖式拉取 —— ⚠ 幂等：重复拉取不会翻倍）
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)

    resp: StreamResponse | None = None
    try:
        resp = f.open_stream(url, headers={"User-Agent": "astrolabe"})
        if resp.status != 200:
            raise _Abort(f"下载源码失败（HTTP {resp.status}）", "http_error")

        # ---- ★★ 闸门 ②b：有 `Content-Length` 就直接判（⚠ 比解压后再发现早得多）----
        if max_bytes and resp.content_length > 0 and resp.content_length > max_bytes:
            raise _Abort(
                f"这个仓库的压缩包就有 {resp.content_length / 1024 / 1024:.1f} MB，"
                f"超过你还剩的 {max_bytes / 1024 / 1024:.1f} MB 存储空间。",
                "storage_full",
            )

        if resp.final_url.endswith(".zip"):
            raise _Abort("暂不支持 zip 形态的 archive（请反馈）", "unsupported_archive")

        # ---- ★ 流式解压（`r|gz`：不落临时文件，⚠ 也就不会被"先塞满磁盘"）----
        tar = tarfile.open(fileobj=resp.body, mode="r|gz")
        try:
            result.bytes, result.files, result.skipped = _extract_tar(
                tar, dest, max_bytes=max_bytes, max_files=max_files
            )
        finally:
            tar.close()
    except _Abort as exc:
        shutil.rmtree(dest, ignore_errors=True)
        result.reason_code = exc.code
        result.message = exc.message
        return result
    except FetchError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        result.reason_code = "fetch_error"
        result.message = str(exc)
        return result
    except (tarfile.TarError, OSError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        result.reason_code = "archive_error"
        result.message = f"源码包无法解析（可能不是 tar.gz，或者下载不完整）：{exc}"[:200]
        return result
    finally:
        # ⚠ 无论成败都要关掉那条连接 —— ★ 否则失败路径会**泄漏 socket**
        #   （★ 一个刷失败请求的人就能把连接耗光）
        _close_quietly(resp)

    if result.files == 0:
        shutil.rmtree(dest, ignore_errors=True)
        result.reason_code = "empty"
        result.message = "这个仓库里没有找到可解析的源码文件（可能是空仓库，或全是链接）"
        return result

    result.ok = True
    result.path = storage.rel_dir(project_ref)
    # ★ 记账（★ 与落盘在同一次调用里 —— ⚠ 见函数文档）
    storage.commit(project_ref, owner=owner, bytes_used=result.bytes,
                   files_used=result.files, path=result.path)
    return result


def _extract_tar(
    tar: tarfile.TarFile, dest: str, *, max_bytes: int, max_files: int
) -> tuple[int, int, int]:
    """★ 逐个成员解压 —— ★★ **边解边计数**（见模块文档的"解压是攻击面"）。"""
    written_bytes = 0
    written_files = 0
    skipped = 0
    dest_abs = os.path.realpath(dest)

    for member in tar:
        rel = _safe_member_path(member.name)
        if rel is None:
            skipped += 1
            continue

        if member.isdir():
            os.makedirs(os.path.join(dest, rel), exist_ok=True)
            continue

        # ★★ **只接受普通文件** —— ⚠ 符号链接 / 硬链接 / 设备文件一律跳过。
        #   ⚠★ 这是**必须**的：★ 一个指向 `/etc` 的链接被解出来后，
        #     后续任何"写这个链接"的动作都会**写到 `/etc`**。
        if not member.isfile():
            skipped += 1
            continue

        written_files += 1
        written_bytes += max(0, member.size)

        # ★★★ 核心防御：**边解边数**（⚠ 成员声明的 `size` 是**攻击者写的**，不能信）
        if max_files and written_files > max_files:
            raise _Abort(
                f"仓库文件太多：已经超过你还剩的 {max_files} 个文件额度。",
                "storage_files_full",
            )
        if max_bytes and written_bytes > max_bytes:
            raise _Abort(
                f"仓库太大：解压过程中就已经超过你还剩的 {max_bytes / 1024 / 1024:.1f} MB 空间。",
                "storage_full",
            )

        target = os.path.join(dest, rel)
        # ★ 最后一道：`realpath` 必须仍落在 `dest` 内（⚠ 纵深防御 —— 见 `_safe_member_path`）
        if not os.path.realpath(os.path.dirname(target)).startswith(dest_abs):
            skipped += 1
            continue

        os.makedirs(os.path.dirname(target), exist_ok=True)
        src = tar.extractfile(member)
        if src is None:
            written_files -= 1
            written_bytes -= max(0, member.size)
            skipped += 1
            continue
        with src, open(target, "wb") as out:
            _copy_limited(src, out, max_bytes=max_bytes, already=written_bytes - max(0, member.size))

    return written_bytes, written_files, skipped


def _copy_limited(src: BinaryIO, out: BinaryIO, *, max_bytes: int, already: int) -> None:
    """★ 逐块拷贝 —— ★★ **按实际写入的字节数**判上限（❌ 不信 `member.size`）。

    ⚠★ 这是防"解压炸弹"的**真正落点**：★ 一个成员可以声称 `size=1` 却流出 10GB
      —— ★ 只有**边写边数**才拦得住。
    """
    total = already
    while True:
        chunk = src.read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if max_bytes and total > max_bytes:
            raise _Abort(
                f"仓库太大：解压过程中就已经超过你还剩的 {max_bytes / 1024 / 1024:.1f} MB 空间。",
                "storage_full",
            )
        out.write(chunk)


def _safe_member_path(name: str) -> str | None:
    """★★★ **把 archive 成员名变成一个安全的相对路径** —— 不安全就返回 `None`（丢弃）。

    ⚠★ 四类必须挡掉的东西（★ 见模块文档）：

    | # | 挡什么 | 怎么挡 |
    |---|---|---|
    | **1** | ★★ **绝对路径** | ★ `lstrip("/")` 之后仍以 `/` 开头 ⇒ 丢 |
    | **2** | ★★ **`..` 穿越** | ★ 任一段等于 `..` ⇒ 丢（⚠ **不做"归一化后校验"，直接丢** —— ★ 后者要写对很难） |
    | **3** | ★ 噪音目录 | ★ 任一段命中 `storage.SKIP_DIRS` ⇒ 丢（★ 省空间的第一道） |
    | **4** | ★ archive 的**顶层目录** | ★ 剥掉第一段（★ 通常是 `repo-<sha>/`）—— ⚠ 不剥则源码在我们要找的路径**下一层** |

    ⚠ 反斜杠也当分隔符处理 —— ★ 有些工具会生成 `..\\..\\x`（★ Windows 风格），
      ⚠ 在 Linux 上它虽然不会穿越，但**会变成一个奇怪的文件名**（★ 不如直接丢）。
    """
    raw = (name or "").replace("\\", "/")
    # ★ 绝对路径 / 盘符 ⇒ 丢
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        return None

    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts:
        return None
    # ★★ `..` 一律丢（⚠ 不做归一化 —— 见上表）
    if any(p == ".." for p in parts):
        return None

    # ★ 剥掉顶层目录（archive 的 `repo-<sha>/`）
    parts = parts[1:]
    if not parts:
        return None
    if any(p in storage.SKIP_DIRS for p in parts):
        return None
    # ⚠ 单个文件名/路径别长到离谱（★ 有些文件系统会 500）
    rel = "/".join(parts)
    return rel if len(rel) <= 900 else None


def _close_quietly(resp) -> None:  # pragma: no cover - 兜底
    try:
        if resp is not None and getattr(resp, "body", None) is not None:
            resp.body.close()
    except Exception:  # noqa: BLE001
        pass


# ===========================================================================
# 工具：从 repo_url 反推 owner/repo
# ===========================================================================


def repo_full_from_url(repo_url: str) -> str:
    """★ 从 `https://github.com/owner/repo` 反推 `owner/repo`。

    ⚠★ 这是**为了不让调用方到处解析 URL** —— ★ 一处写好、一处测。
    """
    path = urlparse((repo_url or "").strip()).path.strip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return ""
    full = f"{parts[0]}/{parts[1]}"
    return full[:-4] if full.endswith(".git") else full
