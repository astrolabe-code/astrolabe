"""Astrolabe · ① Web 层：作业接口（列表 / 详情 / 取消）

★ 契约：`frontend-contract.md` §2 的作业行（② 型 envelope）。

⚠ 可见性（`frontend-contract.md` §2：`error?(本人)`）：

| 字段 | 谁可见 |
|---|---|
| 作业基本信息（kind / state / progress） | 能**读**该项目的人 |
| ★ `error`（错误详情） | ★ **仅能改该项目的人**（owner / 管理员）—— 错误信息可能含路径等细节 |
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from jobs.models import Job
from web import permissions
from web.http import fail, ok, ok_flat

JOBS_PAGE_MAX = 100


def _job_json(job: Job, *, can_edit: bool) -> dict:
    data = {
        "id": job.pk,
        "kind": job.kind,
        "state": job.state,
        "progress": job.progress,
        "stage": job.stage,
        "message": job.stage,          # ⚠ 契约里的 `message` = 人类可读阶段，与 `stage` 同值
        "created_at": job.queued_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
    if can_edit and job.error_msg:
        data["error"] = job.error_msg
    return data


@require_http_methods(["GET"])
def project_jobs(request: HttpRequest, project_ref: str) -> JsonResponse:
    """`GET /api/projects/<project_ref>/jobs/` —— ② 型。"""
    project = permissions.get_project(request, project_ref)
    if project is None or not permissions.can_view(request, project):
        return fail(permissions.NOT_FOUND, 404)

    can_edit = permissions.can_edit(request, project)
    qs = Job.objects.filter(project_ref=project_ref).order_by("-queued_at")[:JOBS_PAGE_MAX]
    return ok_flat(jobs=[_job_json(j, can_edit=can_edit) for j in qs])


@require_http_methods(["GET"])
def job_detail(request: HttpRequest, job_id: int) -> JsonResponse:
    """`GET /api/jobs/<id>/` —— ② 型。"""
    job = Job.objects.filter(pk=job_id).first()
    if job is None:
        return fail("作业不存在", 404)

    project = permissions.get_project(request, job.project_ref)
    if project is None or not permissions.can_view(request, project):
        # ★ 越权与不存在**一律 404**（❌ 不要用 403 泄露"作业存在"）
        return fail("作业不存在", 404)

    return ok_flat(job=_job_json(job, can_edit=permissions.can_edit(request, project)))


@require_http_methods(["POST"])
def job_cancel(request: HttpRequest, job_id: int) -> JsonResponse:
    """`POST /api/jobs/<id>/cancel/` —— ★ **只置标志**（契约 §2 原文）。

    ⚠ 一期语义（诚实说明）：
      · `queued` ⇒ 从 Redis 队列移除 + 置 `canceled` ✅ **真的能取消**
      · `running` ⇒ ⚠ **只能置标志**，正在跑的解析**不会被打断**
        （打断需要 worker 协作，属后续；契约原文也是"只置标志"）
    """
    job = Job.objects.filter(pk=job_id).first()
    if job is None:
        return fail("作业不存在", 404)

    project = permissions.get_project(request, job.project_ref)
    if project is None or not permissions.can_view(request, project):
        return fail("作业不存在", 404)
    if not permissions.can_edit(request, project):
        return fail("需要项目所有者权限", 403, code="forbidden")

    from jobs import queue

    canceled = False
    if job.state == Job.STATE_QUEUED:
        try:
            queue.remove(job.pk)
        except Exception:  # noqa: BLE001 —— ⚠ 队列里没这条也算取消成功
            pass
        job.state = Job.STATE_CANCELED
        job.save(update_fields=["state"])
        canceled = True
    elif job.state == Job.STATE_RUNNING:
        job.error_code = "cancel_requested"
        job.save(update_fields=["error_code"])

    return ok_flat(canceled=canceled, state=job.state)


__all__ = ["project_jobs", "job_detail", "job_cancel"]
