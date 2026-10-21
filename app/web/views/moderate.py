"""Astrolabe · **管理处置接口**（★ `B208` · 2026-10-16）—— ★★ 管理员唯一的权力

## ★★★ 所有者原话（逐字，`A33`）

> 「**网站管理员有权限修改图和笔记，不行。管理员只有隐藏下架项目和笔记的权限，
> 而且一旦被管理员隐藏下架，非管理员不可恢复。**」

## ★★ 三个动作（* 端点契约，* `B208`③）

| 动作 | 语义 | 理由 |
|---|---|---|
| `hide` | ★★ **隐藏** ——* **只有作者 / owner 能看到**，* 别人**直接链接也不可访问** | 所有者裁定（`A34`，覆盖 `U3.5` 旧口径） |
| `take_down` | ★★ **下架** ——* **物理删除**数据 | 所有者原话整句：「下架是彻底从服务器上删除数据。」 |
| `restore` | ★★ **恢复** ——* 仅 `hidden → active` | ★★ **仅管理员能按** ⇒* 非管理员不可恢复 |

## ★★ 六条口径

```
① ★★ 整条端点 @staff_only ⇒* 游客 / 普通用户 / 协作者一律 401 / 403 ✅
② ★★ `reason` 对 hide / take_down **必填**（* `B196`：* 作者来问
     "为什么"必须答得出）✅ · * restore 可空 ✅
③ ★★ 下架前必须**留痕**：
     · · ★ 项目 ⇒* 写一条 `ProjectReview`（* **记在 owner 名下** ⇒*
       所有者在「我的提交」里看得到理由；* `quota_refunded=True` ⇒*
       ❌ 不因此挨额度）+ `AuditLog` ✅
     · · ★ 笔记 ⇒* `AuditLog` ✅
④ ★★ 删除用 `projects.purge_project()`（* 与 owner 删项目**同一套级联**，
     * ❌ 绝不删基图）✅
⑤ ★★ owner 的 PATCH **不接受** state（* `B208`⑥）⇒* 他没有自己改回去的路 ✅
⑥ ★★ 管理员**不能**改内容（* 图 / 笔记 / 评论除外——* 评论删除是保留项，
     * 见 `core/access.can_delete_comment`）✅
```

⚠ 响应形态一律 **①**（`{ok:true,data:{…}}`）—— * `http.py` 规定新接口用它 ⚠
"""

from __future__ import annotations

from django.http import HttpRequest
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core import access
from core.models import AuditLog, Note, Project, ProjectReview
from web.http import fail, ok, read_json
from web.permissions import staff_only
from web.views.projects import purge_project

#: ★ 三个动作（* 契约 `B208`③）✅
ACTIONS = ("hide", "take_down", "restore")

#: ★ `reason` 最长（★ 与模型 `varchar(400)` 一致）
REASON_MAX = 400


# ---------------------------------------------------------------------------
# 项目
# ---------------------------------------------------------------------------

@require_http_methods(["POST"])
@staff_only
def moderate_project(request: HttpRequest, project_ref: str):
    """`POST /api/admin/projects/<ref>/moderate/`。

    Body: `{action: hide|take_down|restore, reason}`

    - `hide` ⇒ `{action, state, reason, moderated_by, moderated_at}`
    - `take_down` ⇒ `{action, deleted, reason}`（★ 数据已物理删除）
    - `restore` ⇒ `{action, state, reason, moderated_by, moderated_at}`

    ⚠★ `take_down` 之前先写 `ProjectReview` 流水（* 记在 owner 名下）✅
    """
    project = Project.objects.filter(project_ref=project_ref).first()
    if project is None:
        return fail("项目不存在", 404, code="not_found")

    body = read_json(request)
    action = str(body.get("action") or "").strip()
    if action not in ACTIONS:
        return fail(f"action 必须是 {ACTIONS} 之一", 400, code="bad_action")
    reason = str(body.get("reason") or "").strip()[:REASON_MAX]

    if action in ("hide", "take_down") and not reason:
        return fail(f"{action} 必须填写理由（作者问起来要答得出）", 400, code="missing_reason")

    if action == "restore" and project.state != Project.STATE_HIDDEN:
        return fail("项目当前不是隐藏状态，无需恢复", 400, code="not_hidden")

    if action == "take_down":
        return _take_down_project(request, project, reason)
    return _set_project_state(request, project, action, reason)


def _take_down_project(request: HttpRequest, project: Project, reason: str):
    """★★ **下架 = 物理删除**（* `B208`③）⚠

    ## ★★ 顺序（* 不能反）

    ```
    ① ★★ 先写 `ProjectReview` 流水 ——* 删了就写不回去了 ⚠
       · · ★ 记在 **owner 名下**（* `submitted_by`）⇒* 他在「我的提交」里看得到 ✅
       · · ★ `quota_refunded=True` ⇒* ❌ 不让他因此挨额度 ✅
    ② ★ 再物理删除（* `purge_project`：* 同一套级联，* ❌ 不碰基图）✅
    ③ ★ 最后写 `AuditLog` ✅
    ```
    """
    admin = request.user
    now = timezone.now()

    # ① 留痕（* 项目行还在，* 冗余列从活对象上抄）✅
    ProjectReview.objects.create(
        project=project,
        project_ref=project.project_ref,
        project_name=project.name,
        submitted_by=project.owner,
        submitted_by_name=project.owner.get_username() if project.owner_id else "",
        repo_url=project.repo_url or "",
        reason_code="taken_down",
        reason_text=reason,
        user_message="该项目已被管理员下架，相关数据已从服务器删除。如有异议请联系站点管理员。",
        decision=ProjectReview.DECISION_REJECTED,
        decided_by=admin,
        decided_at=now,
        decision_note=reason,
        # ★★ 退还额度 ——* 否则"下架"变成"挨一次限额"，* 那是双重惩罚 ⚠
        quota_refunded=True,
    )

    # ② 物理删除（* 项目行没了 ⇒* 上面那行的 `project` 外键自动 SET_NULL ✅）
    purge_project(project.project_ref)

    # ③ 审计 ✅
    _audit(request, "project.takedown", project_ref=project.project_ref,
           name=project.name, reason=reason)

    return ok({"action": "take_down", "deleted": True, "reason": reason})


def _set_project_state(request: HttpRequest, project: Project, action: str, reason: str):
    """★★ hide / restore ——* 只改**状态**，* ❌ 不动内容 ⚠"""
    project.state = Project.STATE_HIDDEN if action == "hide" else Project.STATE_ACTIVE
    # ★★ 「最近一次处置」三列（* 同 `B196` 项目侧形状）✅
    project.moderation_reason = reason
    project.moderated_by = request.user
    project.moderated_at = timezone.now()
    project.save(
        update_fields=["state", "moderation_reason", "moderated_by", "moderated_at", "updated_at"]
    )

    _audit(request, f"project.{action}", project_ref=project.project_ref,
           name=project.name, reason=reason)

    return ok(
        {
            "action": action,
            "state": project.state,
            "reason": reason,
            "moderated_by": request.user.get_username(),
            "moderated_at": project.moderated_at.isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# 笔记
# ---------------------------------------------------------------------------

@require_http_methods(["POST"])
@staff_only
def moderate_note(request: HttpRequest, note_id: int):
    """`POST /api/admin/notes/<id>/moderate/`。

    Body: `{action: hide|take_down|restore, reason}` —— * 口径同项目 ✅

    ⚠★ 笔记下架 = 删除该行 ⇒* 它的**段落 / 评论 / 点赞 / 版本**一并消失
      （* 模型上全是 CASCADE）✅
    """
    note = Note.objects.filter(pk=note_id).first()
    if note is None:
        return fail("笔记不存在", 404, code="not_found")

    body = read_json(request)
    action = str(body.get("action") or "").strip()
    if action not in ACTIONS:
        return fail(f"action 必须是 {ACTIONS} 之一", 400, code="bad_action")
    reason = str(body.get("reason") or "").strip()[:REASON_MAX]

    if action in ("hide", "take_down") and not reason:
        return fail(f"{action} 必须填写理由（作者问起来要答得出）", 400, code="missing_reason")

    if action == "restore" and note.state != Note.STATE_HIDDEN:
        return fail("笔记当前不是隐藏状态，无需恢复", 400, code="not_hidden")

    if action == "take_down":
        title = note.title
        note_id_pk = note.pk
        # ⚠ CASCADE：段落 / 评论 / 点赞 / 版本随行消失 ✅
        note.delete()
        _audit(request, "note.takedown", note_id=note_id_pk, name=title, reason=reason)
        return ok({"action": "take_down", "deleted": True, "reason": reason})

    note.state = Note.STATE_HIDDEN if action == "hide" else Note.STATE_ACTIVE
    note.moderation_reason = reason
    note.moderated_by = request.user
    note.moderated_at = timezone.now()
    note.save(update_fields=["state", "moderation_reason", "moderated_by", "moderated_at"])

    _audit(request, f"note.{action}", note_id=note.pk, name=note.title, reason=reason)

    return ok(
        {
            "action": action,
            "state": note.state,
            "reason": reason,
            "moderated_by": request.user.get_username(),
            "moderated_at": note.moderated_at.isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------

def _audit(request: HttpRequest, action: str, *, project_ref: str = "",
           note_id: int = 0, name: str = "", reason: str = "") -> None:
    """★★ **每次处置都写审计**（* `B208`④）⚠

    ★★ 表里的 `moderation_*` 三列只存**最近一次** ⇒* 历史全靠 `AuditLog` ⚠
    """
    admin = getattr(request, "user", None)
    AuditLog.objects.create(
        actor=admin if getattr(admin, "pk", None) else None,
        action=action,
        target_kind="Project" if project_ref else "Note",
        target_id=project_ref or str(note_id),
        detail={"name": name, "reason": reason},
    )


# ---------------------------------------------------------------------------
# 已处置列表（`B215`：补 restore 的入口）
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
@staff_only
def moderated_list(request: HttpRequest):
    """★★ `GET /api/admin/moderated/` —— ★★ **已处置列表**（* `B215`）⚠

    ⇒ `{projects:[…], notes:[…]}`（① 型）

    ## ★★ 为什么需要它（* `B208` 的洞）

    ```
    ★★ `B208` 切掉了管理员的额外读权限 ⇒* 被隐藏的项目 / 笔记对 staff 也 404
      ⇒* 「恢复」（* 仅管理员）在 UI 里**够不着** ——* 只能盲调 API ⚠
    ★★ 本端点给 staff 一个「够得着」的入口：* 只列**被隐藏**的，
      * 带理由 / 处置人 / 时间（* 恢复前知道自己在恢复什么）✅
    ```

    ⚠★ **`take_down` 的项不在列表** ——* 那是**物理删除**（* `B208`③），
      * 行都没了，* 无从列出（* 留痕在 `ProjectReview` / `AuditLog`）⚠
    ⚠★ **不分页**：* 处置是低频动作，* 隐藏项不该多；* 上限 200
      （* 超了说明处置量异常，* 那要单独看，* ⛔ 不静默翻页）✅
    """
    limit = 200

    projects = [
        {
            "project_ref": p.project_ref,
            "name": p.name,
            "owner": p.owner.get_username() if p.owner_id else "",
            "is_public": p.is_public,
            "moderation_reason": p.moderation_reason,
            "moderated_by": p.moderated_by.get_username() if p.moderated_by_id else "",
            "moderated_at": p.moderated_at.isoformat() if p.moderated_at else "",
        }
        for p in Project.objects.filter(state=Project.STATE_HIDDEN)
        .select_related("owner", "moderated_by")
        .order_by("-moderated_at")[:limit]
    ]

    notes = []
    for n in (
        Note.objects.filter(state=Note.STATE_HIDDEN)
        .select_related("created_by", "moderated_by")
        .order_by("-moderated_at")[:limit]
    ):
        project = access.project_of(n)
        notes.append(
            {
                "id": n.pk,
                "title": n.title,
                "kind": n.kind,
                "project_ref": project.project_ref if project is not None else "",
                "created_by": n.created_by.get_username() if n.created_by_id else "",
                "moderation_reason": n.moderation_reason,
                "moderated_by": n.moderated_by.get_username() if n.moderated_by_id else "",
                "moderated_at": n.moderated_at.isoformat() if n.moderated_at else "",
            }
        )

    return ok({"projects": projects, "notes": notes})
