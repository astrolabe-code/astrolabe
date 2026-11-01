"""★★ 后台：**作业队列**（2026-10-25）⚠

## ★ 为什么必须有这一页

```\n没有它之前：解析失败了，后台**看不到任何痕迹**\n           ⇒ 只能 `docker compose logs` 或直接查库 ⚠\n```\n

★ 所有者追问「后台写完了吗？还有没有没做的？」时，这是盘点出来的**第一号洞** ✅

## ★ 口径

⚠ **全只读** —— 作业由 worker 自己推进，后台改它只会把状态机搞乱 ⚠
  （真要重跑，走「项目 → 重新解析」，那是业务动作，不是改库）
"""

from __future__ import annotations

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from jobs.models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """作业列表 —— 只读，按状态 / 类型筛，点进去看失败原因 ⚠"""

    list_display = (
        "job_id",
        "project_link",
        "kind_label",
        "state_tag",
        "progress_label",
        "took",
        "attempts_label",
        "queued_label",
    )
    list_display_links = ("job_id",)
    # ⚠ 允许删除（* 否则要上 SSH 手工清）—— 执行中的除外，见 `has_delete_permission` ⚠
    actions_on_top = True
    list_filter = ("state", "kind", "error_code")
    search_fields = ("project_ref", "project__name", "error_msg", "worker_id")
    # ★ 搜索框提示用中文（⛔ 否则是 unfold 的 "Type to search"）⚠
    search_help_text = "输入项目名 / 项目编号 / 错误信息搜索"
    ordering = ("-queued_at",)
    list_per_page = 20
    date_hierarchy = "queued_at"

    fieldsets = (
        ("基本信息", {"fields": ("project", "project_ref", "kind", "state", "dedup_key", "priority")}),
        ("进度", {"fields": ("progress", "stage", "eta_s", "attempts")}),
        ("失败原因", {"fields": ("error_code", "error_msg")}),
        ("时间", {"fields": ("queued_at", "started_at", "finished_at")}),
        ("执行者", {"fields": ("worker_id", "payload")}),
    )
    readonly_fields = [f.name for f in Job._meta.fields]

    # ---- 全只读 ----------------------------------------------------------
    # ⚠ `has_change_permission=False` 会**连带禁掉详情页**（Django 2.1 起
    #   `has_view_permission` 默认跟随它）⇒ 必须**显式放行查看** ✅
    def has_view_permission(self, request, obj=None):
        return True

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        """★★ 允许删，但 **执行中的作业不给删**（2026-10-25）⚠

        > 所有者：「**job 有问题，我能在这个后台管理里直接清除有问题的这条最好，
        >   否则发现 job 出问题了，我还要手工去 ssh 上删除**」

        ⚠ 执行中的那条正被 worker 拿着，删了它会「回写一个不存在的作业」⇒ 报错 ⚠
        ⇒ 别的状态（排队中 / 已完成 / 失败 / 已取消）都可以删 ✅
        """
        if obj is not None and obj.state == Job.STATE_RUNNING:
            return False
        return True

    # ★★ 用自己的删除动作替换默认的 `delete_selected`（2026-10-25）⚠
    #   · · 原因：Django 自带的批量删除会先逐条问 `has_delete_permission`，
    #     只要有一条「执行中」就 **整体 403**（不是跳过），完全达不到"清掉坏的"的目的 ⚠
    #   · · 所以自己写一个：**跳过执行中**，其余照删，并说清楚跳了几条 ✅
    actions = ("delete_safely", "retry_selected")

    def get_actions(self, request):
        """★ 去掉 Django 全局的 `delete_selected` ⚠

        ⚠ Django 5.1 的 `_get_base_actions()` 会把 `admin_site.actions` **无条件合并**进来
          ⇒ 光写 `actions = (...)` **删不掉**它（实测下拉里两个都在）⚠
        ⚠ 而默认那个只要选中里有一条「执行中」就**整体 403**，达不到"清掉坏的"的目的 ⚠
        """
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="重新投递所选作业（仅失败/取消，且项目还没出图）")
    def retry_selected(self, request, queryset):
        """★★ **重跑**（2026-10-25）⚠

        > 所有者：「1，2，3 全部加上」（② 指作业删了不能重跑这件事）

        ## ⚠★ 这里有一条**不能越过的红线**

        ```\n        原话：「代码解析完成之后【应该不允许重新解析】」
        原因：解释 / 提问挂在「文件 + 行区间」上 ——
              重新解析会让所有已存在的批注**错位** ⚠
        ```\n
        ⇒ 只有**项目还没有图**时才允许重投（失败 / 取消的作业正好符合这个前提）；
          ⛔ 已经有图的一律拒绝，并说明原因 ✅
        """
        from graph import scope
        from jobs import dispatch

        retried, skipped_state, skipped_graph, failed = 0, 0, 0, []

        for job in queryset:
            if job.state not in (Job.STATE_FAILED, Job.STATE_CANCELED):
                skipped_state += 1
                continue
            # ⚠★ 必须用 `project_ref` 而不是 `project_id`：
            #   `dispatch.submit()` 建作业时**只填 project_ref**，
            #   `project` 外键在真实数据里**全是 NULL**（踩过：拿 project_id 判断会全被拒）⚠
            ref = job.project_ref
            if not ref:
                failed.append(f"#{job.pk}（没有项目标识）")
                continue
            # ⚠ 红线：已经有图 ⇒ 绝不能重解析（会让解释/提问的行号错位）⚠
            if scope.nodes_of(ref).exists():
                skipped_graph += 1
                continue
            try:
                dispatch.submit(
                    kind=job.kind,
                    project_ref=ref,
                    payload=job.payload or {},
                    priority=job.priority,
                    dedup_key=job.dedup_key,
                    # ★ 管理员重投**绕开队列公平闸门**（他在救场，⛔ 不该被"你排得太多"挡住）
                    skip_limits=True,
                )
                retried += 1
            except Exception as exc:  # noqa: BLE001
                failed.append(f"#{job.pk}（{exc}）")

        parts = [f"已重新投递 {retried} 条"]
        if skipped_state:
            parts.append(f"跳过 {skipped_state} 条非失败/取消")
        if skipped_graph:
            parts.append(f"跳过 {skipped_graph} 条已在项目里出过图（不允许重新解析）")
        if failed:
            parts.append("失败：" + "、".join(failed[:3]))

        self.message_user(
            request,
            "；".join(parts),
            level="warning" if (skipped_graph or failed) else "success",
        )

    @admin.action(description="删除所选作业（自动跳过执行中的）")
    def delete_safely(self, request, queryset):
        running = queryset.filter(state=Job.STATE_RUNNING)
        n_running = running.count()
        target = queryset.exclude(state=Job.STATE_RUNNING)
        n = target.count()
        target.delete()

        if n and n_running:
            msg = f"已删除 {n} 条作业；跳过 {n_running} 条「执行中」的（它们正被 worker 处理，删了会出错）"
        elif n:
            msg = f"已删除 {n} 条作业"
        elif n_running:
            msg = f"没有删除任何作业 —— 选中的 {n_running} 条都在执行中"
        else:
            msg = "没有选中任何作业"
        self.message_user(request, msg, level="warning" if n_running else "success")

    # ---- 列 ---------------------------------------------------------------
    @admin.display(description="编号", ordering="id")
    def job_id(self, obj):
        return obj.pk

    @admin.display(description="项目")
    def project_link(self, obj):
        return obj.project.name if obj.project_id else (obj.project_ref or "—")

    @admin.display(description="状态")
    def state_tag(self, obj):
        colors = {
            Job.STATE_QUEUED: "#6b7280",
            Job.STATE_RUNNING: "#0891b2",
            Job.STATE_DONE: "#15803d",
            Job.STATE_FAILED: "#dc2626",
            Job.STATE_CANCELED: "#9ca3af",
        }
        color = colors.get(obj.state, "#111")
        label = obj.get_state_display() if hasattr(obj, "get_state_display") else obj.state
        return format_html('<span style="color:{};font-weight:600">{}</span>', color, label)

    @admin.display(description="类型")
    def kind_label(self, obj):
        return obj.get_kind_display() if hasattr(obj, "get_kind_display") else obj.kind

    @admin.display(description="进度", ordering="progress")
    def progress_label(self, obj):
        return f"{obj.progress}%"

    @admin.display(description="重试", ordering="attempts")
    def attempts_label(self, obj):
        return obj.attempts

    @admin.display(description="入队时间", ordering="queued_at")
    def queued_label(self, obj):
        return timezone.localtime(obj.queued_at).strftime("%Y-%m-%d %H:%M")

    @admin.display(description="耗时")
    def took(self, obj):
        if not obj.started_at:
            return "—"
        end = obj.finished_at or timezone.now()
        seconds = (end - obj.started_at).total_seconds()
        return f"{seconds:.0f} 秒" if seconds < 120 else f"{seconds / 60:.1f} 分"
