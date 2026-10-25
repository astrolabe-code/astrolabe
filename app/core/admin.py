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

from core.admin_moderation import (
    disable_users,
    enable_users,
    grant_staff,
    revoke_staff,
    sync_comment_counts,
    hide_comments,
    hide_notes,
    hide_projects,
    restore_comments,
    restore_notes,
    restore_projects,
)
from core.admin_ops import register_ops_url
from core.models import (
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


class PagedAdmin(ModelAdmin):
    """★★ 后台列表**默认每页 20 条**（2026-10-24）⚠

    所有者：「要有翻页按钮呀，不然列表一长，要下滑很久才能看到滑块」
    · · Django 默认 100 条一页 ⇒ 68 个邀请码全挤一页，滑不到底的横向滑块 ⚠
    · · 顺带打开「总计 N 条」，翻页时知道自己在哪一段 ✅
    """

    list_per_page = 20
    show_full_result_count = True


@admin.register(User)
class UserAdmin(BaseUserAdmin, PagedAdmin):
    # ★★ 用户状态动作（2026-10-24 · 所有者：「要有可以更改用户状态的，比如禁止登陆」）⚠
    actions = (disable_users, enable_users, grant_staff, revoke_staff)
    list_display = ("username", "email", "is_staff", "is_superuser", "is_active", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active")

    # ★★★ 表单也不能把**最后一个超级管理员**降级 / 停用（2026-10-24）⚠
    #   · · 三条批量动作已挡住，但「编辑用户」表单是另一条路 —— 必须一起堵 ⚠
    #   · · 否则取消他的 is_active / is_staff ⇒ 后台再没人能进 ✅
    def save_model(self, request, obj, form, change):
        from django.contrib import messages
        from django.contrib.auth import get_user_model

        if change and obj.pk:
            User = get_user_model()
            before = User.objects.filter(pk=obj.pk).first()
            if before is not None and before.is_superuser:
                loses = not (obj.is_active and obj.is_staff and obj.is_superuser)
                others = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=obj.pk)
                if loses and not others.exists():
                    obj.is_active = True
                    obj.is_staff = True
                    obj.is_superuser = True
                    messages.error(
                        request,
                        "不能停用或降级最后一个超级管理员（否则后台再也没人能进）—— 改动已撤销",
                    )
        super().save_model(request, obj, form, change)
    search_fields = ("username", "email")
    ordering = ("-date_joined",)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


@admin.register(UserProfile)
class UserProfileAdmin(PagedAdmin):
    list_display = ("user", "display_name", "tier", "paid_slots", "created_at")
    list_filter = ("tier",)
    search_fields = ("user__username", "display_name")
    autocomplete_fields = ("user",)


@admin.register(Invite)
class InviteAdmin(PagedAdmin):
    """★★ 邀请码（2026-10-24 补齐：创建 / 撤销 / 删除 / 看谁用过）⚠

    ```\n    创建：点「添加」→ 只填次数与备注 ⇒ token **自动生成**（64 字符随机）
    禁用：勾选 → 动作「撤销所选」⇒ 立刻不可用（可恢复）
    删除：勾选 → 删除（* 用过的记录仍在审计日志里，查得到）
    谁用过：打开某个邀请码 ⇒「已注册用户」一栏（* 来自 invite.redeem 审计）
    ```\n
    """

    list_display = (
        "token",
        "status_text",
        "created_by_name",
        "used_count",
        "max_uses",
        "expires_at",
        "created_at",
    )
    list_filter = ("revoked_at",)
    search_fields = ("token", "created_by_name", "note")

    def get_readonly_fields(self, request, obj=None):
        # ⚠ token **永远只读**：新增时由 `save_model` 生成，修改时不让改 ⚠
        #   · · 若在新增表单里留着它 ⇒ 必填校验不过 ⇒ 建不出来（踩过）⚠
        if obj is None:
            return ()
        return ("token", "created_by_name", "used_count", "revoked_at", "status_detail", "used_users")

    def get_fields(self, request, obj=None):
        # ★ 新增：只让填三样（* 其余系统接管）⚠
        if obj is None:
            return ("max_uses", "expires_at", "note")
        return (
            "token",
            "created_by_name",
            "max_uses",
            "used_count",
            "expires_at",
            "revoked_at",
            "note",
            "status_detail",
            "used_users",
        )

    def save_model(self, request, obj, form, change):
        if not obj.token:
            from core.invites import new_token

            obj.token = new_token()
        if not obj.created_by_id:
            obj.created_by = request.user
        if not obj.created_by_name:
            obj.created_by_name = request.user.get_username()
        super().save_model(request, obj, form, change)

    # ★★ 列表里**只放短标签**（2026-10-24）⚠
    #   · · 原来直接把「邀请链接已于 2026-10-14 04:25 过期，请联系…」整句塞进列里
    #     ⇒ 49 行长句把表格撑爆，列宽全乱（* 所有者：「被挤成一条了，太怪了吧」）⚠
    #   · · 完整句子放详情页「不可用原因」⇒ 想看细的再点进去 ✅
    @admin.display(description="状态")
    def status_text(self, obj):
        from django.utils import timezone

        now = timezone.now()
        if obj.revoked_at:
            return "已撤销"
        if obj.used_count >= obj.max_uses:
            return "已用尽"
        if obj.expires_at and obj.expires_at <= now:
            return "已过期"
        return "可用"

    @admin.display(description="不可用原因")
    def status_detail(self, obj):
        """★ 完整句子（* 只在详情页出现，不撑列表）⚠"""
        from django.utils import timezone

        now = timezone.now()
        if obj.is_usable(now):
            return "（当前可用）"
        return obj.reject_reason(now) or ""

    @admin.display(description="已注册用户")
    def used_users(self, obj):
        """★ 谁用这个码注册的（* 来自 `invite.redeem` 审计日志）⚠"""
        from django.urls import reverse
        from django.utils.html import format_html

        from core.models import AuditLog

        rows = (
            AuditLog.objects.filter(
                action="invite.redeem", target_kind="Invite", target_id=str(obj.pk)
            )
            .select_related("actor")
            .order_by("created_at")
        )
        if not rows:
            return "（还没有人用这个码注册）"
        items = []
        for row in rows:
            when = row.created_at.strftime("%Y-%m-%d %H:%M")
            if row.actor_id:
                url = reverse("admin:auth_user_change", args=[row.actor_id])
                items.append(
                    format_html('{}（{}）', format_html('<a href="{}">{}</a>', url, row.actor.username), when)
                )
            else:
                items.append(format_html("（账号已删除）{}", when))
        return format_html("、<br>".join(str(i) for i in items))

    # ---- 批量：撤销 / 恢复 ----
    actions = ("revoke_selected", "unrevoke_selected")

    @admin.action(description="撤销所选（立刻不可用）")
    def revoke_selected(self, request, queryset):
        from django.utils import timezone

        n = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f"已撤销 {n} 个邀请码")

    @admin.action(description="恢复所选（重新可用）")
    def unrevoke_selected(self, request, queryset):
        n = queryset.filter(revoked_at__isnull=False).update(revoked_at=None)
        self.message_user(request, f"已恢复 {n} 个邀请码")


@admin.register(Collaborator)
class CollaboratorAdmin(PagedAdmin):
    """★ 项目协作者（2026-10-24：**不进任何菜单**）⚠

    所有者：「出来满足一下我对哪些项目邀请了那些协作者的好奇心，完全没用呀。」
    · · 日常管理在前台「项目设置 → 协作者」
    · · 这里只留作排查用（* 直接访问 /admin/core/collaborator/ 仍可用）⚠
    """

    list_display = ("project", "user")
    search_fields = ("project__name", "user__username")
    autocomplete_fields = ("project", "user")

    def get_model_perms(self, request):
        # ⚠ 返回空 ⇒ 不出现在侧栏 / 应用索引；⛔ 但 URL 依然有效 ✅
        return {}


# ---------------------------------------------------------------- 内容


@admin.register(Project)
class ProjectAdmin(PagedAdmin):
    actions = (hide_projects, restore_projects)
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

    # ★★ 后台删除项目必须走 `purge_project()`（2026-10-24）⚠
    #   · · Django 默认只级联删行：**不释放存储、不写审计、不动作业** ⚠
    def delete_model(self, request, obj):
        from web.views.projects import purge_project

        purge_project(obj.project_ref, by=request.user)
        self.message_user(request, f"已彻底删除项目 {obj.name}")

    def delete_queryset(self, request, queryset):
        from web.views.projects import purge_project

        for project in queryset:
            purge_project(project.project_ref, by=request.user)
        self.message_user(request, f"已彻底删除 {queryset.count()} 个项目")


@admin.register(Note)
class NoteAdmin(PagedAdmin):
    # ★ 隐藏 / 恢复（* Django 默认只有删除，所有者指出缺隐藏）⚠
    actions = (hide_notes, restore_notes)
    list_display = ("ref", "title", "created_by", "kind", "is_public", "state", "created_at")
    list_filter = ("kind", "is_public", "state")
    search_fields = ("title", "ref", "created_by__username", "project_name")
    readonly_fields = ("ref",)
    autocomplete_fields = ("created_by",)

    # ★★★ 后台「删除」= **物理删除**（2026-10-24 · 所有者裁定）⚠
    #   · · 原话：「管理员删除就是物理删除，不要软删，所以，我才设置了隐藏这个级别」
    #   · · ⇒ 两个级别各司其职：**隐藏**保留数据（仅作者可见）；**删除**彻底没了 ✅
    #   · · 用户侧的"回收站"是用户自己的操作，与管理员无关 ⚠
    def get_queryset(self, request):
        # ★ 用户删进回收站的不在后台列表里出现（* 他们自己能恢复）⚠
        return super().get_queryset(request).filter(deleted_at__isnull=True)

    def delete_model(self, request, obj):
        pk = obj.pk
        super().delete_model(request, obj)
        # ⚠ 物理删除**不会**触发索引清理（`Note.save` 才有钩子）
        #   ⇒ 主动入队：消费者发现笔记已不存在就删索引文档 ⚠
        self._reindex_deleted([pk])

    def delete_queryset(self, request, queryset):
        pks = list(queryset.values_list("pk", flat=True))
        super().delete_queryset(request, queryset)
        self._reindex_deleted(pks)

    @staticmethod
    def _reindex_deleted(pks):
        try:
            from search import sync

            sync.enqueue_many(pks)
        except Exception:  # pragma: no cover - 索引只是收敛，不影响删除
            pass


@admin.register(NoteComment)
class NoteCommentAdmin(PagedAdmin):
    actions = (hide_comments, restore_comments)
    list_display = ("id", "note", "kind", "is_paragraph", "created_by", "state", "created_at")
    list_filter = ("kind", "is_paragraph", "state")
    search_fields = ("body", "created_by__username")
    autocomplete_fields = ("note", "created_by")

    # ★ 后台删除评论 = **物理删除**（* 与笔记同一口径，管理员删除不留数据）⚠
    def get_queryset(self, request):
        return super().get_queryset(request).filter(deleted_at__isnull=True)

    # ⚠ 物理删除绕过应用层的"减计数" ⇒ 删完重算，* 否则 comment_count 虚高 ⚠
    def delete_model(self, request, obj):
        note_id = obj.note_id
        super().delete_model(request, obj)
        sync_comment_counts([note_id])

    def delete_queryset(self, request, queryset):
        note_ids = list(queryset.values_list("note_id", flat=True))
        super().delete_queryset(request, queryset)
        sync_comment_counts(note_ids)


# ---------------------------------------------------------------- 系统


@admin.register(AuditLog)
class AuditLogAdmin(PagedAdmin):
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
class AppSettingAdmin(PagedAdmin):
    list_display = ("key", "updated_by", "updated_at")
    search_fields = ("key",)


@admin.register(ProjectStorage)
class ProjectStorageAdmin(PagedAdmin):
    list_display = ("project_ref", "owner", "bytes_used", "files_used", "measured_at")
    search_fields = ("project_ref",)


# ★★ 把「运维概览」挂进后台（`/admin/ops/` · 2026-10-24）⚠
register_ops_url()
