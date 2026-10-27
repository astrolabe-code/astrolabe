"""★★★ **前台可读的站点配置**（`D120` · 2026-10-27）⚠

## 为什么需要这个端点

以前站点参数**只有后台能读**（`appsettings.get()` 在 Python 里），
前端一个都拿不到 ⇒ 任何「后台可调」的界面阈值都无从谈起 ⚠

## ★★★ 安全口径：**白名单**，⛔ 不是把 KEYS 倒出去

```\n可以给前台的     纯体验类阈值（停留秒数、每页条数…）\n⛔ 绝不外发       paused / quota.* / 门禁项 —— 这些会暴露运营状态与额度 ⚠\n```\n
新增键时，**必须显式加进 `PUBLIC_KEYS`**，否则前台读不到（默认安全）✅

## ★ 缓存

`Cache-Control: public, max-age=60` —— 改完参数最迟 1 分钟生效；
前端再用 react-query 的 `staleTime` 兜一层（见 `query/siteConfig.ts`）✅
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_http_methods

from core import appsettings

#: ★★★ **允许前台读取的键**（⚠ 新增前先想清楚：这个值暴露出去有没有风险）⚠
PUBLIC_KEYS = (
    "ui.resume_dwell_seconds",
)


@require_http_methods(["GET"])
@cache_control(public=True, max_age=60)
def site_config(request: HttpRequest) -> JsonResponse:
    """`GET /api/site-config/` —— 前台需要的站点参数（公开、无需登录）⚠

    ⚠ 键名转成 camelCase 再给前端，避免 JS 里到处写点号字符串 ⚠
    """
    data = {}
    for key in PUBLIC_KEYS:
        # ★ 用短名（`ui.resume_dwell_seconds` ⇒ `resumeDwellSeconds`）✅
        short = key.split(".", 1)[-1]
        parts = short.split("_")
        camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
        data[camel] = appsettings.get(key)
    return JsonResponse({"ok": True, **data})
