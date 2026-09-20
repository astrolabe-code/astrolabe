"""Astrolabe · ① Web 层：**邀请**（`U4.7`）

★ 依据 `USERS-AND-AUTH.md` `U4.7`（★ **邀请制 = 连带责任**）。

| 方法 | 路径 | 谁 |
|---|---|---|
| `POST` | `/api/invites/check/` | ★★ **匿名**（`U4.8` 流程第 ② 步：注册前就得能校验） |
| `GET` / `POST` | `/api/invites/` | ★ **管理员**（列表 / 生成） |
| `POST` | `/api/invites/<token>/revoke/` | ★ 管理员（作废） |

---

# ⚠★ 为什么 `check` 必须**匿名可用**

★ `U4.8` 的流程是：**先填邀请码 → 再跳 GitHub 授权**。

⚠ 如果 `check` 要求登录，就成了死循环：
**没账号的人要先登录才能校验"我能注册吗"** —— ★ 而他正是**因为没账号**才来校验的。

★ 安全性上也没问题：★ `check` **只读、无副作用**（★ **不消耗**邀请码 —— `U4.8` 纪律 1），
⚠ 而**暴力猜 token** 在 256 bit 熵面前**不可能**（`U4.7`：这也是不用短码的理由之一）。
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from core import invites
from web.http import fail, ok, read_json
from web.permissions import staff_only

#: ★ `max_uses` 的合理上限 —— ⚠ 防止管理员手滑写成 100000（那等于公开注册）
MAX_USES_CAP = 200

#: ★ 有效期上限（10 年）—— ⚠ 防手滑写成 36500（那等于"永不过期"，正是 `U4.7` 规则 2 要防的）
MAX_VALID_DAYS = 3650


def _int_in_range(body: dict, key: str, low: int, high: int, default: int) -> tuple[int | None, str]:
    """★ 取一个**在范围内**的整数 —— ★★ **非法就报错，❌ 不钳制**。

    ⚠★ 为什么**不能**钳制（这是被实测逼出来的）：

    ★ 原先写成 `max(low, min(got, high))` ⇒ ⚠ `valid_days=0` 被**悄悄改成 1**
      ⇒ ★ 管理员可能想表达"永不过期"（我们**明确禁止**，见 `create_invite`），
      ★ 结果得到一个「**明天就过期**」的邀请码 —— ⚠ **静默地做错了事**，
      比直接报错**危险得多**（★ 因为它看起来"成功了"）。

    ★ 这与本项目一路的纪律一致：★ **让错误在开发期/输入处暴露**（`reject()`、`create_invite` 都是这个思路）。
    """
    if key not in body or body[key] in (None, ""):
        return default, ""
    try:
        got = int(body[key])
    except (TypeError, ValueError):
        return None, f"{key} 必须是整数"
    if not (low <= got <= high):
        return None, f"{key} 必须在 {low} ~ {high} 之间"
    return got, ""


def _invite_json(inv) -> dict:
    """★ 邀请的投影（⚠ 含 `token` —— 因为**管理员本来就要把它发出去**）。"""
    return {
        "token": inv.token,
        "invited_by": inv.created_by_name,
        "used": inv.used_count,
        "max_uses": inv.max_uses,
        "usable": inv.is_usable(),
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "revoked": inv.is_revoked,
        "note": inv.note,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        # ★ 直接给出可分享的链接（★ 前端可以照用，也可以自己拼）
        "url": _invite_url(inv.token),
    }


def _invite_url(token: str) -> str:
    base = getattr(settings, "ASTROLABE_SPA_URL", "").rstrip("/")
    return f"{base}/invite/{token}" if base else f"/invite/{token}"


# ===========================================================================
# ★★ 预检（匿名）
# ===========================================================================


@require_http_methods(["POST"])
def check(request: HttpRequest) -> JsonResponse:
    """★ 预检一个邀请码 —— ★★ **匿名可用**（见模块文档）。"""
    body = read_json(request)
    token = str(body.get("token") or request.GET.get("token") or "").strip()
    c = invites.check(token)
    return ok(
        {
            "ok": c.ok,
            # ★ 失败时**说清原因**（★ 同 `U3.9`：含糊的提示会让用户反复重试）
            "message": c.message,
            # ★ 成功时告诉他是**谁**邀请的（★ 连带责任对用户也是可见的）
            "invited_by": c.invited_by_name if c.ok else "",
        }
    )


# ===========================================================================
# 列表 / 生成（管理员）
# ===========================================================================


@require_http_methods(["GET", "POST"])
@staff_only
def collection(request: HttpRequest) -> JsonResponse:
    """`GET` 列表 / `POST` 生成。"""
    if request.method == "POST":
        return _create(request)

    # ⚠ `limit` 是**只读参数**，钳制它是安全的（❌ 不会"静默改变用户的意图"：
    #   ★ 用户要的是"尽量多给我几条"，给 200 条完全符合预期）
    limit, _ = _int_in_range({"limit": request.GET.get("limit")}, "limit", 1, 200, 50)
    limit = limit or 50

    from core.models import Invite

    qs = Invite.objects.order_by("-created_at")[:limit]
    # ⚠★★ `B171` 修：这里原本写的是 `body_qs` —— ★★ 那个名字**在这份文件里从未定义过** ⚠
    #   ⇒ 后果：★★ **任何 `GET /api/invites/` 都必然 500**（★ 一个躺了很久的 bug）
    #   ★ 本意显然是读【查询参数】`?usable=1` ⇒ ★ 改成 `request.GET` ✅
    #
    #   ⚠ 为什么它能躺这么久：★ `smoke_auth_api.py` 只测了"注册门禁那几个开关"，
    #     ★ **从没打过 `GET /api/invites/` 这条列表接口** ⚠
    #   ⇒ ★★ 教训：★ **"接口已实现"≠"接口被验证过"** —— ★ 本条的登记里我（AI）
    #      **凭"代码看起来完备"就断言了"后端完全就绪"**，⚠ 那是不该的 ⚠
    if request.GET.get("usable") == "1":
        qs = [i for i in qs if i.is_usable()]
    return ok({"invites": [_invite_json(i) for i in qs]})


def _create(request: HttpRequest) -> JsonResponse:
    body = read_json(request)

    max_uses, err = _int_in_range(body, "max_uses", 1, MAX_USES_CAP, 1)
    if err:
        return fail(err, 400, code="bad_max_uses")
    # ★★ 有效期**不允许 <= 0** —— ⚠ 见 `_int_in_range` 的说明
    #   （★ 而且 `create_invite` 自己也会 raise，这里是**更早、更清楚**的一道）
    valid_days, err = _int_in_range(body, "valid_days", 1, MAX_VALID_DAYS, 7)
    if err:
        return fail(err, 400, code="bad_valid_days")

    try:
        inv = invites.create_invite(
            request.user,
            max_uses=max_uses,
            valid_days=valid_days,
            note=str(body.get("note") or "")[:200],
        )
    except ValueError as exc:
        # ⚠ `create_invite` 对非法有效期**直接 raise**（★ 不静默变成"永不过期"）——
        #   ★ 这里把它翻译成 400，❌ 不是 500
        return fail(str(exc), 400, code="bad_valid_days")
    return ok(_invite_json(inv), status=201)


# ===========================================================================
# 作废（管理员）
# ===========================================================================


@require_http_methods(["POST"])
@staff_only
def revoke(request: HttpRequest, token: str) -> JsonResponse:
    """★ 作废一个邀请（★ 还没用完也能收回 —— 比如发现它被转发了）。"""
    from core.models import Invite

    inv = Invite.objects.filter(token=token).first()
    if inv is None:
        return fail("邀请不存在", 404, code="not_found")
    invites.revoke(inv, by=request.user)
    return ok({"revoked": True, "token": inv.token})
