"""Astrolabe · ① Web 层：**图修补**（维护者手工修补 · `§2.3.12` 通道 ②）

---

# ★★★ 为什么必须有网页接口

> **用户原话（`B157`）**：「**修补节点是项目创建者自己修补，不是我这个管理员帮他修补。**
> 所以，**必须在网页上能操作**。」

⚠★ 我上一批做成了 CLI（`manage.py curate`）—— ★ **那是"管理员代劳"的形态，搞错了两件事**：

| | ⚠ CLI（只有运维能用） | ★★ 网页接口 |
|---|---|---|
| ★ **谁用** | 只有能登服务器的人 | ✅ **项目创建者自己** |
| ★ **权限** | ⚠ 有 shell 就能改**任何**项目 | ✅ **按 `can_curate()` 判**（owner 或 staff） |
| ★ **审计的 actor** | ⚠ 一个运维账号 | ✅ **维护者本人的账号** |

⇒ ★★ CLI **保留**（★ 事故处理 / 运维需要在服务器上直接操作时有用），
  ★ **但主路径是这个接口**。

---

# 端点（★ 契约 `frontend-contract.md` §2 已定义，❌ 不是我另起的）

```
POST /api/projects/<project_ref>/graph/edit/
body: {base_graph_rev?, reason, changes: [ {action, ...}, ... ]}
resp: {ok:true, data:{graph_rev, applied}}
```

★ `changes[].action` 六种：`add_node` / `update_node` / `remove_node` /
  `add_edge` / `update_edge` / `remove_edge`

★ 另有 `GET …/graph/manual/` —— ★ **看一眼这个项目上被人补过什么**
  （★ 直接支撑 `§2.3.12` 规则 2「**UI 上人工项有视觉标记**」）✅

---

# ★ 状态码口径

| 情况 | 返回 | 为什么 |
|---|---|---|
| ★ 未登录 | **401** `unauthenticated` | ★ 这是**明确信号**（前端据此弹登录）—— ⚠ 不是越权 |
| ★★ **不是这个项目的人** | **404** | ★★ **与"项目不存在"不可区分**（`§19.3`）—— ⚠ 否则 `project_ref` 就成了**探测工具**（403 会告诉攻击者"这个项目存在"） |
| ★ 坏 JSON | **400** `bad_json` | 契约 §12 |
| ★★ **`base_graph_rev` 不匹配** | **409** `stale_rev` + `data:{graph_rev}` | ★ 前端靠 `data.graph_rev` **重读后重放**（契约 §6） |
| ★ 理由为空 / 动作不认识 | **400** `bad_request` | ⚠★ 见下 |

---

# ⚠★ 为什么 `reason` 是**必填**

★ 主文 `§2.3.12` 规则 4：

> **必须有全量审计**：谁 / 何时 / 加了删了什么 / **为什么**
> —— ⚠ **「用户全权负责」的技术前提就是「可追溯」；
> 没有审计，「全权负责」就变成「没人负责」。**

⇒ ★★ 所以前端**必须**让维护者填一句理由（★ 他也知道自己为什么改）。
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from graph import curate
from web import permissions
from web.http import fail, ok, read_json

#: ★ 前端拿它做分支 —— ⚠ 与前端要**写死一致**
CODE_BAD_JSON = "bad_json"
CODE_BAD_REQUEST = "bad_request"
CODE_STALE_REV = "stale_rev"


def _permitted(request: HttpRequest, project_ref: str):
    """★ 取项目并校验**可否修补** —— ★★ 越权与"不存在"**一律同一种返回**。

    ★★ 委托 `graph.curate.can_curate()`（★ 方向 `web → graph`，符合 A3 分层）——
      ⚠ 反过来的话 `graph/` 就要 import `web/`，**越层**了。
    """
    verdict = curate.can_curate(project_ref, permissions.current_user(request))
    if not verdict.allowed:
        return None, verdict
    return verdict, None


@require_http_methods(["POST"])
def edit(request: HttpRequest, project_ref: str) -> JsonResponse:
    """★ `POST …/graph/edit/` —— **维护者批量修补图**（★ 一次一批）。"""
    user = permissions.current_user(request)
    if user is None:
        # ★ 401 —— ⚠ **不是 404**：这里"需要登录"是**明确信号**（前端据此弹登录），
        #   与"越权"不是一回事（越权才是 404，见下）
        return fail("请先登录", 401, code="unauthenticated")

    verdict, denied = _permitted(request, project_ref)
    if denied is not None:
        # ★★ **越权统一 404**（与"项目不存在"不可区分）—— `§19.3`
        return fail(permissions.NOT_FOUND, 404, code=denied.code)

    body = read_json(request)
    if not body:
        # ⚠ 空 body 与坏 JSON 都到这里 —— ★ 文案要说清"要 JSON"
        return fail("请求体必须是 JSON", 400, code=CODE_BAD_JSON)

    changes = body.get("changes")
    if changes is None:
        # ★ 兼容：允许用 `change` 传单条（★ 让前端写小改动时少一层数组）
        single = body.get("change")
        changes = [single] if isinstance(single, dict) else None
    if not isinstance(changes, list):
        return fail("changes 必须是一个数组", 400, code=CODE_BAD_REQUEST)

    reason = (body.get("reason") or "").strip()
    if not reason:
        # ★★ 见模块文档：★ 这不是"流程规定"，而是「**用户全权负责**」的技术前提
        return fail(
            "请填写修改理由 —— 这段图是你自己维护的，"
            "理由会记进审计（半年后你回来看，才知道当时为什么改）",
            400,
            code=CODE_BAD_REQUEST,
        )

    base = body.get("base_graph_rev")
    try:
        base_graph_rev = int(base) if base is not None and base != "" else None
    except (TypeError, ValueError):
        return fail("base_graph_rev 必须是整数", 400, code=CODE_BAD_REQUEST)

    try:
        result = curate.apply_changes(
            project_ref,
            by=user,
            reason=reason,
            changes=changes,
            base_graph_rev=base_graph_rev,
        )
    except ValueError as exc:
        # ⚠★ `apply_changes` 的参数校验会**抛**（★ 那是"调用方写错了"）——
        #   ★ 在 Web 层翻译成 400，❌ 不让它变成 500
        return fail(str(exc), 400, code=CODE_BAD_REQUEST)

    if not result.ok:
        if result.stale:
            # ★★ 409 + **当前** rev —— ★ 前端据此**重读后重放**（契约 §6）
            return fail(result.message, 409, code=CODE_STALE_REV,
                        data={"graph_rev": result.current_rev})
        code = result.detail.get("code") or CODE_BAD_REQUEST
        # ⚠ 权限失败理论上到不了这里（上面已判过）—— ★ 但真到了也不能泄露
        status = 404 if code in ("not_found", "forbidden") else 400
        return fail(result.message, status, code=code)

    return ok({"graph_rev": result.graph_rev, "applied": result.applied})


@require_http_methods(["GET"])
def manual(request: HttpRequest, project_ref: str) -> JsonResponse:
    """★ `GET …/graph/manual/` —— ★ **哪些是人补的**（`origin="manual"`）。

    ★★ 用途：★ `§2.3.12` 规则 2 要求「**UI 上人工项有视觉标记**」——
      ★ 这个端点让前端能显示"这张图里有 N 项是维护者补的" ✅

    ⚠ 只读接口 ⇒ ★ **按 `can_view` 判**（公开项目游客也能看）——
      ★ 因为"**哪些是机器给的、哪些是人修的**"是**来源标注**，
      ★ §19.4「**来源与置信度必须标注**」把它归为**读者有权知道的信息**。
    """
    project = permissions.get_project(request, project_ref)
    if project is None or not permissions.can_view(request, project):
        return fail(permissions.NOT_FOUND, 404)

    from graph.models import ORIGIN_MANUAL

    summary = curate.manual_summary(project_ref)
    # ★ 首屏不需要 200 条明细 —— ★ 只给"有多少"，明细按需再拉
    summary.pop("nodes", None)
    summary["has_manual"] = bool(summary["manual_nodes"] or summary["manual_edges"])
    summary["origin_manual"] = ORIGIN_MANUAL
    return ok(summary)
