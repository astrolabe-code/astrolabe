"""Astrolabe · ① Web 层：**参数中心**（`U2.4` 两级权限 · `U2.5` 审计纪律）

| 方法 | 路径 | 谁 |
|---|---|---|
| `GET` | `/api/admin/settings/` | ★ **staff**（★ 读全部参数 + 每个参数"你可不可改"） |
| `POST` | `/api/admin/settings/` | ★ **staff**（⚠★ 但**门禁类**只有 **superuser** 能改） |

---

# ★★★ 两级权限：「是不是 staff」和「能不能改这一个」是**两件事**

★ `U2.4` 的原文：**staff** 能审核；★ 而改**门禁类参数**只有 **superuser** 能。

⚠★ 关键在于**这个判定放在哪一层** —— ★ `web/permissions.py::staff_only` 的文档里写明了：

> ★ 后者由 `appsettings.set_value()` 自己拦（⚠ 不在这一层判，因为那是**参数层**的纪律）。

⇒ ★★ 本视图**只管第一层**（`@staff_only`），★ 第二层**交给 `set_value()` 抛 `PermissionError`**，
   ★★ 这里**只负责把它翻译成 `403`**（⚠ 否则会变成 `500`，★ 前端就只能显示"服务器错误"）✅

★ 这样做的好处：★ **纪律只有一处**（`appsettings.py`）——
   ★ 哪天新增一个 `gated=True` 的键，★ **本文件一个字都不用改** ⚠

---

# ⚠★★ 为什么这里要**自己校验类型**（★ 这是被 `_coerce` 逼出来的）

★ `core/appsettings.py::_coerce()` 的写法是：

```python
try:
    if spec.type is bool: return str(value).lower() in ("1","true","yes","on")
    ...
except (TypeError, ValueError):
    pass        # ★★ 静默
```

⇒ ★★★ **后果**：★ 前端若发 `{"registration_open": "abc"}`
   ⇒ ★ `"abc"` 不在那个集合里 ⇒ ★★ **静默存成 `False`** ⚠

★★ 而"**把注册入口悄悄关掉**"这种错误，★ **和 `_int_in_range` 注释里骂的那个毛病是同一类**：
   ★ 它**看起来成功了**（返回 200），★ 而管理员要做的事**没做成** ⚠

⇒ ★★ 所以本视图在**写库之前**做一次显式类型检查，★ 不合法**直接 400**（★ 见 `_check_type`）。

★ 这与本项目一路的纪律一致：★ **让错误在输入处暴露** ✅
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from core import appsettings
from core.appsettings import KEYS, KeySpec
from web.http import fail, ok, read_json
from web.permissions import staff_only

#: ★ `type` 字段的显示名 —— ⚠ 前端据它决定"渲染开关还是输入框"
_TYPE_NAMES = {bool: "bool", int: "int", dict: "dict"}


def _can_edit_gated(request: HttpRequest) -> bool:
    """★ 当前用户能不能改**门禁类**参数（★ 只有 superuser 能）。"""
    return bool(getattr(getattr(request, "user", None), "is_superuser", False))


def _setting_json(key: str, value: Any, *, can_edit_gated: bool) -> dict:
    """★ 一个参数的投影（★ 含**给人看**的 `label` / `note`）。

    ⚠★ 刻意多给两样东西：

    | 字段 | 为什么要给 |
    |---|---|
    | `label` / `note` | ★ `KeySpec` 就要求"没说明的参数是灾难" —— ★ 那这些说明**得真的被看到** |
    | `editable` | ★★ 前端据此把开关**置灰** —— ⚠ 而不是"点了再吃 403"（★ 那是让用户白点一次）|
    """
    spec = KEYS[key]
    return {
        "key": key,
        "value": value,
        # ★ 前端用它在界面里挑控件（开关 / 数字框）—— ⚠ 不是 Python 类型名（那是实现细节）
        "type": _TYPE_NAMES.get(spec.type, "str"),
        "label": spec.label,
        "note": spec.note,
        "gated": spec.gated,
        "editable": (not spec.gated) or can_edit_gated,
    }


def _all_json(*, can_edit_gated: bool) -> list[dict]:
    """★★ **一次查库**取全部参数（★ `all_settings()` 的推荐用法：❌ 不要每个键各查一次）。"""
    current = appsettings.all_settings()
    return [
        _setting_json(key, current.get(key, KEYS[key].default), can_edit_gated=can_edit_gated)
        for key in KEYS
    ]


def _check_type(spec: KeySpec, value: Any) -> str:
    """★ 写入前的类型检查 —— ★★ 返回错误文案，空串 = 通过。

    ⚠★★ **为什么只认 JSON 原生类型**（不接受 `"true"` 这种字符串）：

    ★ 一旦允许字符串，★ 就得回答"`"yes"` 算不算真"这类问题 —— ★ 而那正是
      `_coerce` 现在**默默替用户猜**的地方 ⚠
    ⇒ ★★ 干脆**只认 `true` / `false` / 整数** —— ★ 前端本来就发 JSON 布尔 ✅
    """
    if spec.type is bool:
        # ⚠ `isinstance(True, int)` 在 Python 里是 `True` ⇒ ★ 必须先判 bool（★ 顺序不能反）
        if isinstance(value, bool):
            return ""
        return f"{spec.label}：需要布尔值（true / false）"
    if spec.type is int:
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{spec.label}：需要整数"
        return ""
    return ""


@require_http_methods(["GET", "POST"])
@staff_only
def settings_view(request: HttpRequest) -> JsonResponse:
    """`GET` 读全部参数 / `POST` 改一批参数（★ 全成或全不成）。"""
    can_gated = _can_edit_gated(request)
    if request.method == "GET":
        return ok(
            {
                "settings": _all_json(can_edit_gated=can_gated),
                # ★★ 显式告诉前端"你够不够格改门禁类" —— ★ 省得它自己猜 `is_superuser`
                #    （⚠ 而 `auth.user_json()` **刻意不返回** `is_superuser`，★ 前端根本猜不出来）
                "can_edit_gated": can_gated,
            }
        )
    return _update(request, can_edit_gated=can_gated)


def _update(request: HttpRequest, *, can_edit_gated: bool) -> JsonResponse:
    """★ 批量改参数 —— ★★ **全部成功或全部回滚**。

    ⚠★ 为什么必须用事务：★ 管理员一次改三个开关（★ 比如"开注册 + 关邀请"），
       ★ 若第三个被 `set_value()` 以 `PermissionError` 拒掉（★ 它是门禁类），
       ★★ 前两个**已经写进库了** ⇒ ★ 用户看到一句报错，★ 而状态**已经半改**了 ⚠
       ⇒ ★ 那比整批失败**难查得多**（★ 他以为"没改成功"）。
    """
    from django.db import transaction

    body = read_json(request)
    values = body.get("values")
    if not isinstance(values, dict) or not values:
        return fail("请给出要修改的参数（`values` 对象）", 400, code="missing_values")

    # ★ 先**整批**校验，❌ 不要边写边验（★ 那样失败时已经写了一半）
    unknown = sorted(k for k in values if k not in KEYS)
    if unknown:
        return fail(f"未注册的参数：{'、'.join(unknown)}", 400, code="unknown_key")
    for key, raw in values.items():
        err = _check_type(KEYS[key], raw)
        if err:
            return fail(err, 400, code="bad_value")

    applied: dict[str, Any] = {}
    try:
        with transaction.atomic():
            for key, raw in values.items():
                applied[key] = appsettings.set_value(key, raw, actor=request.user)
    except PermissionError as exc:
        # ★★ 门禁类 + 非 superuser —— ★ `set_value()` 自己抛的（★ 见文件头"纪律只有一处"）
        #    ⚠ 翻译成 403，❌ 不是 500
        return fail(str(exc), 403, code="gated_superuser_only")
    except KeyError as exc:
        return fail(str(exc), 400, code="unknown_key")

    return ok(
        {
            "applied": applied,
            # ★ 回最新值 —— ★ 省得前端再打一枪（★ 而且事务提交后的值才是权威）
            "settings": _all_json(can_edit_gated=can_edit_gated),
        }
    )
