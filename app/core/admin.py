"""★★ **管理后台**（django-unfold · 2026-10-24）⚠

## ★★★ 所有者原话（逐字）

> 「不要自建，自建不知道有什么bug。用现成的，经过时间检验的比较好。」
> 「要选择开源，免费使用的就行，而且不要有传染性……其他的你按效果好，占用资源别太多权衡就行。」

## ★ 为什么是 django-unfold

```
MIT 许可（⛔ 无 copyleft）· Django 5.1 官方支持 · 模板覆盖 admin ⇒ 不用重写任何页面
```

## ★ 注册口径

```\n内容  Note / NoteComment / Project\n用户  User / UserProfile / Invite / Collaborator / ApiToken\n系统  AuditLog（只读）/ AppSetting / ProjectStorage\n```

⚠ `AuditLog` **只读**：审计日志是「最大权力唯一的约束」，⛔ 后台里不许改 ⚠
"""
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin

from core.models import (
    ApiToken,
    AppSetting,
    AuditLog,
    Collaborator,
    Invite,
    Note,
    NoteComment,
    Project,
    ProjectStorage,
    UserProfile,
)


# ---------------------------------------------------------------- 用户 / 权限

# ⚠ `django.contrib.auth.admin` **已经注册过** User / Group
#   ⇒ 想换成本项目这版（unfold 样式 + 自定义列）必须**先注销** ⚠
for _model in (User, Group):
    try:
        admin.site.unregister(_model)
    except admin.sites.NotRegistered:  # pragma: no cover
        pass


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    list_display = ("username", "email", "is_staff", "is_superuser", "is_active", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email")
    ordering = ("-date_joined",)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):
    list_display = ("user", "display_name", "tier", "paid_slots", "created_at")
    list_filter = ("tier",)
    search_fields = ("user__username", "display_name")
    autocomplete_fields = ("user",)


@admin.register(Invite)
class InviteAdmin(ModelAdmin):
    list_display = ("token", "created_by_name", "used_count", "max_uses", "expires_at", "revoked_at")
    search_fields = ("token", "created_by_name")
    readonly_fields = ("token",)


@admin.register(Collaborator)
class CollaboratorAdmin(ModelAdmin):
    list_display = ("project", "user")
    search_fields = ("project__name", "user__username")
    autocomplete_fields = ("project", "user")


@admin.register(ApiToken)
class ApiTokenAdmin(ModelAdmin):
    list_display = ("user", "prefix", "provider", "expires_at", "revoked_at", "last_used_at")
    search_fields = ("user__username", "prefix")
    readonly_fields = ("token_hash",)


# ---------------------------------------------------------------- 内容


@admin.register(Project)
class ProjectAdmin(ModelAdmin):
    list_display = (
        "name",
        "project_ref",
        "owner",
        "provider",
        "is_public",
        "state",
        "node_count",
        "edge_count",
        "created_at",
    )
    list_filter = ("is_public", "state", "provider")
    search_fields = ("name", "project_ref", "owner__username", "repo_url")
    readonly_fields = ("project_ref", "node_count", "edge_count", "repo_url", "provider")
    autocomplete_fields = ("owner",)


@admin.register(Note)
class NoteAdmin(ModelAdmin):
    list_display = ("ref", "title", "created_by", "kind", "is_public", "state", "created_at")
    list_filter = ("kind", "is_public", "state")
    search_fields = ("title", "ref", "created_by__username", "project_name")
    readonly_fields = ("ref",)
    autocomplete_fields = ("created_by",)


@admin.register(NoteComment)
class NoteCommentAdmin(ModelAdmin):
    list_display = ("id", "note", "kind", "is_paragraph", "created_by", "state", "created_at")
    list_filter = ("kind", "is_paragraph", "state")
    search_fields = ("body", "created_by__username")
    autocomplete_fields = ("note", "created_by")


# ---------------------------------------------------------------- 系统


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    """★ 审计日志 **只读**（* 可追责是管理员唯一约束）⚠"""

    list_display = ("created_at", "actor", "action", "target_kind", "target_id", "ip")
    list_filter = ("target_kind", "action")
    search_fields = ("actor__username", "action", "target_id")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AppSetting)
class AppSettingAdmin(ModelAdmin):
    list_display = ("key", "updated_by", "updated_at")
    search_fields = ("key",)


@admin.register(ProjectStorage)
class ProjectStorageAdmin(ModelAdmin):
    list_display = ("project_ref", "owner", "bytes_used", "files_used", "measured_at")
    search_fields = ("project_ref",)
