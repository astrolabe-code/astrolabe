"""Astrolabe · 共享内核：**提交上线申请**（限额闸门 + 流水 + 许可核验）

★ 依据 `USERS-AND-AUTH.md`：`U3.4`（许可核验）· `U3.7`（为什么进审核）·
`U3.8`（用户要看得到原因）· `U3.9`（防刷审核）· `U9.4`（付费可见性）

---

# ★★ 这个模块存在的唯一理由：**把"提交"变成一件原子的事**

⚠★ 天真的写法是：

```python
if check_upload_quota(user).allowed:        # ← 读到"还剩 1 个"
    ProjectReview.objects.create(...)       # ← 建流水
```

★★ **这个写法有竞态**：两个请求**同时**读到"还剩 1 个" ⇒ **双双通过**
（★ 经典的 check-then-use）。⇒ ★ 恶意刷的人只要**并发发请求**就绕过了限额。

⇒ ★★ 正确做法：**`transaction.atomic()` + `select_for_update()` 锁住该用户那一行**，
   ★ 让**同一个用户**的提交**串行**（⚠ 不同用户之间**互不影响**，不会拖慢全站）。

---

# ★★ 提交顺序（顺序本身是有讲究的）

```
① 锁用户行
② 查额度          ← ★ 不够就【不建流水】直接返回（❌ 不浪费一次计数）
③ 许可核验
④ 建流水（★ 无论自动放行还是进审核，【都必须建】）
```

⚠★ 第 ④ 步为什么"自动放行也要建"：

- ★ 它是**限额的依据** —— ⚠ 不建则**自动放行的提交不计次** ⇒ **防刷漏掉一半**
- ★ 它是**审计** —— 将来要能回答"这个项目什么时候自动过的、依据是什么"

---

# ★ 「用户能看见自己的申请被驳回的原因」

★ 这是用户明确要求的：

> **用户原话**：「申请要能驳回，**用户要能看见自己的申请被驳回的原因**。」

⇒ ★ 所以本模块提供 `my_submissions()`（**给用户看的**），它与后台视图**读同一批数据**，
  但★ **只暴露该给用户看的字段**：

| 字段 | 给用户？ | 说明 |
|---|---|---|
| `decision` | ✅ | 通过 / 待审核 / 被驳回 |
| `user_message` | ✅ | ★ 系统核验时的说明 |
| `decision_note` | ✅ | ★★ **管理员驳回的理由 —— 用户最需要的就是这个** |
| `reason_text` / `evidence` | ❌ | ⚠ **只给管理员**（含内部判断要点，如"权利人可能就是你"） |
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from core import licensing, quota
from core.licensing import DECISION_ALLOW, DECISION_REJECT
from core.models import Project, ProjectReview, UserProfile

# ===========================================================================
# 结果
# ===========================================================================

@dataclass
class SubmissionResult:
    """★ 一次提交流程的结论。"""

    accepted: bool = False
    #: ★ 建出来的流水（⚠ 被限额拦下时为 `None`）
    review: ProjectReview | None = None
    quota: quota.QuotaVerdict | None = None
    license_verdict: licensing.LicenseVerdict | None = None
    #: ★★ **给用户看的说明** —— ★ 无论是"限额拦下"还是"许可结论"，都从这里取
    user_message: str = ""

    @property
    def auto_allowed(self) -> bool:
        return bool(self.review and self.review.auto_decided
                    and self.review.decision == ProjectReview.DECISION_APPROVED)

    @property
    def needs_review(self) -> bool:
        return bool(self.review and self.review.decision == ProjectReview.DECISION_PENDING)


# ===========================================================================
# 闸门
# ===========================================================================

def submit_project(
    project: Project,
    user,
    *,
    root: str | None = None,
    license_verdict: licensing.LicenseVerdict | None = None,
    require_file: bool | None = None,
    defer_license: bool = False,
    at: datetime | None = None,
) -> SubmissionResult:
    """★ **上传闸门** —— 限额 + 许可核验 + 建流水，**一次事务做完**。

    Args:
        project: 要提交的项目（★ 调用方应先建好 `Project` 记录）
        user: 提交者
        root: 源码目录（★ 用于许可核验；⚠ 与 `license_verdict` 二选一）
        license_verdict: 直接给核验结论（★ 便于单测 / 复用已算好的结果）
        require_file: 覆盖许可开关（⚠ `None` = 读 `AppSetting`）
        defer_license: ★★ **源码还没拉下来 ⇒ 核验推迟到作业里**
            （★ 见 `licensing.deferred()`：它**不等于** `missing`）
        at: 用于测试的时间注入

    ⚠★ **本函数不抛业务异常** —— ★ 限额不足是**正常业务情况**，
      统一通过 `SubmissionResult.accepted=False` + `user_message` 返回
      （★ 让调用方（Web 层）好写，❌ 不用 try/except 区分）。
    """
    User = get_user_model()

    with transaction.atomic():
        # ---- ① ★★ 锁住这个用户 —— 让【同一用户】的提交串行（不同用户互不影响）----
        #   ⚠ 不加这一步就是经典的 check-then-use 竞态：
        #     两个并发请求会各自读到"还剩 1 个"，双双通过（★ 限额被绕过）
        User.objects.select_for_update().filter(pk=getattr(user, "pk", None)).first()

        profile = ensure_profile(user)

        # ---- ② 额度（★ 不够就返回，❌ 不建流水 —— 不浪费一次计数）----
        verdict = quota.check_upload_quota(
            user, at=at, repo_url=project.repo_url or "", profile=profile
        )
        if not verdict.allowed:
            return SubmissionResult(
                accepted=False, quota=verdict, user_message=verdict.user_message
            )

        # ---- ③ 许可核验 ----
        if defer_license:
            # ★★ 源码还没拉 ⇒ **核验推迟**（★ 但**流水照建**：限额必须当场落实）
            lv = licensing.deferred()
        else:
            lv = license_verdict or licensing.evaluate(root, require_file=require_file)

        project.repo_url = (project.repo_url or "")[:512]
        if defer_license:
            # ⚠ 推迟时**不写许可字段** —— 否则会把 `Project.license_*` 清成空，
            #   看起来像"核验过了、没有许可证"（★ 又是"说错原因"）
            project.save(update_fields=["repo_url", "updated_at"])
        else:
            # ★ 把核验结果写到项目上（★ 这些字段用于"批量收回"，见 `license_exception`）
            project.license_spdx = (lv.spdx or "")[:64]
            project.license_category = (lv.category or "")[:16]
            project.license_evidence = lv.evidence
            project.license_exception = lv.decision != DECISION_ALLOW
            project.save(
                update_fields=[
                    "license_spdx", "license_category", "license_evidence",
                    "license_exception", "repo_url", "updated_at",
                ]
            )

        # ---- ④ ★★ 建流水（★ 无论哪种结论都必须建 —— 它是限额的依据 + 审计）----
        review = _create_review(project, user, lv)

        project.review_state = _review_state_for(lv.decision)
        project.save(update_fields=["review_state", "updated_at"])

        return SubmissionResult(
            accepted=True,
            review=review,
            quota=verdict,
            license_verdict=lv,
            user_message=lv.user_message,
        )


def _decision_for(decision: str) -> str:
    """★ 核验结论 → 流水的 `decision`（★ 建流水与更新流水**共用同一套映射**）。"""
    if decision == DECISION_ALLOW:
        return ProjectReview.DECISION_APPROVED
    if decision == DECISION_REJECT:
        return ProjectReview.DECISION_REJECTED
    return ProjectReview.DECISION_PENDING


def _review_state_for(decision: str) -> str:
    if decision == DECISION_ALLOW:
        return Project.REVIEW_APPROVED
    if decision == DECISION_REJECT:
        return Project.REVIEW_REJECTED
    return Project.REVIEW_PENDING


def _verdict_fields(lv: licensing.LicenseVerdict) -> dict:
    """★ 核验结论 → 流水字段（★ **建与更新共用** —— ⚠ 两处各写一遍早晚会不一致）。"""
    return {
        "reason_code": lv.reason_code[:32],
        "reason_text": lv.reason_text[:400],
        "evidence": lv.evidence,
        "suggestion": lv.suggestion[:200],
        "user_message": lv.user_message[:400],
    }


def _auto_note(lv: licensing.LicenseVerdict) -> str:
    """★ 自动拒绝时写下的理由（★ 用户也会看到它 —— `my_submissions().reject_reason`）。"""
    return f"系统自动拒绝：{lv.reason_text[:180]}"


def _auto_fields(lv: licensing.LicenseVerdict) -> dict:
    """★ 「系统自动判定」的公共字段（★ 建与更新共用）。"""
    from django.utils import timezone

    decision = _decision_for(lv.decision)
    out: dict = {
        "decision": decision,
        "auto_decided": True,
        "decided_at": timezone.now(),
    }
    if decision == ProjectReview.DECISION_REJECTED:
        out["decision_note"] = _auto_note(lv)
        # ★★ **不计入额度**：★ 这是"材料不全，请补齐再来"，不该罚用户
        #   （★ 否则他改一次文件名就亏一个额度）
        out["quota_refunded"] = True
    return out


def _create_review(project: Project, user, lv: licensing.LicenseVerdict) -> ProjectReview:
    """★ 建一条流水（★ **三种结论都必须建** —— 见模块文档）。"""
    from django.utils import timezone

    common = {
        "project": project,
        "project_ref": project.project_ref,
        "project_name": project.name[:200],
        "submitted_by": user if getattr(user, "pk", None) else None,
        "submitted_by_name": (getattr(user, "username", "") or "")[:150],
        "repo_url": (project.repo_url or "")[:512],
        **_verdict_fields(lv),
    }

    if lv.decision == DECISION_ALLOW:
        # ★ 自动放行（⚠ 仍建流水：限额依据 + 审计）
        return ProjectReview.objects.create(
            **common, **_auto_fields(lv), decided_at=timezone.now()
        )

    if lv.decision == DECISION_REJECT:
        return ProjectReview.objects.create(**common, **_auto_fields(lv))

    # ★ 进人工审核（★ 含「待核验」这个中间态 —— 它同样是 pending）
    return ProjectReview.objects.create(
        **common, decision=ProjectReview.DECISION_PENDING
    )


def resolve_license(
    review: ProjectReview,
    license_verdict: licensing.LicenseVerdict,
    *,
    project: Project | None = None,
    at: datetime | None = None,
) -> tuple[ProjectReview, Project | None]:
    """★★ **核验完成后，就地更新那条流水** —— 把「**待核验**」改成**真结论**。

    ★★ 为什么是"就地更新"而不是"再建一条"：

    | | 再建一条 | ★ 就地更新 |
    |---|---|---|
    | ★ 限额计数 | ⚠ **多条 ⇒ 计成两次**（用户白白亏一个额度） | ✅ 始终一条 |
    | ★ 用户看到的 | ⚠ 两条（一条"待核验"一条真结论）⇒ **困惑** | ✅ 一条，且是**真原因** |

    ⚠★★ **不能覆盖人工已裁决的结论** —— 如果管理员已经放行/驳回过了，
      ★ 这次核验**只更新证据与说明**，❌ **不动 `decision`**
      （★ 否则等于**系统推翻人的判断**，与"决定权在管理员"直接冲突）。

    Returns: `(review, project)`
    """
    from django.utils import timezone

    from core.models import AuditLog

    now = at or timezone.now()
    if project is None:
        project = review.project

    fields = {
        **_verdict_fields(license_verdict),
        "updated_at": now,
    }

    # ---- ★★ 人工已裁决 ⇒ 只补证据，❌ 不动结论 ----
    manually_decided = (not review.auto_decided) and review.decision != ProjectReview.DECISION_PENDING

    if not manually_decided:
        fields.update(_auto_fields(license_verdict))
    else:
        # ★ 顶多把"自动拒绝"之外的状态同步一下（人工结论保持）
        pass

    for k, v in fields.items():
        setattr(review, k, v)
    review.save()

    # ---- 同步项目上的许可字段（★ 供"批量收回"用，见 `license_exception`）----
    if project is not None:
        project.license_spdx = (license_verdict.spdx or "")[:64]
        project.license_category = (license_verdict.category or "")[:16]
        project.license_evidence = license_verdict.evidence
        project.license_exception = license_verdict.decision != DECISION_ALLOW
        if not manually_decided:
            project.review_state = _review_state_for(license_verdict.decision)
        project.save(
            update_fields=[
                "license_spdx", "license_category", "license_evidence",
                "license_exception", "review_state", "updated_at",
            ]
        )

    AuditLog.objects.create(
        action="review.license_resolved",
        target_kind="ProjectReview",
        target_id=str(review.pk),
        detail={
            "project_ref": review.project_ref,
            "reason_code": license_verdict.reason_code,
            "decision": review.decision,
            "auto": not manually_decided,
            "manually_decided": manually_decided,
        },
    )
    return review, project


# ===========================================================================
# 用户档案
# ===========================================================================

def ensure_profile(user) -> UserProfile | None:
    """★ 取用户档案，**没有就建**（⚠ 不需要调用方每次自己判空）。"""
    if not getattr(user, "pk", None):
        return None
    profile = getattr(user, "profile", None)
    if profile is None:
        profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


# ===========================================================================
# ★★ 「用户要能看见自己的申请被驳回的原因」
# ===========================================================================

def my_submissions(user, *, limit: int = 50) -> list[dict[str, Any]]:
    """★★ **给用户看的**提交记录 —— 含**被驳回的原因**。

    ★ 这是用户明确要求的能力：

    > 「申请要能驳回，**用户要能看见自己的申请被驳回的原因**。」

    ★★ **这里是有意过滤过的投影** —— ⚠ 只暴露该给用户看的字段：

    | 给用户 | 不给用户 |
    |---|---|
    | `decision`（状态） | `reason_text`（★ 含内部判断要点） |
    | `decision_note`（★ **驳回理由**） | `evidence`（★ 检测证据细节） |
    | `user_message`（★ 系统说明） | `suggestion`（★ 给管理员的建议） |

    ⚠★ 为什么不给 `evidence` / `suggestion`：★ 那是**审核工作台的语言**
      （"建议人工确认提交者身份"这种话**不该让用户看见**）。
      ★ 用户要看的是"**我该做什么**"，不是"我们内部怎么讨论你"。
    """
    if not getattr(user, "pk", None):
        return []

    rows = (
        ProjectReview.objects.filter(submitted_by=user)
        .order_by("-created_at")
        .values(
            "id", "project_ref", "project_name", "repo_url", "created_at",
            "decision", "decided_at", "user_message", "decision_note",
            "reason_code", "quota_refunded",
        )[:limit]
    )

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "project_ref": r["project_ref"],
                "project_name": r["project_name"],
                "repo_url": r["repo_url"],
                "submitted_at": r["created_at"].isoformat() if r["created_at"] else None,
                "status": r["decision"],
                # ★ 状态的中文说法（★ 给用户看的，不用后台那套词）
                "status_text": _status_text(r["decision"]),
                # ★ 系统核验说明
                "message": r["user_message"] or "",
                # ★★ **驳回原因** —— 用户最需要的字段
                "reject_reason": r["decision_note"] if r["decision"] == "rejected" else "",
                "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
                # ★ 告知额度未被占用（★ 用户能放心重试）
                "quota_refunded": r["quota_refunded"],
            }
        )
    return out


def _status_text(decision: str) -> str:
    return {
        ProjectReview.DECISION_PENDING: "审核中",
        ProjectReview.DECISION_APPROVED: "已通过",
        ProjectReview.DECISION_REJECTED: "未通过",
    }.get(decision, decision)


def my_upload_status(user, *, at: datetime | None = None) -> dict[str, Any]:
    """★ 用户自己看"我还剩几个额度"（★ 提交前先看，避免白填一遍）。"""
    profile = ensure_profile(user)
    verdict = quota.check_upload_quota(user, at=at, profile=profile)
    return {
        "allowed": verdict.allowed,
        "remaining_day": verdict.remaining_day,
        "remaining_week": verdict.remaining_week,
        "per_day": verdict.per_day,
        "per_week": verdict.per_week,
        "message": verdict.user_message,
        "retry_after": verdict.retry_after.isoformat() if verdict.retry_after else None,
        "unlimited": verdict.unlimited,
    }
