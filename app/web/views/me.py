"""Astrolabe · ① Web 层：**我的**（额度 / 提交记录 / 驳回原因）

★ 依据 `USERS-AND-AUTH.md` `U3.8`（★ **用户要能看见自己的申请被驳回的原因**）
+ `U3.9`（上传限额）。

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/me/upload/` | ★ 我还剩几个上传额度（★ **提交前先看**，避免白填一遍） |
| `GET` | `/api/me/submissions/` | ★★ **提交记录 + 驳回原因** |
| `GET` | `/api/me/overview/` | ★ 上面两个合并（SPA 一次拉完） |

---

★★ **这里是 `U3.8` 的落点** —— 用户对"我为什么被驳回"的可见性。

⚠★ 注意本模块**不自己拼字段**，而是直接用 `submission.my_submissions()` ——
  ★ 那是一份**有意过滤过的投影**：★ 只给 `user_message` / `decision_note`，
  ❌ **不给** `evidence` / `suggestion`（★ 那是**审核工作台的语言**）。
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from core import appsettings, submission
from web import permissions
from web.http import ok


def _limit(request: HttpRequest, default: int = 50, high: int = 200) -> int:
    try:
        return max(1, min(int(request.GET.get("limit", default)), high))
    except (TypeError, ValueError):
        return default


@require_http_methods(["GET"])
def upload(request: HttpRequest) -> JsonResponse:
    """★ 剩余额度（★ 前端在发布页顶部显示"今天还能传 N 个"）。"""
    user = permissions.current_user(request)
    if user is None:
        return JsonResponse(
            {"ok": False, "error": {"code": "unauthenticated", "message": "请先登录"}},
            status=401,
        )
    return ok(submission.my_upload_status(user))


@require_http_methods(["GET"])
def submissions(request: HttpRequest) -> JsonResponse:
    """★★ **我的提交记录**（★ 含被驳回的原因 —— `U3.8`）。"""
    user = permissions.current_user(request)
    if user is None:
        return JsonResponse(
            {"ok": False, "error": {"code": "unauthenticated", "message": "请先登录"}},
            status=401,
        )
    rows = submission.my_submissions(user, limit=_limit(request))
    return ok(
        {
            "submissions": rows,
            # ★ 顺手统计一下 —— ★ 前端拿去做空状态文案（"你还没有提交过项目"）
            "counts": {
                "total": len(rows),
                "pending": sum(1 for r in rows if r["status"] == "pending"),
                "approved": sum(1 for r in rows if r["status"] == "approved"),
                "rejected": sum(1 for r in rows if r["status"] == "rejected"),
            },
        }
    )


@require_http_methods(["GET"])
def storage_view(request: HttpRequest) -> JsonResponse:
    """★★ **我的存储空间**（`B152`）—— ★ 前端在发布页 / 设置页显示进度条。

    ★ 返回的是 ★ **"用了多少 / 上限多少 / 还剩多少"** ——
      ★★ 让 VIP 的"空间更大"**看得见**（`U1`：★ 只是额度更大，❌ 不是能看更多）。
    """
    user = permissions.current_user(request)
    if user is None:
        return JsonResponse(
            {"ok": False, "error": {"code": "unauthenticated", "message": "请先登录"}},
            status=401,
        )
    from core import storage

    cap = storage.check_capacity(user)
    per_project = appsettings.quota_for(
        getattr(getattr(user, "profile", None), "tier", None) or "free",
        getattr(user, "profile", None),
    )
    return ok(
        {
            **cap.to_dict(),
            # ★ 单项目上限（★ 与"总空间"一起给，⚠ 前端两个都要显示）
            "repo_bytes_max": int(per_project.get("repo_bytes_max") or 0),
            "repo_files_max": int(per_project.get("repo_files_max") or 0),
            # ★ 每个项目占了多少（★ 便于用户自己决定删哪个）
            "projects": _project_usage(user),
        }
    )


def _project_usage(user) -> list[dict]:
    from core.models import ProjectStorage

    rows = (
        ProjectStorage.objects.filter(owner=user)
        .order_by("-bytes_used")
        .values("project_ref", "bytes_used", "files_used")[:100]
    )
    return [
        {
            "project_ref": r["project_ref"],
            "bytes_used": r["bytes_used"],
            "files_used": r["files_used"],
        }
        for r in rows
    ]


@require_http_methods(["GET"])
def overview(request: HttpRequest) -> JsonResponse:
    """★ 发布面板（★ SPA 一次拉完，❌ 不用打两个请求）。"""
    user = permissions.current_user(request)
    if user is None:
        return JsonResponse(
            {"ok": False, "error": {"code": "unauthenticated", "message": "请先登录"}},
            status=401,
        )
    from core import publish

    return ok(publish.my_publish_overview(user))
