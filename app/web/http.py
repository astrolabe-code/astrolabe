"""Astrolabe · ① Web 层：响应形态（envelope）

★ 依据 `frontend-contract.md` §1 / §11 —— 后端有**四种**响应形态，
  前端 `src/api/client.ts` 统一归一为 `{ok:true,data}` / `{ok:false,error}`。

| 形态 | 长什么样 | 用在哪 |
|---|---|---|
| **①** | `{ok:true, data:X}` | ★ **新增接口一律用它** |
| **②** | `{ok:true, 展开字段…}` | 契约点名是 ② 的既有接口（`graph/summary`、`graph/nodes`…） |
| **③** | `{"error":"文案"}` + 状态码 | 只读接口的 404 / 403 / 400 |
| **④** | `{ok:false, error:{code,message}}` + 状态码 | 写操作失败（带 `code`） |

★ 我们的取舍：

- **新接口一律 ①**（`ok` / `fail`）—— 干净、前端只认一种
- ⚠ **但契约里点名是 ② 的接口照 ② 实现**（`ok_flat`）——
  否则现有前端要改，违背「后端既有接口形态不动」的原则（§1 末段）
- ⚠ ③ 与 ④ 的区别**不是风格**：③ 无法携带 `code`，④ 能 ⇒
  ★ **前端要对 `code` 分支的地方必须用 ④**（如 `stale_rev` / `project_busy`）

⚠ 分层纪律（`ARCHITECTURE.md` A3）：本模块只依赖 Django，❌ 不含业务逻辑。
"""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, JsonResponse


def ok(data: Any = None, status: int = 200) -> JsonResponse:
    """① `{ok:true, data:X}` —— ★ **新接口一律用它**。"""
    return JsonResponse({"ok": True, "data": data}, status=status, json_dumps_params=_DUMPS)


def ok_flat(**fields: Any) -> JsonResponse:
    """② `{ok:true, 展开字段…}` —— ⚠ **仅用于契约里点名的既有接口**。

    ★ 原则（§1）：**「后端既有接口形态不动」** —— 前端已按 ② 解析的接口
      改成 ① 会**直接打断现有前端**，所以这里必须留一条 ② 的出口。
    """
    return JsonResponse({"ok": True, **fields}, json_dumps_params=_DUMPS)


def fail(message: str, status: int = 400, code: str = "", data: Any = None) -> JsonResponse:
    """③ / ④ 错误响应。

    · 不给 `code` ⇒ ③ `{"error":"文案"}`（只读接口的 404 / 403 / 400）
    · 给 `code`  ⇒ ④ `{ok:false, error:{code,message}}`（前端要对 `code` 分支时用）

    ⚠ 错误文案一律**中文**（与契约的 400 文案口径一致）；
      ⚠ **不回显** `uid` / `file_path` 明细（§19.3）。
    """
    if not code:
        return JsonResponse({"error": message}, status=status, json_dumps_params=_DUMPS)
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if data is not None:
        payload["data"] = data  # ★ 如 `stale_rev` 要带最新 graph_rev，前端靠它重放
    return JsonResponse(payload, status=status, json_dumps_params=_DUMPS)


# ---------------------------------------------------------------------------

def safe_next_url(raw: str, *, default: str | None = None) -> str | None:
    """★★ 校验 `next_url` —— ★ 返回 `None` 表示**不允许**（⚠ 调用方必须拒绝，❌ 不得回退到原值）。

    ⚠★ 放在 `http.py`（❌ 不放 `views/auth.py`）的原因很实在：
      ★ **发布端点也要用它**，★ 而 `views/auth.py` 又要调发布逻辑
      ⇒ ⚠ 留在 view 层就会形成**循环 import**（★ 这类工具就该待在底层）。

    ★ 允许两种：

    | 形态 | 例子 | 为什么允许 |
    |---|---|---|
    | ★ **站内相对路径** | `/p/proj_xxx` | ★ 跳不出去 |
    | ★ **白名单 origin** | `https://astro.example.com/p/x` | ★ 前端可能有多个域名 |

    ⚠★ **`//evil.com` 必须被挡住** —— ★ 它是**协议相对 URL**，浏览器会当成 `https://evil.com`
      ⇒ ★ 只判 `startswith("/")` 会被**直接绕过**（经典坑）。
    """
    from urllib.parse import urlsplit

    from django.conf import settings

    target = (raw or "").strip()
    if not target:
        return default if default is not None else getattr(settings, "ASTROLABE_SPA_URL", "/")

    # ★ 站内相对路径 —— ⚠ 必须同时排除 `//`（协议相对）与 `/\`（某些浏览器会归一成 `//`）
    if target.startswith("/") and not target.startswith("//") and not target.startswith("/\\"):
        return target

    parts = urlsplit(target)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin in tuple(getattr(settings, "ASTROLABE_ALLOWED_ORIGINS", ())):
        return target
    return None


def read_json(request: HttpRequest) -> dict:
    """★ 读请求体 JSON —— ⚠ **解析失败一律返回 `{}`**，❌ 不抛异常。

    ★ 与 `projects.py` 里的 `_body()` 是同一口径（契约 §12：坏 JSON ⇒ `400 bad_json`），
      ★ 这里抽出来给新接口共用 —— ⚠ 两边各写一份，早晚会不一致。
    """
    body = getattr(request, "body", b"") or b""
    if not body:
        return {}
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def project_ref_of(request: HttpRequest) -> str:
    """从已解析的路由参数里取 `project_ref`。

    ⚠ 本函数**不做校验** —— 形态已由路由转换器挡掉（`core/refs.py`）；
      需要二次确认时用 `core.refs.is_valid_project_ref`。
    """
    return str(request.resolver_match.kwargs.get("project_ref", "")) if request.resolver_match else ""


def _dumps_default(obj: Any):  # pragma: no cover - 兜底
    return str(obj)


_DUMPS: dict[str, Any] = {
    "ensure_ascii": False,   # ★ 中文直接输出（错误文案 / 节点名里有中文）
    "default": _dumps_default,
}
