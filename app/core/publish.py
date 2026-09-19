"""Astrolabe · 共享内核：**发布编排** —— ★★ 把散落的模块串成**一条链路**

> 在此之前，`core/` 里的模块（许可核验 / 限额 / 邀请 / OAuth / 归属校验 / 审核）**各自独立**，
> ★ 没有任何一个地方能回答「**用户从点『发布』到看到图，中间发生了什么**」。
> ★★ 本模块就是那个答案。

---

# ★★★ 完整链路（★ 每一步都能说出"不过时会怎样"）

```
① 归属校验（Gate 0 第 ②③ 步）        ← core/oauth.py      ⚠ 同步（一次 API 调用，快）
     │  不是你的仓库 / 是 Fork / 是组织仓库 ⇒ ❌ 拒绝，给出可读原因
     ▼
② 建 Project + 上传闸门               ← core/submission.py
     │  超限额 / 重复仓库 ⇒ ❌ 拒绝（★ 且【不留孤儿项目】）
     │  ★ 许可核验【推迟】（源码还没拉下来 —— 见 licensing.deferred()）
     ▼
③ 投递 parse 作业                     ← jobs/dispatch.py  ⚠ O(毫秒) 两次写
     │  ★ job_id 立刻返回（★ B115 ①：投递即入队，❌ 不得静默拒绝）
     ▼
④ 【作业层】拉源码 → 许可核验 → 解析 → 写图   ← jobs/tasks.py
     │  ★ 核验完 ⇒ submission.resolve_license() 把那条流水【就地更新】成真结论
     │  · 宽松 ⇒ ✅ 放行，继续解析
     │  · 其余 ⇒ ⚠ 停在「待人工审核」，**不解析**（★ U3.1 第 ④ 步）
     ▼
⑤ 【管理员】放行 ⇒ ★ 重投作业 ⇒ 解析 ⇒ 图就出来了
```

---

# ★★ 为什么 ① 同步、④ 异步（这个切分是刻意的）

| 步骤 | 耗时 | 放哪 |
|---|---|---|
| ★ **归属校验** | ★ **一次 HTTP 调用** | ★ **同步**（不留作业、立刻能给用户答案） |
| ★★ **拉源码 + 许可核验 + 解析** | ★★ **秒级到分钟级** | ★★ **异步**（⚠ 放同步会把 web 线程占死 —— `A3` 红线的本意） |

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

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.db import transaction

from core import appsettings, fetch, licensing, oauth, quota, storage, submission
from core.models import OAuthIdentity, Project, ProjectReview

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
    access_token: str,
    repo_full_name: str,
    name: str = "",
    desc: str = "",
    source_path: str = "",
    priority: int | None = None,
    fetcher: Any = None,
    at: datetime | None = None,
) -> PublishResult:
    """★★ **发布一个项目** —— ★★ 见模块文档的完整链路。

    Args:
        user: 发布者（★ 必须已绑定该 provider 的第三方身份）
        provider: `github` / `gitee`
        access_token: ★★ **本次授权拿到的 token** —— ⚠ **只在本函数内使用一次**
            （★ 用来做归属校验，❌ **不落库**。见 `core/oauth.py` 模块文档）
        repo_full_name: `owner/repo`
        name: 项目显示名（⚠ 省略 ⇒ 用仓库名）
        source_path: ⚠★ **只给内部 / 管理员用的调试口子**（`B152`）——
            ★ **普通用户不要传**：★ 他的源码应当由作业层从 `repo_url` 拉取，
            ★ 而拉取**尚未实现** ⇒ 作业会**明确失败**（❌ 不是假装成功）。
            ⚠★ 之所以要这么分：★ `source_path` 能被用来**读容器里的任何目录**
            （★ 这台机器上还跑着数据库）⇒ ★ **不能对普通用户开放**。
        priority: 队列优先级（⚠ `None` ⇒ 从配额里取 `queue_priority`，★ VIP 先出图）

    ⚠★ **本函数【不抛业务异常】** —— ★ 所有"不过"都通过返回值表达
      （★ 同 `submit_project`：这是**正常业务情况**，❌ 不是程序错误）。
    """
    r = PublishResult()

    # ==================================================================
    # ① ★★ 归属校验（Gate 0 第 ②③ 步）—— ⚠ 先做，因为后面每一步都很贵
    # ==================================================================
    identity = OAuthIdentity.objects.filter(user=user, provider=provider).first()
    if identity is None:
        return _fail(
            r, step="identity", code="identity_missing",
            message=f"请先用 {provider} 登录一次，确认账号归属后再发布。",
        )

    own = oauth.verify_repo_ownership(
        provider, access_token,
        repo_full_name=repo_full_name,
        # ★★ 比【数字 ID】（⚠ 不比 login —— `U3.2` 坑 1：用户名会改）
        provider_user_id=identity.provider_user_id,
        fetcher=fetcher,
    )
    if not own.ok:
        return _fail(r, step="ownership", code=own.reason_code, message=own.message)
    r.steps["ownership"] = {"ok": True, "repo": own.repo.get("full_name") or repo_full_name}

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

    #  ★★★ 闸门 ②：**这个仓库（估计）放得下吗** —— ★★ 用的是**归属校验那次请求
    #    已经拿到的 `repo.size`**（★ GitHub 单位是 KB）⇒ ⚠ **零额外开销**。
    #  ⚠★ 它只是**估计值**（★ 见 `fetch.check_remote_size` 的两条坑），
    #    ★ 所以**第三道（边解边数）必须留着** —— 见 `core/fetch.py`。
    size_check = fetch.check_remote_size(own.repo, remaining_bytes=cap.remaining_bytes)
    if not size_check.ok:
        return _fail(r, step="storage", code=size_check.reason_code, message=size_check.message)
    r.steps["remote_size"] = {
        "ok": True, "estimated_bytes": size_check.bytes, "known": size_check.known
    }

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
            is_public=True,
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
    job, created = _dispatch_parse(
        project,
        # ★★ 只放行**存储空间内**的路径（`B152`）——
        #   ⚠★ 见 `_safe_source_path()`：这是"不把任意路径交给作业"的最后一道。
        source_path=_safe_source_path(source_path, user),
        commit="",
        priority=priority if priority is not None else _queue_priority(user),
    )
    if job is None:
        # ★ 作业没投出去 ⇒ ★★ **如实告诉用户**（❌ 不假装"已受理"）
        return _fail(
            r, step="dispatch", code="enqueue_failed",
            message=(
                "项目已创建，但解析任务投递失败，请稍后重试或联系站长。"
                "（这次提交仍然占用了你的上传额度）"
            ),
        )

    r.ok = True
    r.job = job
    r.job_created = created
    r.steps["dispatch"] = {"ok": True, "job_id": job.pk, "created": created}
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


def _dispatch_parse(project: Project, *, source_path: str, commit: str, priority: int):
    """★ 投递解析作业（★ 延迟 import —— 见模块文档的分层说明）。"""
    from jobs import dispatch
    from jobs.models import Job

    payload = {
        "project_id": project.pk,
        "project_ref": project.project_ref,
        # ⚠★ 一期：**只有 staff 才会给非空 `path`**（内部调试，见 `_safe_source_path`）。
        #   ★ 普通用户这里是空 ⇒ ★★ 作业会**从远端拉取**（`B153`，`core/fetch.py`）。
        "path": source_path or "",
        # ★★ 作业靠这三样自己把源码拉下来（★ 不再需要调用方提供目录）
        "provider": project.provider,
        "repo_full_name": fetch.repo_full_from_url(project.repo_url),
        "repo_url": project.repo_url,
        "commit": commit,
    }
    try:
        return dispatch.submit(
            kind=Job.KIND_PARSE,
            project_ref=project.project_ref,
            payload=payload,
            priority=priority,
            # ★★ `B115` ④：同一项目同一版本重复投递 ⇒ **合并**（❌ 不是失败）
            dedup_key=f"parse:{project.project_ref}:{commit or 'HEAD'}",
        )
    except Exception:  # noqa: BLE001 —— ★ 入队失败已在 dispatch 里留痕，这里只负责如实上报
        return None, False


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

    job, created = _dispatch_parse(
        project, source_path=source_path, commit=commit, priority=0
    )
    return review, job


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
