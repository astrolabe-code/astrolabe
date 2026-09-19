"""Astrolabe · 共享内核：健康检查

⚠ 设计约束（DEPLOYMENT.md D5）：
   本视图**只检查进程存活**，不做任何 IO。
   ❌ 不要在这里查数据库 / Redis —— 那会让容器探针变成周期性压测。
"""

from django.http import JsonResponse


def healthz(request):
    """存活探针：进程能响应即返回 200。"""
    return JsonResponse({"status": "ok"})
