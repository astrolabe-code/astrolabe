"""★★ **后台里的「运维概览」页**（2026-10-24）⚠

## ★ 所有者原话（逐字）

> 「Astrolabe 后台可以看到kuma 的信息吗？还是我每次都要打开这两个页面」

## ★ 做法

```\n不用 iframe：Kuma 有 `X-Frame-Options: SAMEORIGIN`，跨端口嵌会被浏览器拦死 ⚠\n改为**后端直读**（Kuma 的 sqlite 只读挂载）＋ 本地探活，**一页看完** ✅\n```

⚠ 只读：`mode=ro`，绝不对 Kuma 的库做任何写操作 ⚠
"""
from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import path

from core import ops


def ops_dashboard(request):
    """★ `/admin/ops/` —— 依赖状态 / Kuma 监控 / 索引进度 ⚠"""
    context = {
        **admin.site.each_context(request),
        "title": "运维概览",
        "checks": ops.stack_checks(),
        "kuma": ops.kuma_monitors(),
        "index": ops.index_stats(),
        "backup": ops.backup_status(),
        "collected_at": ops.collected_at(),
    }
    return TemplateResponse(request, "admin/ops_dashboard.html", context)


def register_ops_url() -> None:
    """★ 把 `/admin/ops/` 挂进 admin 的 URLconf（* 不改 AdminSite 类）⚠"""
    original = admin.site.get_urls

    def get_urls():
        custom = [
            path("ops/", admin.site.admin_view(ops_dashboard), name="ops-dashboard"),
        ]
        return custom + original()

    admin.site.get_urls = get_urls
