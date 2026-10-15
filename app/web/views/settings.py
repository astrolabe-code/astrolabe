"""Astrolabe · **设置接口**（★ `B190` · 2026-10-15）

★★★ **本文件只做一件事**：★ 把 `core/settings_table.py` 那套**三级继承**暴露成 HTTP ⚠

## ★★ 四条口径

```
① ★★ 未设置 = 不存行 ⇒ ★ 所以 GET 永远有值（* 回落到代码默认）✅
② ★★ 响应带 `source` ⇒ ★ 前端能显示「这一项为什么是这个值」⚠
③ ★★ `gated=true` 的键只有管理员能改（* 403）✅
④ ★★ 未注册的键 ⇒ ★ 400（* 后端 `spec_of()` 直接 KeyError）✅
```

## ⚠★ 为什么不在视图里做校验

```
★★ 校验全在 `core/settings_table.py`（* `set_value()` 里）✅
   · · ★ 门禁判断 · 档位判断 · 键是否注册 ⇒ ★ **一处** ⚠
   · · ★★ 视图只负责"把异常翻成 HTTP 状态码" ⚠
```

"""

from django.http import HttpRequest
from django.views.decorators.http import require_http_methods

from core import settings_table as st
from web.http import fail, ok_flat, read_json
from web.permissions import can_edit, can_view, current_user, get_project


@require_http_methods(["GET", "PATCH"])
def user_settings(request: HttpRequest):
    """`GET/PATCH /api/me/settings/` —— ★★ **用户档**设置。

    ## GET 发什么

    ```json
    {"settings": {"note.revision_limit": 10, …},
     "specs": [{"key":…, "label":…, "note":…, "type":"int",
                "default":10, "value":10, "source":"default", "gated":true}]}
    ```

    ⚠★ `specs` 是给前端**渲染控件**用的（* 开关 / 下拉 / 输入框）✅
      · · ★ 它只含**用户档可用**的键（* 项目档的键不出现）⚠
      · · ★★ 而"哪些键存在"由**代码注册表**决定 ⇒ ★ 用户不能自己造字段（* B190）⚠
    """
    user = current_user(request)
    if user is None:
        return fail("请先登录", 401, code="unauthorized")

    if request.method == "PATCH":
        return _patch_user(request)
    return ok_flat(settings=st.all_for(user=user), specs=_specs("user", user))


@require_http_methods(["GET", "PATCH"])
def project_settings(request: HttpRequest, project_ref: str):
    """`GET/PATCH /api/projects/<ref>/settings/` —— ★★ **项目档**设置。"""
    project = get_project(request, project_ref)
    if project is None or not can_view(request, project):
        return fail("项目不存在", 404, code="not_found")

    if request.method == "PATCH":
        if not can_edit(request, project):
            return fail("没有权限修改这个项目的设置", 403, code="forbidden")
        return _patch(request, project=project)
    return ok_flat(settings=st.all_for(project=project),
                   specs=_specs("project", project))


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------

def _specs(scope: str, owner) -> list[dict]:
    """★★ **给前端渲染控件用的规格表**。

    ⚠★ 每一项都带 `source` ⇒ ★ 前端能显示"这一项为什么是这个值" ⚠
      （* `default` / `global` / `user` / `project`）✅
    """
    out = []
    for s in st.keys_for(scope):
        value, source = st.resolve(s.key, user=owner if scope == "user" else None,
                                   project=owner if scope == "project" else None)
        out.append({
            "key": s.key,
            "label": s.label,
            "note": s.note,
            "type": s.type.__name__,
            "default": s.default,
            "value": value,
            "source": source,
            "gated": s.gated,
        })
    return out


def _patch(request: HttpRequest, *, project=None, user=None):
    body = read_json(request)
    if not isinstance(body, dict) or not body:
        return fail("请求体必须是非空 JSON 对象", 400, code="bad_body")

    applied, rejected = {}, {}
    for key, value in body.items():
        try:
            applied[key] = st.set_value(
                key, value, project=project, user=user, actor=user
            )
        except KeyError:
            rejected[key] = "未注册的设置键"
        except PermissionError:
            rejected[key] = "门禁类设置只有管理员能改"
        except (TypeError, ValueError):
            rejected[key] = "值的类型不对"

    # ⚠★ 只要有一个被拒 ⇒ ★ 整件 400（* ❌ 不是"部分成功"）⚠
    #   · · ★ 理由：* 部分成功会让前端**不知道该显示哪一份** ⚠
    if rejected:
        return fail("有些设置没被接受", 400, code="bad_setting",
                    applied=applied, rejected=rejected)

    return ok_flat(
        settings=(st.all_for(project=project) if project is not None
                  else st.all_for(user=user)),
        applied=applied,
    )


def _patch_user(request: HttpRequest):
    return _patch(request, user=request.user)
