"""Astrolabe · **协作者接口**（★ `B202` / `B206` / `B207` · 2026-10-16）

★★★ **本文件只做一件事**：★ 把 `core_collaborator` 那张表暴露成 HTTP ⚠

## ★★ 六条口径（★ 全是已登记的决策）

```
① ★★ **不发链接、不要 token、无接受流程**（* `B206`）——
     · · ★ owner 在管理页**输入用户名** ⇒ * 当场成为协作者 ✅
     · · ★★ 形态对齐微信小程序（* 所有者原话）——* 选人加人 ⚠

② ★★ **三个端点**（* `B206`③）：* 列表 / 按用户名添加 / 移除 ✅

③ ★★ **谁能管**（* 加人 / 移除）= **owner ∨ staff** ⚠
     · · ★ 协作者**不能**加 / 移协作者（* 邀请是项目主的权力，* A24③）⚠
④ ★★ **谁能看名单** = `can_edit`（* owner ∨ 协作者 ∨ staff）——
     · · ★ `B207`① 齐平：* 项目内访问齐平 ⇒ * 协作者看得到都有谁 ⚠

⑤ ★★ **幂等**（* `B206`④）：
     · · ★ 已是对员 ⇒ * 200 `already:true`（* ❌ 不是 409）✅
     · · ★ 移除一个不是成员的用户 ⇒ * 200 `removed:false` ✅

⑥ ★★ **边界**（* `B206`④）：* 用户名不存在 ⇒ * 404 `user_not_found` ·
     * 拿 owner 自己下手 ⇒ * 400（* owner 本就全权，* 不需要那一行）⚠
```

## ★★ 审计（`B206`⑤ / `B202`③）

```
★★ 加人 / 移除都写 `AuditLog` ✅
   · · ★ 表里**没有** created_at / invited_by ⇒* "谁邀的、何时进的"
     **只能查审计**（* 存两份必然打架，* 同 `B197`）⚠
```

⚠ 响应形态一律 **①**（`{ok:true,data:{…}}`）—— * `http.py` 规定新接口用它 ⚠
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.views.decorators.http import require_http_methods

from core.models import AuditLog, Collaborator, Project
from web.http import fail, ok, read_json
from web.permissions import can_edit, can_manage_members, can_view, current_user

User = get_user_model()

#: ★ 用户名最长（★ 与 Django `User.username` 的 150 一致）
USERNAME_MAX = 150


# ---------------------------------------------------------------------------
# 列表 / 添加
# ---------------------------------------------------------------------------

@require_http_methods(["GET", "POST"])
def collection(request: HttpRequest, project_ref: str):
    """`GET/POST /api/projects/<ref>/collaborators/`。

    ## GET

    ⇒ `{items:[{username}], total}`

    ⚠★ 协作者也能看名单（`B207`① 齐平）——* 但**加人 / 移除只有 owner/staff** ⚠

    ## POST

    `{username}` ⇒ `{added, already, username}`

    ⚠★ **幂等**：* 已是对员 ⇒ * 200 `already:true`，* ❌ 不是 409 ⚠
    """
    project = Project.objects.filter(project_ref=project_ref).first()
    if project is None or not can_view(request, project):
        # ⚠ 越权统一 404（与"不存在"不可区分 ——* 同其它项目端点）⚠
        return fail("项目不存在或无权访问", 404)

    if request.method == "POST":
        if not can_manage_members(request, project):
            return fail("只有项目所有者能管理协作者", 403, code="forbidden")
        return _add(request, project)

    if not can_edit(request, project):
        return fail("没有权限查看协作者名单", 403, code="forbidden")
    return _list(project)


def _list(project: Project):
    # ★★ 按用户名排（* 稳定、* 可读）✅
    usernames = list(
        Collaborator.objects.filter(project=project)
        .order_by("user__username")
        .values_list("user__username", flat=True)
    )
    return ok({"items": [{"username": u} for u in usernames], "total": len(usernames)})


def _add(request: HttpRequest, project: Project):
    body = read_json(request)
    username = str(body.get("username") or "").strip()[:USERNAME_MAX]
    if not username:
        return fail("请填写要添加为协作者的用户名", 400, code="missing_username")

    target = User.objects.filter(username=username).first()
    if target is None:
        # ⚠ 404（* 不是 400）——* "没有这个用户"是**事实判定**，* 告诉 owner 他填错了 ⚠
        return fail("没有这个用户", 404, code="user_not_found")

    # ⚠★ owner 本就全权 ⇒* 不需要那一行（* `B206`④）⚠
    if target.pk == project.owner_id:
        return fail("项目所有者不需要添加为协作者", 400, code="owner_not_allowed")

    row, created = Collaborator.objects.get_or_create(project=project, user=target)
    if created:
        _audit(request, "collaborator.add", project, username)

    return ok({"added": True, "already": not created, "username": username})


# ---------------------------------------------------------------------------
# 移除
# ---------------------------------------------------------------------------

@require_http_methods(["DELETE"])
def remove(request: HttpRequest, project_ref: str, username: str):
    """`DELETE /api/projects/<ref>/collaborators/<username>/` —— ★ 移除协作者。

    ⚠★ **幂等**：* 移除一个不是成员的用户 ⇒ * 200 `removed:false` ✅
    ⚠★ **被移除者已建的笔记 / 评论全留着**（* `B202`③）——
      · ★ 没有"冻结"这个动作（* 没有状态可置），* 他只是**不能再改** ✅
      · ★★ 不加分支、* 不加字段、* 数据一条不丢 ✅
    """
    project = Project.objects.filter(project_ref=project_ref).first()
    if project is None or not can_view(request, project):
        return fail("项目不存在或无权访问", 404)

    if not can_manage_members(request, project):
        return fail("只有项目所有者能管理协作者", 403, code="forbidden")

    name = (username or "").strip()[:USERNAME_MAX]
    target = User.objects.filter(username=name).first()
    if target is None:
        return fail("没有这个用户", 404, code="user_not_found")
    if target.pk == project.owner_id:
        return fail("不能移除项目所有者", 400, code="owner_not_allowed")

    deleted, _ = Collaborator.objects.filter(project=project, user=target).delete()
    if deleted:
        _audit(request, "collaborator.remove", project, name)

    return ok({"removed": bool(deleted), "username": name})


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------

def _audit(request: HttpRequest, action: str, project: Project, username: str) -> None:
    """★★ **加人 / 移除必须留痕**（* `B206`⑤）⚠

    ★★ 表里没有 created_at / invited_by ⇒* 审计是"谁邀的、何时进的"
      **唯一**出处（* 同 `settings_table.set_value()` 的口径）✅
    """
    actor = current_user(request)
    AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        target_kind="Project",
        target_id=project.project_ref,
        detail={"username": username, "project": project.name},
    )
