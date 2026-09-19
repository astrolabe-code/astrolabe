"""Astrolabe · 根路由

★ 分层纪律：本文件只做【路由挂载】，❌ 不写业务逻辑。
   ① Web 层的接口挂到 /api/
   其余（/admin/、/healthz）在这里直接挂。
"""

from django.contrib import admin
from django.urls import include, path

from core.views import healthz

urlpatterns = [
    # ★ 健康检查（DEPLOYMENT.md D5：容器 healthcheck 探测它）
    # ⚠ 只检查进程存活 —— 【不要】在这里查数据库，否则探针会变成压测
    path("healthz", healthz, name="healthz"),

    path("admin/", admin.site.urls),

    # ★ ① Web 层接口（后续在 web/api/ 下实现）
    path("api/", include("web.urls")),
]
