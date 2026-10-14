"""Astrolabe · 共享内核：**发布编排** —— ★★ 把散落的模块串成**一条链路**

> 在此之前，`core/` 里的模块（许可核验 / 限额 / 邀请 / OAuth / 审核）**各自独立**，
> ★ 没有任何一个地方能回答「**用户从点『发布』到看到图，中间发生了什么**」。
> ★★ 本模块就是那个答案。

---

# ★★★ 完整链路（★ 每一步都能说出"不过时会怎样"）

```
① 建 Project + 上传闸门               ← core/submission.py
     │  超限额 / 重复仓库 ⇒ ❌ 拒绝（★ 且【不留孤儿项目】）
     │  ★ 许可核验【推迟】（源码还没拉下来 —— 见 licensing.deferred()）
     ▼
② 投递 parse 作业                     ← jobs/dispatch.py  ⚠ O(毫秒) 两次写
     │  ★ job_id 立刻返回（★ B115 ①：投递即入队，❌ 不得静默拒绝）
     ▼
③ 【作业层】拉源码 → 许可核验 → 解析 → 写图   ← jobs/tasks.py
     │  ★ 核验完 ⇒ submission.resolve_license() 把那条流水【就地更新】成真结论
     │  · 宽松 ⇒ ✅ 放行，继续解析
     │  · 其余 ⇒ ⚠ 停在「待人工审核」，**不解析**（★ U3.1 第 ④ 步）
     ▼
④ 【管理员】放行 ⇒ ★ 重投作业 ⇒ 解析 ⇒ 图就出来了
```

★★★ `B176` ①（2026-10-12）：**这条链路原本的第 ① 步「归属校验」已【退役】** ⚠ ——
★ 原本它要先拿 `access_token` 去问第三方「这库是不是你的」；
★ ⇒ 现在**建项目不再要求任何第三方授权**，★ 于是 `publish_project()` 的同步部分**变短了** ✅

---

# ★★ 为什么【发布】同步、而【拉源码 + 解析】异步（这个切分是刻意的）

| 步骤 | 耗时 | 放哪 |
|---|---|---|
| ★ **建项目 + 投递作业** | ★ **两次写库（O(毫秒)）** | ★ **同步**（立刻能给用户 `project_ref` / `job_id`） |
| ★★ **拉源码 + 许可核验 + 解析** | ★★ **秒级到分钟级** | ★★ **异步**（⚠ 放同步会把 web 线程占死 —— `A3` 红线的本意） |

⚠★ `B176` ① 之前，这里还有一行「★ **归属校验** —— 一次 HTTP 调用 —— 同步」——
★★ 现在那一行**没有了**（★ 归属校验已退役；★ 见上）✅

---

# ★★ 分层说明（唯一的越界点，必须写清）

★ 本模块在**共享内核**（`core`）里，却调用了 `jobs.dispatch`。

⚠★ 这**不违反** `ARCHITECTURE.md` A3 红线 #2 —— 按 `B131` 的精确口径：

| | 允许？ |
|---|---|
| ★ 调 `jobs.dispatch`（**投递**，O(毫秒)） | ✅ |
| ❌ 调 `jobs.tasks` / `run_worker`（**执行**，O(分钟)） | ❌ **严禁** |

★ 而且这里是**延迟 import**（在函数内），❌ 不在模块顶层 ——
★ 让"共享内核不依赖作业层"这一点**在 import 期就成立**。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.db import transaction

#: ★ 本模块的日志（★ `B179` 起要多记一条"复用了现成基图"—— ★ 那是**省下算力**的证据）⚠
log = logging.getLogger(__name__)

from core import appsettings, fetch, licensing, oauth, quota, storage, submission
from core.models import Project, ProjectReview

#: ★★ `B182`：前端传来的 commit sha 必须【长得像 sha】才采用 ⚠
#:
#: ★★ 为什么必须校验：★ 这个值**直接决定基图的身份**与**下载地址** ⚠
#:   · ★ 前端传来一句怪话（★ 手滑 / 老客户端 / 恶意）⇒ ★ 会造出一个**身份错乱**的基图 ⚠
#:   · ★ 而那种错是**静默的**：★ 查询按身份比，★ 永远对不上 ⇒ 每次都重新解析 ⚠
#: ⇒ ★★ 所以不像就让**服务端自己解析**（★ 兜底那条路一直都在）✅
#:
#: ★ 形态：★ 7–64 位十六进制
#:   · ★ GitHub 短 sha = 7 位，★ 完整 SHA-1 = 40 位
#:   · ★★ 放到 64 位是为了**将来**（★ 平台若改用 SHA-256 就是 64 位）✅
#:     ⚠ 而不必为此再改一次代码 + 再发一次迁移 ⚠
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")

# ===========================================================================
# 结果
# ===========================================================================


@dataclass
class PublishResult:
    """★ 发布结论 —— ★★ **带分步结果**（⚠ 不能只说"失败了"）。"""

    ok: bool = False
    #: ★ 拒绝的原因码（`not_owner` / `fork` / `organization` / `daily` / `duplicate_repo` …）
    reason_code: str = ""
    #: ★★ **给用户看的说明**（★ 每个失败点都必须能读懂为什么）
    message: str = ""

    project: Project | None = None
    review: ProjectReview | None = None
    job: Any = None
    job_created: bool = False

    #: ★★ `B179`：**复用了现成基图** ⇒ `job` 为 `None`，但这是**成功** ⚠
    #   ⚠★ 视图层必须据此给用户**另一种文案**（★ 不是"投递失败"）⚠
    reused: bool = False
    #: ★ 复用了哪一版（★ 前端可以显示"对应 commit ea42736…"）✅
    reused_sha: str = ""

    #: ★ 分步结果（★ 前端可以照着渲染"①②③④ 各是哪一步拦住的"）
    steps: dict[str, Any] = field(default_factory=dict)

    @property
    def project_ref(self) -> str:
        return self.project.project_ref if self.project else ""


def _fail(result: PublishResult, *, step: str, code: str, message: str) -> PublishResult:
    result.ok = False
    result.reason_code = code
    result.message = message
    result.steps[step] = {"ok": False, "reason_code": code, "message": message}
    return result


# ===========================================================================
# 发布
# ===========================================================================


def publish_project(
    user,
    *,
    provider: str,
    repo_full_name: str,
    name: str = "",
    desc: str = "",
    source_path: str = "",
    # ⚠★ `B182`：**前端已经算好的 commit sha**（★ 空 ⇒ 由服务端自己解析）⚠
    #   ★★ 所有者原话：「**这个过程应该发生在前端，不是用我服务器的IP地址查询的**」
    sha: str = "",
    # ⚠★ 2026-10-13：**用户选的分支 / tag**（★ 空 ⇒ 默认分支）⚠
    #   ★★ 为什么要补它：★ 「新建项目」改走本函数之后，★ 前端那个
    #     「commit（可选）」输入框**得有地方落** —— ⚠ 否则它变成了摆设 ⚠
    #   ★ 它只作【留痕】（★ 真正定位版本的是 `sha`）⇒ ★ 记进基图的 `ref` 列 ✅
    ref: str = "",
    # ⚠★ 2026-10-13：**用户选的"创建后立即公开"** ⚠
    #   ★ 本函数原先**写死 `True`**（★ 政策：发布即公开页面）——
    #   ★★ 而前端那个勾选框的文案是「**创建后立即公开**」⇒
    #     ★ 默认不勾 ⇒ ★ 写死 True 会让**用户的勾选形同虚设** ⚠
    #   ★ 默认仍取 `True`（★ 保持原政策），★ 但**允许调用方覆盖** ✅
    is_public: bool = True,
    priority: int | None = None,
    at: datetime | None = None,
    ) -> PublishResult:
    """★★ **发布一个项目** —— ★★ 见模块文档的完整链路。

    ⚠★★ `B176` ①（2026-10-12）：**本函数【不再需要任何第三方授权】** ⚠ ——
      ★ 曾经它要 `access_token` 去**当场校验仓库归属**，★ 那一步已**退役** ⚠
      （★ 原话：「我以前说用 github 验证库是不是属于本人，我觉得不行，删掉这个，有风险」）
      ⇒ ★★ 于是 `access_token` / `fetcher` 两个参数**一并删掉** ✅
      ★ 论证见 `docs/backend-decisions.md` 的 `B176` ⑥。

    Args:
        user: 发布者（★ ❌ **不再要求**已绑定该 provider 的第三方身份）
        provider: `github` / `gitee`
        repo_full_name: `owner/repo`
        name: 项目显示名（⚠ 省略 ⇒ 用仓库名）
        source_path: ⚠★ **只给内部 / 管理员用的调试口子**（`B152`）——
            ★ **普通用户不要传**：★ 他的源码应当由作业层从 `repo_url` 拉取。
            ⚠★ 之所以要这么分：★ `source_path` 能被用来**读容器里的任何目录**
            （★ 这台机器上还跑着数据库）⇒ ★ **不能对普通用户开放**。
        priority: 队列优先级（⚠ `None` ⇒ 从配额里取 `queue_priority`，★ VIP 先出图）

    ⚠★ **本函数【不抛业务异常】** —— ★ 所有"不过"都通过返回值表达
      （★ 同 `submit_project`：这是**正常业务情况**，❌ 不是程序错误）。
    """
    r = PublishResult()

    # ==================================================================
    # ① ★★★ `B176` ①（2026-10-12）：**归属校验已退役 —— 这里【什么都不做】**
    #   ⚠ 本处原本是「身份绑定检查 + `verify_repo_ownership()` +
    #     `record_ownership_audit()` 留痕 + `ownership` 步骤回执」⚠
    #   ⇒ ★★ 现在**建项目不再要求任何第三方授权** ✅
    #   ★★ 论证：见 `docs/backend-decisions.md` 的 `B176` ⑥ ——
    #     ★ 旧方案付出了「承认知道风险」的代价，★ **却没换来真正的防护** ⚠
    # ==================================================================


    repo_url = _repo_url(provider, repo_full_name)
    project_name = (name or repo_full_name.rsplit("/", 1)[-1])[:200]

    # ==================================================================
    # ①.5 ★★ 存储空间预检（`B152`）—— 两道都是"**早在拉取之前**"能判的
    # ==================================================================
    #  ★★ 闸门 ①：**用户已经满了**吗
    cap = storage.check_capacity(user)
    if not cap.ok:
        return _fail(r, step="storage", code=cap.reason_code, message=cap.message)
    r.steps["storage"] = {"ok": True, **cap.to_dict()}

    #  ⚠★★ `B176` ①：**「仓库大小预检」这一步【也没有了】**
    #    ★ 它当初靠的是**归属校验那次请求顺带拿到的 `repo.size`**（★ 零额外开销）⚠
    #    ⇒ ★ 归属校验一退役，★ **那个 `repo` 字典就不存在了** ⚠
    #    ★★ 而**真正的防线一直不在这一层** —— `core/fetch.py` 的
    #      「**边解边数**」硬闸门仍在（★ `max_bytes` / `max_files`）✅
    #    ⚠★ 另：`B178` 已定「**取消存储空间配额**」⇒ 这一层的目的本就消失了 ⚠


    # ==================================================================
    # ② 建 Project + 上传闸门（★ 两者必须同一事务 —— 否则会留孤儿项目）
    # ==================================================================
    with transaction.atomic():
        project = Project.objects.create(
            name=project_name,
            desc=(desc or "")[:2000],
            owner=user,
            provider=provider,
            repo_url=repo_url,
            state=Project.STATE_ACTIVE,
            # ★ 发布即公开「页面」（★ 读开放是策略，U2.1）——
            #   ⚠ 但**列表 / 搜索只列 `review_state=approved` 的**，
            #     见本模块的 `public_projects()`（★ 约定固化成一个函数，❌ 不靠口头）
            # ⚠★ 2026-10-13：改成**用调用方给的值**（★ 默认仍是 True）——
            #   ★ 前端那个勾选框写的是「创建后立即公开」⇒ ★ 得让它真的说了算 ⚠
            is_public=bool(is_public),
            review_state=Project.REVIEW_PENDING,
        )

        sub = submission.submit_project(
            project, user,
            # ★★ 许可核验**推迟**到作业里（源码还没拉下来）
            #   ⚠ 它**不等于** `missing`（"看了、没有"）—— 见 `licensing.deferred()`
            defer_license=True,
            at=at,
        )

        if not sub.accepted:
            # ★★ 主动回滚 ⇒ **不留孤儿项目**（⚠ 用户被限额拦住，却多出一个空项目，很荒谬）
            transaction.set_rollback(True)
            r.project = None
            return _fail(
                r, step="quota",
                code=(sub.quota.reason_code if sub.quota else "quota"),
                message=sub.user_message,
            )

        r.project = project
        r.review = sub.review
        r.steps["quota"] = {
            "ok": True,
            "used_day": sub.quota.used_day if sub.quota else 0,
            "per_day": sub.quota.per_day if sub.quota else 0,
        }
        r.steps["submission"] = {"ok": True, "review_id": sub.review.pk if sub.review else None}

    # ==================================================================
    # ③ 投递 parse 作业 —— ⚠★ **放在事务【外】**（见下）
    # ==================================================================
    #  ⚠★ 为什么不能在事务里：`dispatch` 会**推 Redis** ——
    #    若在事务里推成功、事务随后回滚，队列里就留下一个**指向不存在作业**的 id；
    #    ★ 而 worker 领到它只会报错。⇒ ★★ **先把数据库落定，再入队**。
    #
    #  ⚠ 反过来（事务提交成功、入队失败）也有风险 ——
    #    ★ 但 `dispatch.submit` 已经把那种情况**显式置为 `failed` 并抛异常**
    #      （`B115` ①：❌ 绝不静默），★ 所以这里是**可观测**的，❌ 不是黑洞。
    out = dispatch_parse(
        project,
        # ★★ 只放行**存储空间内**的路径（`B152`）——
        #   ⚠★ 见 `_safe_source_path()`：这是"不把任意路径交给作业"的最后一道。
        source_path=_safe_source_path(source_path, user),
        commit="",
        # ⚠★ `B182`：把前端算好的 sha 透传下去 —— ★ 有它，服务端【一次 API 都不发】✅
        sha=sha or "",
        # ⚠★ 2026-10-13：**用户选的分支 / tag** 也带下去 ——
        #   ★ 它进基图的 `ref` 列（★ 只作留痕；★ 定位版本靠 `sha`）✅
        ref=ref or "",
        priority=priority if priority is not None else _queue_priority(user),
    )

    # ---- ⚠★ `B179`：**三种结局**，❌ 不能只看 `job is None` ----
    if out.failed:
        # ★★ 解析不出 sha（私有 / 不存在 / 限流 / 分支错）⇒ ★★ **如实报出原因** ⚠
        #   ★ 以前这里一律说"投递失败"—— ★ 而真实原因常常是**用户传了私有仓库** ⚠
        return _fail(
            r, step="dispatch", code=out.fail_code or "enqueue_failed",
            message=out.fail_message
            or (
                "项目已创建，但解析任务投递失败，请稍后重试或联系站长。"
                "（这次提交仍然占用了你的上传额度）"
            ),
        )

    if out.reused:
        # ★★★ **已经有现成的基图了**（★ 别的项目解析过同一个 sha）⚠
        #   ⇒ ★★ **没有作业**（⚠ 所以下面必须走这条分支，❌ 不能掉进 `job is None`）⚠
        #   ★ 这正是所有者要的「**有同样的，就直接返回，不拉取，不解析，还快**」✅
        r.ok = True
        r.job = None                     # ⚠★ 刻意置空 —— 真的没有作业
        r.job_created = False
        r.reused = True                  # ★★ 让视图层能给出对的文案 ⚠
        r.reused_sha = out.reused_sha
        r.steps["dispatch"] = {
            "ok": True, "reused": True, "sha": out.reused_sha, "job_id": None,
        }
        r.message = "这个仓库的同一个版本已经解析过了，直接就能看，不用再拉一次。"
        return r

    if out.job is None:
        # ★ 作业没投出去 ⇒ ★★ **如实告诉用户**（❌ 不假装"已受理"）
        return _fail(
            r, step="dispatch", code="enqueue_failed",
            message=(
                "项目已创建，但解析任务投递失败，请稍后重试或联系站长。"
                "（这次提交仍然占用了你的上传额度）"
            ),
        )

    r.ok = True
    r.job = out.job
    r.job_created = out.created
    r.steps["dispatch"] = {
        "ok": True, "job_id": out.job.pk, "created": out.created,
        # ★★ `B179`：把 sha 一并记进步骤（★ 事后能看出"这一版对应哪个 commit"）✅
        "sha": out.job.payload.get("sha", ""),
    }
    r.message = (
        "已受理，正在拉取源码并核验许可证，完成后会自动开始解析。"
    )
    return r


def _safe_source_path(source_path: str, user) -> str:
    """★★ **只放行"存储空间内"的路径**（`B152`）—— ⚠★ 这是**安全边界**，不是便利功能。

    ⚠★★ 背景：★ `source_path` 一旦可以任意传，**用户就能让服务端去读容器里的任何目录**
      （`/etc`、**别的用户的项目**、…），★ 而这台机器上还跑着数据库。

    ★ 规则（★ 三条）：

    | 传了什么 | 结果 |
    |---|---|
    | ★ 空 | ★ 返回空 ⇒ 作业会**明确失败**「拉取尚未实现」（★ 诚实） |
    | ★★ **在 `ASTROLABE_STORAGE_ROOT` 内** | ★ 放行（★ 这是正常形态） |
    | ⚠ 在外面 | ★★ **只有 staff 才放行**（★ 内部调试用）；★ 普通用户 ⇒ ★ **降级为空** |

    ⚠ 普通用户传了外部路径**不报错、只是不生效** —— ★ 因为"报错"会暴露
      「路径检查存在」这件事给探测者（⚠ 免费反馈），★ 而**降级**让他的请求
      **自然地在作业里失败**（★ 与"看不见区别"的原则一致）。
    """
    raw = (source_path or "").strip()
    if not raw:
        return ""

    try:
        root_abs = os.path.realpath(storage.root())
        src_abs = os.path.realpath(raw)
    except (OSError, ValueError):
        return ""

    inside = src_abs == root_abs or src_abs.startswith(root_abs + os.sep)
    if inside:
        return src_abs
    if getattr(user, "is_staff", False):
        return src_abs          # ★ 内部调试口子（★ 已留审计入口：调用方是 staff）
    return ""


def _repo_url(provider: str, repo_full_name: str) -> str:
    """★ `owner/repo` → 仓库地址（★ 用于**重复提交检测** —— ⚠ 必须归一化）。"""
    full = (repo_full_name or "").strip().strip("/")
    host = "github.com" if provider == "github" else "gitee.com"
    return f"https://{host}/{full}"[:512]


def _queue_priority(user) -> int:
    """★ 队列优先级（`U6`）—— ★★ **VIP 不是"看得更多"，而是"排得更前"**。"""
    profile = getattr(user, "profile", None)
    tier = getattr(profile, "tier", None) or "free"
    try:
        return int(appsettings.quota_for(tier, profile).get("queue_priority") or 0)
    except Exception:  # noqa: BLE001 —— ⚠ 优先级是"锦上添花"，读不到就别让它挂
        return 0


@dataclass
class DispatchOutcome:
    """★★ `dispatch_parse()` 的返回值（★ `B179` 起**不再是裸 tuple**）⚠

    ## ⚠★ 为什么必须换个类型

    ★ `B179` 之前只有两种结果：★ 投出去了（`job`）· ★ 没投出去（`None`）。
    ★★ `B179` 之后多出**第三种** —— ⚠★ **复用了现成的基图** ⚠

    | 情形 | `job` | `reused` | `failed` | 调用方该怎么办 |
    |---|---|---|---|---|
    | ★ 投出去了 | ✅ 有 | `False` | `False` | ★ 照旧等作业 ✅ |
    | ★★ **复用了** | ⚠ `None` | ✅ **`True`** | `False` | ★★ **这是成功** —— ★ 告诉用户"已经有了，直接看" ✅ |
    | ★ 解析不出 sha | `None` | `False` | ✅ `True` | ★ **如实报原因**（私有 / 限流 / 分支不存在）⚠ |

    ⚠★★ 如果把"复用"也返回 `job=None` ⇒ ★ 调用方会**误判成投递失败** ⚠
      —— ★ 于是用户看到"投递失败"，★ 而事实上**图已经能看了**（★ 那是最难解释的一类 bug）⚠
    """

    job: Any = None
    created: bool = False
    #: ★★ `B179`：**复用了现成基图** —— ⚠ `job` 是 `None`，但这是**成功** ⚠
    reused: bool = False
    reused_sha: str = ""
    base_graph: Any = None
    #: ★★ 失败（★ 带**用户能看懂的原因**，❌ 不是笼统的"失败"）
    failed: bool = False
    fail_code: str = ""
    fail_message: str = ""

    @property
    def ok(self) -> bool:
        """★ 只要不是失败就算成（★ 复用也是成）✅"""
        return not self.failed


def dispatch_parse(
    project: Project,
    *,
    source_path: str,
    commit: str,
    priority: int,
    ref: str = "",
    sha: str = "",
) -> DispatchOutcome:
    """★★ **投递一个解析作业** —— ★★ **这是对外入口**（`B176` ① 之后由三处共用）⚠

    | 谁调用 | 什么时候 |
    |---|---|
    | ★ `publish_project()` | ★ 建完项目 ⇒ 投递第一次拉取 |
    | ★ `approve_and_resume()` | ★ 管理员放行之后 ⇒ 重投 |
    | ★★ `web/views/projects.py::start_fetch()` | ★★ 用户点「拉取代码」（★ `B176` ①：**不再走 OAuth**）|

    ⚠★★ **payload 只在这一处构造** —— ★ 三个调用方**共用同一份** ⚠
      （★ 否则"作业该带什么"就会有三个版本，★ 早晚不一致 —— 同 `U4.8` 的收敛纪律）

    ★ 作业靠 payload 里的 `provider` / `repo_full_name` / `repo_url`
      **自己把源码拉下来**（`B153`，`core/fetch.py`）—— ★ 调用方**不需要**给目录 ✅

    ## ★★★ `B179`：**拉取之前先问一句"有没有现成的"**

    ★★ 所有者原话（逐字）：

    > 「**用户拉一个图就解析一次，太浪费算力，应该是，拉去之前，看看现有的图数据里
    > 有没有同样的，有同样的，就直接返回，不拉取，不解析，还快。**」

    ⇒ ★★ 所以本函数现在**先解析 sha**（★ `core/fetch.py::resolve_ref`），★ 再按
      【仓库 + sha】查基图：

    | 查到 | 做什么 |
    |---|---|
    | ★★ **已经建好** | ★★ **绑上就返回，★ 不投作业** ⇒ 用户**秒回** ✅ |
    | ★ 只有记录、还没建 | ★ 投作业（★ 让它去拉去解析）✅ |
    | ⚠ 解析不出 sha | ★★ **不投作业，如实报原因** ⚠ |

    ⚠★ **失败兜底（必须有的）**：★ `resolve_ref` 要**走网络** ——
      ★★ 而所有者明确说过「github 在国内搞这些配置，很卡的」⚠
      ⇒ ★★ 网络不通 ⇒ ★ **照旧投作业**（★ 让作业去扛、去重试），❌ 不让用户请求挂着 ⚠

    ★ 延迟 import —— 见模块文档的分层说明。
    """
    from jobs import dispatch
    from jobs.models import Job

    provider = (project.provider or "").strip().lower()
    repo_full = (fetch.repo_full_from_url(project.repo_url) or "").strip()
    # ⚠★★ `B182`：这里【不能写 `sha = ""`】⚠ ——
    #   ★★ 它会把调用方（前端）传进来的 sha **在判断之前就清掉** ⚠
    #   · ★ 后果：★ 明明是"前端给了 sha"，★ 服务端却照样去解析（★ 白烧 2 次 API）⚠
    #   · ★★ 而那种错是【静默的】—— ★ 功能照旧，★ 只是配额白白流走 ⚠
    #   ⇒ ★★ 改成：★ 先收下前端给的（形态不像就丢掉），★ 再由下面决定要不要自己解析 ✅
    sha = (sha or "").strip().lower()

    # ---- ⓪ ★★ `B179`：先定 sha（⚠ 只有"真要拉远端"时才需要）----
    #   ★ 调试路径（`source_path` 非空 ⇒ staff 指了容器里的目录）**跳过** ——
    #     ★ 那时源码不来自远端，★ 而 sha 由作业里兜底解析（见 `_base_graph_for`）。
    if repo_full.count("/") == 1 and not source_path:
        # ⚠★★ `B182`（2026-10-13）：**前端可能已经把 sha 算好了** ⚠
        #   ★★ 所有者原话（逐字）：
        #   > 「**不对呀，这个过程应该发生在前端，不是用我服务器的IP地址查询的，
        #   > 只有拉源码，才是我服务器做的吧？**」
        #
        #   ★★ 为什么这样更好：
        #     · ★ 未认证的 GitHub API 每小时每 IP 约 60 次，★ 而解析 sha 要 2 次
        #       ⇒ ★★ 由服务端做 ⇒ 每小时约 30 次拉取就撞限，★ 而且【所有用户一起被挡】⚠
        #     · ★★ 由前端做 ⇒ ★ 每个用户花【自己的】配额 ⇒ ★ 互不影响 ✅
        #     · ★★ 服务端的 IP 彻底不参与这两次查询 ⚠
        #
        #   ★★ 为什么服务端还能信这个 sha（★ 不需要"信"）：
        #     · ★ sha 同时决定【基图身份】与【下载地址】⇒ ★ 报什么就下什么 ⇒ 自证一致 ✅
        #
        #   ⚠★ 但**必须校验形态**（★ 否则前端传来一句怪话就能污染基图身份）——
        #     ★ 不像样的 sha ⇒ ★ 当它没给，★ 回落到服务端自己解析 ⚠
        # ★ `sha` 在上面已经**收下并规范化**过了 ⇒ ★ 这里直接判形态
        given = sha
        if given and not _SHA_RE.match(given):
            log.info(
                "前端给的 sha 形态不像（已忽略，改由服务端解析）project_ref=%s sha=%r",
                project.project_ref, given[:40],
            )
            given = ""

        if not given:
            try:
                verdict = fetch.resolve_ref(provider, repo_full, ref)
            except Exception:  # noqa: BLE001 —— ★ 网络炸了也要能继续（见函数文档的兜底）
                verdict = None

            if verdict is not None:
                if not verdict.ok:
                    # ★★ 私有 / 不存在 / 限流 / 分支错 —— ★ 每条都有**用户能看懂**的文案 ⚠
                    return DispatchOutcome(
                        failed=True, fail_code=verdict.reason_code,
                        fail_message=verdict.message or "解析不出这个仓库的版本。",
                    )
                given = verdict.sha
        # ★★ 否则：★ 前端给了 sha ⇒ ★ **一次 API 都不发**，直接用 ✅

        sha = given

        if sha:
            # ---- ⓪-1 ★★ 「有没有同样的？」----
            from graph import binding

            bg = binding.find(provider, repo_full, sha)
            if binding.is_ready(bg):
                # ★★★ **有，而且建好了** ⇒ ★★ 绑上就返回，★ **不拉取、不解析** ⚠
                #   ★ 这正是「有同样的，就直接返回……还快」的落点 ✅
                binding.bind(project.project_ref, bg, requested_ref=ref)
                log.info(
                    "复用现成基图（同步）project_ref=%s base=%s@%s ⇒ 不投作业",
                    project.project_ref, repo_full, sha[:12],
                )
                return DispatchOutcome(
                    reused=True, reused_sha=sha, base_graph=bg, created=False
                )

    payload = {
        "project_id": project.pk,
        "project_ref": project.project_ref,
        # ⚠★ 一期：**只有 staff 才会给非空 `path`**（内部调试，见 `_safe_source_path`）。
        #   ★ 普通用户这里是空 ⇒ ★★ 作业会**从远端拉取**（`B153`，`core/fetch.py`）。
        "path": source_path or "",
        # ★★ 作业靠这三样自己把源码拉下来（★ 不再需要调用方提供目录）
        "provider": project.provider,
        "repo_full_name": repo_full,
        "repo_url": project.repo_url,
        "commit": commit,
        # ★★ `B179`：**sha 一并带进 payload** ——
        #   ⚠ 这样作业**不必再解析一次**（★ 省两次 API 调用），
        #     ★★ 而且"按 sha 下载"才有依据（★ 一份基图永远对应同一份代码）⚠
        "sha": sha,
        # ★ 用户当时指定的分支 / tag（⚠ 空 ⇒ 默认分支）—— ★ 只作留痕
        "ref": (ref or "")[:128],
    }
    try:
        job, created = dispatch.submit(
            kind=Job.KIND_PARSE,
            project_ref=project.project_ref,
            payload=payload,
            priority=priority,
            # ★★ `B115` ④：同一项目同一版本重复投递 ⇒ **合并**（❌ 不是失败）
            # ⚠★ `B179`：去重键**换成 sha** —— ★ 以前用 `commit or 'HEAD'`，
            #   ★★ 而实测 `commit` 全是空 ⇒ 键永远是 `…:HEAD` ⇒ **两个不同版本会被并成一条** ⚠
            dedup_key=f"parse:{project.project_ref}:{sha or commit or 'HEAD'}",
        )
        return DispatchOutcome(job=job, created=created)
    except Exception:  # noqa: BLE001 —— ★ 入队失败已在 dispatch 里留痕，这里只负责如实上报
        return DispatchOutcome(
            failed=True, fail_code="enqueue_failed", fail_message="投递作业失败，请稍后再试。"
        )


# ===========================================================================
# 审核通过后「把作业接上」
# ===========================================================================


def approve_and_resume(
    review: ProjectReview,
    *,
    by,
    note: str = "",
    source_path: str = "",
    commit: str = "",
    # ⚠★ `B182`：同 `publish_project` —— ★ 前端算好的 sha（★ 空 ⇒ 服务端自己解析）
    sha: str = "",
    ) -> tuple[ProjectReview, Any]:
    """★★ **管理员放行 ⇒ 重投解析作业**（★ 链路第 ⑤ 步）。

    ⚠★ 为什么必须显式重投：★ 项目在「待审核」期间**没有解析、没有图**
      （`U3.1` 第 ④ 步：**通过后才允许投递解析作业**）⇒
      ★ 放行只是**解锁**，还差**真正跑一次**。

    ★ 所以把「放行」和「重投」**绑在一个函数里** ——
    ⚠ 否则将来一定会出现"点了放行，但谁都忘了重投，项目页永远是空的"。
    """
    review.approve(by=by, note=note)
    project = review.project
    if project is None:
        # ⚠ 项目已被删 ⇒ 不重投（★ 但放行动作本身已经记审计）
        return review, None

    # ★★★ **定版闸门**（`B103` / `B155`）——
    #   ⚠★ 已经有图 ⇒ **绝不能再投作业**（★ 那会覆盖图 ⇒ 让解释里的行区间失效）。
    #   ★ 正常路径下这里本来就是"没有图"（★ 待审核期间没解析），
    #     ⚠ 但"图被并发写进去"或"人工反复点放行"都可能走到这里 ⇒ ★ **必须挡**。
    if project.is_graph_built:
        return review, None

    # ⚠★ `B179`：`dispatch_parse` 现在返回 `DispatchOutcome`（★ 三种结局）⚠
    #   · ★ 投出去了 ⇒ `out.job` 有值 ⇒ ★ **照旧回给它**（★ 调用方要等这个作业）✅
    #   · ★★ **复用了现成基图** ⇒ `out.job` 是 `None`，而**项目已经有图了**
    #     （★ `binding.bind()` 已把 `graph_built_at` 置真）⇒ ★ **不用等，这正是"还快"** ✅
    #   · ★ 失败 ⇒ `out.job` 也是 `None`（★ 失败原因在 `out.fail_message` 里）
    #   ⚠★ 三种都返回 `out.job` 就对了 —— ★ **不要写死 `None`**（★ 我犯过这个错：
    #     那会让"真的投了作业"也返回 `None` ⇒ 调用方以为没投 ⇒ 永远等不到图）⚠
    out = dispatch_parse(
        project, source_path=source_path, commit=commit, priority=0,
        # ⚠★ `B182`：透传前端算好的 sha（★ 有它就不烧服务端的 API 配额）✅
        sha=sha or "",
    )
    return review, out.job


def public_projects():
    """★★ **列表 / 搜索的权威查询集** —— ★ 只有「已放行」的项目才该出现在列表里。

    ⚠★ 为什么把它固化成一个函数，而不是写在文档里：

    ★ 「未审核 / 被驳回的项目不该出现在首页」这条规则，⚠ 如果只写进文档，
      ★ **早晚有一个人写列表接口时忘了加这个 filter**。
      ⇒ ★★ 所以给一个**函数**，让后来的人**直接用**（❌ 而不是自己拼 `filter`）。

    ★ 注意它与 `is_public` **不是一回事**：

    | 字段 | 管什么 |
    |---|---|
    | `is_public` | ★ 这个项目的**页面**能不能被访问（★ 含"直接点链接进来"） |
    | `review_state` | ★ 它**够不够格出现在列表 / 搜索里** |
    """
    return Project.objects.filter(
        is_public=True,
        state=Project.STATE_ACTIVE,
        review_state=Project.REVIEW_APPROVED,
    )


# ===========================================================================
# 用户自助
# ===========================================================================


def my_publish_overview(user) -> dict[str, Any]:
    """★ 用户自己的发布面板（★ 把"我还剩几个额度"和"我的提交都怎么样了"合到一起）。

    ★★ 数据全部来自已有模块，❌ 不新造存储。
    """
    return {
        "upload": submission.my_upload_status(user),
        "submissions": submission.my_submissions(user, limit=20),
    }
