"""★★ **后台的「隐藏 / 恢复」批量动作**（2026-10-24）⚠

## ★ 所有者原话（逐字）

> 「笔记，项目，评论怎么只有删除选项，没有隐藏选项？」

## ★ 为什么后台原来只有删除

Django admin 默认只给一个 `delete_selected`。而本项目对"隐藏"有自己的口径
（`B208`）：`state=hidden` + **理由必填** + 写审计，⛔ 不是物理删除。

所以这里把 `web/views/moderate.py` 的口径**原样搬过来**：

```\n隐藏：state=hidden + moderation_reason + moderated_by/at + AuditLog\n项目隐藏：额外**单向下沉**把该项目下的笔记也置为 hidden（* 恢复不回滚）\n恢复：state=active（* 理由可空）\n```

⚠ 与接口不同的是：这里是**批量**操作，且动作入口只在后台（`/admin/`）⚠
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse
from django.utils import timezone
from django.contrib import admin as dj_admin



def sync_comment_counts(note_ids) -> None:
    """★★ **按库重算评论数**（2026-10-24）⚠

    ```\n  后台隐藏 / 恢复 / 删除评论都不走应用层那条"改计数"的路径
  ⇒ 若不管，`Note.comment_count` 会虚高（* 实测：删完显示 1、实际 0）⚠
  ```\n
    ⚠ 用**重算**而不是加减：幂等，重复执行不会越算越偏 ✅
    """
    from core.models import Note, NoteComment
    from search import sync as search_sync

    ids = {int(i) for i in note_ids if i}
    if not ids:
        return
    for nid in ids:
        # ★ 口径：未删除 且 未隐藏 的评论才算数 ⚠
        count = (
            NoteComment.objects.filter(note_id=nid, deleted_at__isnull=True)
            .exclude(state="hidden")
            .count()
        )
        Note.objects.filter(pk=nid).update(comment_count=count)
    # ★ 计数变了 ⇒ 让索引只更新计数（* 不重写正文）⚠
    try:
        search_sync.enqueue_many(list(ids), counts_only=True)
    except Exception:  # pragma: no cover
        pass


def _confirm(request, queryset, *, title: str, action_name: str, intro: str):
    """★ 理由填写页（* 必须先填理由，才允许隐藏）⚠"""
    return TemplateResponse(
        request,
        "admin/moderate_confirm.html",
        {
            **dj_admin.site.each_context(request),
            "title": title,
            "intro": intro,
            "queryset": queryset,
            "action_name": action_name,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        },
    )


def _audit(user, action: str, *, kind: str, target: str, name: str, reason: str) -> None:
    """★ 管理动作必留痕（`U2.5` 纪律 1）⚠"""
    from core.models import AuditLog

    AuditLog.objects.create(
        actor=user,
        action=action,
        target_kind=kind,
        target_id=str(target),
        detail={"name": name, "reason": reason},
    )


def _set_state(obj, hidden: bool, reason: str, user) -> None:
    """★ 笔记 / 项目共用的四列（* 与 `moderate.py` 完全一致）⚠"""
    obj.state = "hidden" if hidden else "active"
    fields = ["state"]
    if hasattr(obj, "moderation_reason"):
        obj.moderation_reason = reason
        obj.moderated_by = user
        obj.moderated_at = timezone.now()
        fields += ["moderation_reason", "moderated_by", "moderated_at"]
    obj.save(update_fields=fields)


# ----------------------------------------------------------------- 笔记


def hide_notes(modeladmin, request, queryset):
    if request.POST.get("confirmed") != "1":
        return _confirm(
            request,
            queryset,
            title="隐藏所选笔记",
            action_name="hide_notes",
            intro=f"将隐藏 {queryset.count()} 篇笔记：只有作者本人还能看到，别人直接访问链接也不可见。",
        )
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "隐藏必须填写理由（作者会问为什么）")
        return _confirm(
            request, queryset, title="隐藏所选笔记", action_name="hide_notes",
            intro=f"将隐藏 {queryset.count()} 篇笔记。",
        )
    for note in queryset:
        _set_state(note, True, reason, request.user)
        _audit(request.user, "note.hide", kind="note", target=note.pk,
               name=note.title or "", reason=reason)
    messages.success(request, f"已隐藏 {queryset.count()} 篇笔记")


hide_notes.short_description = "隐藏所选（仅作者可见）"
hide_notes.allowed_permissions = ("change",)


def restore_notes(modeladmin, request, queryset):
    for note in queryset:
        _set_state(note, False, "", request.user)
        _audit(request.user, "note.restore", kind="note", target=note.pk,
               name=note.title or "", reason="")
    messages.success(request, f"已恢复 {queryset.count()} 篇笔记")


restore_notes.short_description = "恢复所选（取消隐藏）"
restore_notes.allowed_permissions = ("change",)


# ----------------------------------------------------------------- 项目


def hide_projects(modeladmin, request, queryset):
    if request.POST.get("confirmed") != "1":
        return _confirm(
            request,
            queryset,
            title="隐藏所选项目",
            action_name="hide_projects",
            intro=f"将隐藏 {queryset.count()} 个项目，并**级联隐藏**其下所有笔记（恢复时不会自动回滚）。",
        )
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "隐藏必须填写理由")
        return _confirm(
            request, queryset, title="隐藏所选项目", action_name="hide_projects",
            intro=f"将隐藏 {queryset.count()} 个项目。",
        )

    from web.views.projects import _cascade_hidden

    for project in queryset:
        _set_state(project, True, reason, request.user)
        cascaded = _cascade_hidden(project)
        _audit(request.user, "project.hide", kind="project", target=project.project_ref,
               name=project.name or "", reason=f"{reason}（级联隐藏 {cascaded} 篇笔记）")
    messages.success(request, f"已隐藏 {queryset.count()} 个项目（含其下笔记）")


hide_projects.short_description = "隐藏所选（含其下笔记）"
hide_projects.allowed_permissions = ("change",)


def restore_projects(modeladmin, request, queryset):
    for project in queryset:
        _set_state(project, False, "", request.user)
        _audit(request.user, "project.restore", kind="project", target=project.project_ref,
               name=project.name or "", reason="")
    messages.success(request, f"已恢复 {queryset.count()} 个项目")


restore_projects.short_description = "恢复所选（取消隐藏）"
restore_projects.allowed_permissions = ("change",)


# ----------------------------------------------------------------- 评论


def hide_comments(modeladmin, request, queryset):
    if request.POST.get("confirmed") != "1":
        return _confirm(
            request,
            queryset,
            title="隐藏所选评论",
            action_name="hide_comments",
            intro=f"将隐藏 {queryset.count()} 条评论：列表里不再出现（数据保留）。",
        )
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "隐藏必须填写理由")
        return _confirm(
            request, queryset, title="隐藏所选评论", action_name="hide_comments",
            intro=f"将隐藏 {queryset.count()} 条评论。",
        )
    note_ids = list(queryset.values_list("note_id", flat=True))
    for comment in queryset:
        comment.state = "hidden"
        comment.save(update_fields=["state"])
        _audit(request.user, "comment.hide", kind="comment", target=comment.pk,
               name=(comment.body or "")[:40], reason=reason)
    sync_comment_counts(note_ids)
    messages.success(request, f"已隐藏 {queryset.count()} 条评论")


hide_comments.short_description = "隐藏所选评论"
hide_comments.allowed_permissions = ("change",)


def restore_comments(modeladmin, request, queryset):
    note_ids = list(queryset.values_list("note_id", flat=True))
    for comment in queryset:
        comment.state = "normal"
        comment.save(update_fields=["state"])
        _audit(request.user, "comment.restore", kind="comment", target=comment.pk,
               name=(comment.body or "")[:40], reason="")
    sync_comment_counts(note_ids)
    messages.success(request, f"已恢复 {queryset.count()} 条评论")


restore_comments.short_description = "恢复所选评论"
restore_comments.allowed_permissions = ("change",)


# ----------------------------------------------------------------- 用户状态


def _last_superuser(user) -> bool:
    """★ 他是不是**最后一个可用的超级管理员**（* 动了他 = 后台可能再也没人能进）⚠"""
    from django.contrib.auth import get_user_model

    if not (user.is_superuser and user.is_active):
        return False
    return not (
        get_user_model()
        .objects.filter(is_superuser=True, is_active=True)
        .exclude(pk=user.pk)
        .exists()
    )


def _higher_than_actor(request, target) -> bool:
    """★★ 目标是不是**同权或更高权**（2026-10-24）⚠

    ```\n    · · staff 只能处置**普通用户** —— ⛔ 不能碰别的 staff / superuser
    · · 否则 A 管理员可以把 B 管理员踢掉（* 所有者：「这不对吧？」）⚠
    ```\n
    """
    actor = request.user
    if target.pk == actor.pk:
        return True  # ⚠ 自己一律当"高权"，走"跳过自己"的分支 ⚠
    if target.is_superuser:
        return not actor.is_superuser
    if target.is_staff:
        return not actor.is_superuser
    return False


def _revoke_sessions(users) -> int:
    """★★ **删掉这些用户的所有会话**（B245 / B247①）⚠

    ```
    session 制下，只把 is_active 置 False **不会**让已登录的人掉线
    —— Django 的 session 不过期就认它（与 is_active 无关）⚠
    ⇒ 「禁止登录」必须连带删会话，否则名存实亡 ⚠
    ```

    ★ 与旧实现的差别：旧的是撤销 ApiToken（令牌制），现在是删 Session ✅
    """
    from web.auth import logout_all_sessions

    total = 0
    for user in users:
        total += logout_all_sessions(user)
    return total


def disable_users(modeladmin, request, queryset):
    """★★ **禁止登录**（2026-10-24）⚠

    ```\n    is_active=False ⇒ 登录接口直接拒（Django 认证层）
    + 撤销全部令牌  ⇒ **已经登录的会话当场失效**（否则禁用只是"下次再说"）⚠
    ```\n
    ⚠ 不能禁自己（* 唯一的管理员一禁，后台就没人能进了）⚠
    """
    # ★★ 三层保护（2026-10-24）⚠
    #   ① 不能禁自己
    #   ② staff 只能禁**普通用户**（⛔ 不能禁别的 staff / superuser）
    #   ③ 不能禁**最后一个可用的超级管理员**（* 否则后台再也没人能进）⚠
    targets = queryset.exclude(pk=request.user.pk)
    blocked = [u for u in targets if _higher_than_actor(request, u) or _last_superuser(u)]
    if blocked:
        names = "、".join(u.username for u in blocked[:5])
        messages.warning(
            request,
            f"已跳过 {len(blocked)} 个账号（{names}）："
            "不能禁用自己 / 同权或更高权账号 / 最后一个超级管理员",
        )
        targets = targets.exclude(pk__in=[u.pk for u in blocked])
    if not targets.exists():
        messages.error(request, "没有可操作的对象（都被保护规则挡住了）")
        return
    n = targets.update(is_active=False)
    revoked = _revoke_sessions(targets)
    messages.success(request, f"已禁止 {n} 个账号登录，清除 {revoked} 个会话")
    for user in targets:
        _audit(request.user, "user.disable", kind="user", target=user.pk,
               name=user.username, reason="后台禁止登录")


disable_users.short_description = "禁止登录（立即失效）"
disable_users.allowed_permissions = ("change",)


def enable_users(modeladmin, request, queryset):
    n = queryset.update(is_active=True)
    messages.success(request, f"已恢复 {n} 个账号的登录权限")
    for user in queryset:
        _audit(request.user, "user.enable", kind="user", target=user.pk,
               name=user.username, reason="后台恢复登录")


enable_users.short_description = "恢复登录"
enable_users.allowed_permissions = ("change",)


def grant_staff(modeladmin, request, queryset):
    # ⚠ 只有超级管理员能授权（* 否则 staff 可以给自己人开后门）⚠
    if not request.user.is_superuser:
        messages.error(request, "只有超级管理员能授予后台权限")
        return
    n = queryset.update(is_staff=True)
    messages.success(request, f"已授予 {n} 个账号后台权限")
    for user in queryset:
        _audit(request.user, "user.grant_staff", kind="user", target=user.pk,
               name=user.username, reason="")


grant_staff.short_description = "授予后台权限（staff）"
grant_staff.allowed_permissions = ("change",)


def revoke_staff(modeladmin, request, queryset):
    # ⚠ 只有超级管理员能收权（* 否则 staff 之间可以互相踢，属于提权）⚠
    if not request.user.is_superuser:
        messages.error(request, "只有超级管理员能取消别人的后台权限")
        return
    targets = queryset.exclude(pk=request.user.pk)
    blocked = [u for u in targets if _last_superuser(u)]
    if blocked:
        names = "、".join(u.username for u in blocked[:5])
        messages.warning(request, f"已跳过 {names}：不能取消最后一个超级管理员")
        targets = targets.exclude(pk__in=[u.pk for u in blocked])
    if not targets.exists():
        messages.error(request, "没有可操作的对象（都被保护规则挡住了）")
        return
    n = targets.update(is_staff=False, is_superuser=False)
    messages.success(request, f"已取消 {n} 个账号的后台权限")
    for user in targets:
        _audit(request.user, "user.revoke_staff", kind="user", target=user.pk,
               name=user.username, reason="")


revoke_staff.short_description = "取消后台权限"
revoke_staff.allowed_permissions = ("change",)
