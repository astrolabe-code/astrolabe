"""Astrolabe · 共享内核：健康检查

⚠ 设计约束（DEPLOYMENT.md D5）：
   本视图**只检查进程存活**，不做任何 IO。
   ❌ 不要在这里查数据库 / Redis —— 那会让容器探针变成周期性压测。
"""

from django.http import JsonResponse


def healthz(request):
    """⭐ **存活探针**：进程能响应即返回 200。

    ⚠ 刻意**不查任何依赖**（`DEPLOYMENT.md` D5）：容器 healthcheck 每 30s 打一次，
      * 在里面查库等于把探针变成压测 ⚠
    · · 要判断"能不能真的干活"，用下面的 `readyz` ✅
    """
    return JsonResponse({"status": "ok"})


def readyz(request):
    """⭐⭐ **就绪探针**：DB / Redis / Meilisearch 都通才 200（2026-10-24）⚠

    ## ★ 为什么必须有它

    ```
    只探 /healthz ⇒ PG 挂了、Redis 挂了，进程照样回 200
    ⇒ 监控一片绿，页面却全白（* 所有者问「django后端怎么监测到挂了」）⚠
    ```

    ## ★ 谁在用

    ```
    Uptime Kuma「Django 后端」监控 → 每 60s 打这个
    ⛔ 容器 healthcheck 不要用（* 那会把探针变成压测）⚠
    ```

    Returns: 全通 200；任一失败 503，并在 `checks` 里指明是谁坏了 ✅
    """
    from core import ops

    checks = ops.stack_checks()
    healthy = all(item["ok"] for item in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=200 if healthy else 503,
    )
