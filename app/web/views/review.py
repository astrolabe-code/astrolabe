"""Astrolabe · ① Web 层：**管理员审核队列**（`U3.7` / `U3.8`）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/admin/reviews/` | ★ 审核队列（默认看**待办**） |
| `POST` | `/api/admin/reviews/<id>/approve/` | ★ 放行（★ **并自动重投解析作业**） |
| `POST` | `/api/admin/reviews/<id>/reject/` | ★★ 驳回（★ **必须写理由**） |

---

# ★★ 这里就是 `U3.7` 那句要求的落点

> **用户原话**：「★★★ 所以，**审核里一定要显示表明为什么进审核**。」

⇒ ★ `_review_json()` **刻意比用户侧投影多给** `reason_text` / `evidence` / `suggestion`：

| 字段 | 给管理员 | 给用户 |
|---|---|---|
| `reason_text`（含判断要点） | ✅ | ❌ |
| `evidence`（检测证据） | ✅ | ❌ |
| `suggestion`（系统建议） | ✅ | ❌ |
| `user_message`（给提交者的说法） | ⚠ 备查 | ✅ |
| `decision_note`（决定理由） | ✅ | ✅ |

---

# ★★ 驳回必须带理由（**在视图层也拦一次**）

★ `ProjectReview.reject()` 已经会 `raise ValueError` ——
★ 这里**再拦一次只是为了给前端一个清楚的 400**（⚠ 否则会变成 500，★ 前端只能显示"服务器错误"）。
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from core.models import ProjectReview
from web import permissions
from web.http import fail, ok, read_json
from web.permissions import staff_only

#: ★ 队列一次最多返回多少条（⚠ 管理员不需要"翻到第 50 页"，★ 处理完再看新的）
MAX_QUEUE = 200


def _review_json(r: ProjectReview) -> dict:
    """★★ **管理员投影** —— ★ 含"为什么进审核"的完整四要素（`U3.7`）。"""
    return {
        "id": r.pk,
        "project_ref": r.project_ref,
        "project_name": r.project_name,
        "repo_url": r.repo_url,
        # ★ 谁提交的（★ `U4.7` 连带责任）
        "submitted_by": r.submitted_by_name,
        "submitted_at": r.created_at.isoformat() if r.created_at else None,

        # ---- ① 为什么进审核（★ U3.7 的四要素）----
        "reason_code": r.reason_code,
        "reason_text": r.reason_text,          # ★ 人类可读
        "evidence": r.evidence,                # ★ 检测证据
        "suggestion": r.suggestion,            # ★ 系统建议（⚠ 只是建议）

        # ---- ② 决定 ----
        "decision": r.decision,
        "auto_decided": r.auto_decided,        # ★ 系统自动 vs 人工
        "decided_by": r.decided_by.get_username() if r.decided_by_id else "",
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "decision_note": r.decision_note,
        "user_message": r.user_message,
        "quota_refunded": r.quota_refunded,

        # ★ 项目还在不在（⚠ 流水是 append-only，项目可能已被作者删掉）
        "project_exists": r.project_id is not None,
    }


@require_http_methods(["GET"])
@staff_only
def queue(request: HttpRequest) -> JsonResponse:
    """★ 审核队列 —— ★ **默认看待办**（⚠ 管理员的默认诉求就是"还有哪些没处理"）。

    ★ 排序用 `-created_at`（**先来先审**）——
      ⚠ 刻意不做"按提交者分组"之类的花活：★ 那会让老条目**永远沉底**。
    """
    decision = str(request.GET.get("decision") or ProjectReview.DECISION_PENDING).strip()
    if decision not in dict(ProjectReview.DECISION_CHOICES):
        decision = ProjectReview.DECISION_PENDING

    qs = (
        ProjectReview.objects.filter(decision=decision)
        .select_related("decided_by")
        .order_by("-created_at")[:MAX_QUEUE]
    )
    rows = [_review_json(r) for r in qs]

    return ok(
        {
            "decision": decision,
            "reviews": rows,
            # ★ 三个计数 —— ★ 后台标签页上直接显示"待审 N 条"
            "counts": {
                d: ProjectReview.objects.filter(decision=d).count()
                for d, _ in ProjectReview.DECISION_CHOICES
            },
        }
    )


def _get_review(review_id: int) -> ProjectReview | None:
    return ProjectReview.objects.filter(pk=review_id).select_related("project").first()


@require_http_methods(["POST"])
@staff_only
def approve(request: HttpRequest, review_id: int) -> JsonResponse:
    """★ **放行** —— ★★ 并**自动重投解析作业**（`B149` 的 `approve_and_resume`）。

    ⚠★ 一个必须显式处理的边界：**项目在待审核期间是没有图的**（`U3.1` 第 ④ 步
      "通过后才允许解析"）⇒ ★ 如果放行时**不重投**，项目页会**永远空着**。

    ⚠ 一期还有个现实问题：**服务端拉源码尚未实现** ⇒ 重投时必须知道 `source_path`。
      ★ 所以这里有条件地要求它 —— ★ **已经有图的项目不要求**（★ 那只是"重新放行"，
      ⚠ 别让管理员为了放行一个已解析的项目去翻目录）。
    """
    from core import publish
    from graph.models import Node

    review = _get_review(review_id)
    if review is None:
        return fail("审核项不存在", 404, code="not_found")
    if review.decision != ProjectReview.DECISION_PENDING:
        # ⚠ 幂等保护：★ 重复点击"放行"不该覆盖一次已经做出的**驳回**决定
        return fail("这条审核已经处理过了", 409, code="already_decided")

    body = read_json(request)
    note = str(body.get("note") or "").strip()[:2000]
    source_path = str(body.get("source_path") or "").strip()[:512]

    has_graph = bool(
        review.project_ref and Node.objects.filter(project_ref=review.project_ref).exists()
    )

    # ★★ `B153` 之后**不再要求 `source_path`** —— ★ 作业会**自己从远端拉**。
    #   ⚠ 只有 staff 传了才用（★ 内部调试：跳过拉取，直接用容器里的目录）。
    if has_graph and not source_path:
        review.approve(by=request.user, note=note)
        return ok({"review": _review_json(review), "dispatched": False})

    _, job = publish.approve_and_resume(
        review, by=request.user, note=note, source_path=source_path
    )
    review.refresh_from_db()
    return ok(
        {
            "review": _review_json(review),
            "dispatched": True,
            "job_id": job.pk if job is not None else None,
            "job_state": job.state if job is not None else "",
        }
    )


@require_http_methods(["POST"])
@staff_only
def reject(request: HttpRequest, review_id: int) -> JsonResponse:
    """★★ **驳回** —— ★★ **必须写理由**（★ 用户要求：「用户要能看见自己的申请被驳回的原因」）。

    ⚠★ 这里在视图层**再拦一次空理由** —— ★ `ProjectReview.reject()` 已经会 `raise`，
      ★ 但那是 `ValueError` ⇒ ⚠ 会变成 **500**，★ 前端只能显示"服务器错误"。
      ⇒ ★ 翻译成 400 + 清楚的原因码。
    """
    review = _get_review(review_id)
    if review is None:
        return fail("审核项不存在", 404, code="not_found")
    if review.decision != ProjectReview.DECISION_PENDING:
        return fail("这条审核已经处理过了", 409, code="already_decided")

    body = read_json(request)
    note = str(body.get("note") or "").strip()
    if not note:
        return fail("驳回必须填写理由（用户会看到它）", 400, code="missing_reason")

    # ★ 是否**退还额度**：★ 默认退（★ 驳回往往意味着"材料不全，请补齐再来"）
    #   ⚠ 但管理员可以显式 `refund_quota=false`（★ 情形：反复提交同样的东西）
    refund = bool(body.get("refund_quota", True))

    try:
        review.reject(
            by=request.user,
            note=note[:2000],
            user_message=str(body.get("user_message") or "")[:400],
            refund_quota=refund,
        )
    except ValueError as exc:
        return fail(str(exc), 400, code="missing_reason")

    review.refresh_from_db()
    return ok({"review": _review_json(review), "refunded": bool(review.quota_refunded)})
