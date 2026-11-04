"""★★ 后台里的「访问审计」（2026-10-25）⚠

## ★ 所有者原话（逐字）

> 「设备token，限流那个呢？**我要检测那些IP在疯狂请求token之类的，方便我以后禁掉他呀。
>   还要疯狂掉线和登陆也一样呀。**」

> 「你要有左栏的二级栏，分别放这些呀。」

> 「**我说把访问日志的二级表也加到左栏，通过折叠展开收起。**」

> 「访问审计的表格，你怎么自己写了，其他页面不是有写好的表格样式吗？」

> 「你这还是不一样呀，用户的表格有多选，这个没有呀？」

> 「**你写了两份表格结构？我的天哪，你直接复用原来的，不就完了，
>   用户怎么填的，这个就怎么填呗，写两套结构干什么？直接填数据，不就完了？**」

## ★ 最终形态

```\n左栏（unfold 折叠分组）          右侧：**一份表格结构**，只换数据\n▼ 访问审计                        {列定义} + {行数据} + {动作}\n     ① 设备令牌发放\n     ② 登录失败\n     ③ 登录 / 登出\n     ④ 被限流\n     ⑤ 封禁名单\n```\n
⚠★ **模板里只有一个 `<table>`**，五个分类共用它（`{% for t in tables %}`），
  ⛔ 不再每个分类复制一份 markdown —— 结构改一次，五处一起变 ✅
"""
from __future__ import annotations

import math

from functools import partial

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.urls import path

from core import access_audit

#: ★ (tab 键, 标题, URL name)
TABS = (
    # ⚠ 2026-11-04：「设备令牌发放」这个 tab 已删除（令牌功能整体移除，见 core/device.py）
    ("login_fail", "① 登录失败", "access-login-fail"),
    ("session", "② 登录 / 登出", "access-session"),
    ("online", "③ 在线会话", "access-online"),
    ("limited", "④ 被限流", "access-limited"),
    ("ban", "⑤ 封禁名单", "access-ban"),
)

#: ★ 每个 tab 对应哪些 Redis 计数（* 「清空本类记录」要知道清谁）⚠
TAB_KINDS = {
    "login_fail": ("login_fail",),
    "session": ("login_ok", "logout"),
    "limited": ("rate_limited",),
    "online": (),   # ⚠ 会话不是审计计数，清空走「踢下线」
    "ban": (),      # ⚠ 封禁名单有自己的解封
}

_TAB_KEYS = {key for key, _, _ in TABS}


# ---------------------------------------------------------------------------
# 表格描述（★ 只造数据，不碰 HTML）⚠
# ---------------------------------------------------------------------------


def _cell(text, label, *, mono=False, num=False, hot=False):
    """★ 一个单元格（`label` 给移动端 `data-label` 用）⚠"""
    return {"text": text, "label": label, "mono": mono, "num": num, "hot": hot}


def _build_tables(tab: str, data: dict, banned: list, q: str = "") -> tuple[list, str]:
    """★★ **所有分类共用一套表格结构**，这里只决定「填什么数据」⚠

    Returns: `(tables, lead)` —— tables 是若干张表的描述，每张：
    `{caption, action, action_label, columns, rows, empty, colspan, half}`
    """
    bk = data["by_kind"]
    totals = data["totals"]

    # ★ 顶部筛选：只按 IP 子串过滤（* 审计数据没有别的可筛字段）⚠
    def keep(rows):
        return [r for r in rows if not q or q.lower() in (r["ip"] or "").lower()] if q else rows


    if tab == "login_fail":
        return (
            [
                {
                    "action": "ban",
                    "action_label": "封禁所选 IP",
                    "columns": [
                        {"label": "IP"},
                        {"label": "尝试的用户名"},
                        {"label": "次数", "w": 90},
                    ],
                    "rows": [
                        {
                            "key": r["ip"],
                            "cells": [
                                _cell(r["ip"], "IP", mono=True),
                                _cell(r["who"] or "—", "用户名"),
                                _cell(r["count"], "次数", num=True, hot=r["count"] > 10),
                            ],
                        }
                        for r in keep(bk["login_fail"])
                    ],
                    "empty": "近两天没有登录失败。",
                }
            ],
            "撞库信号。⚠ 后端刻意不区分「账号不存在」与「密码错」，所以用户名可能是猜的。",
        )

    if tab == "limited":
        return (
            [
                {
                    "action": "ban",
                    "action_label": "封禁所选 IP",
                    "columns": [
                        {"label": "IP"},
                        {"label": "身份"},
                        {"label": "次数", "w": 90},
                    ],
                    "rows": [
                        {
                            "key": r["ip"],
                            "cells": [
                                _cell(r["ip"], "IP", mono=True),
                                _cell(r["who"] or "anon", "身份"),
                                _cell(r["count"], "次数", num=True),
                            ],
                        }
                        for r in keep(bk["rate_limited"])
                    ],
                    "empty": "近两天没有被限流的请求。",
                }
            ],
            "搜索刷得太快被挡。身份 anon = 连设备令牌都没带（多半是脚本）。",
        )

    if tab == "online":
        from core import admin_sessions

        rows, orphans = admin_sessions.online_sessions()
        # ★ 顶部筛选：IP 或**用户名**都能筛（* 从用户详情页跳过来时带的是用户名）⚠
        if q:
            needle = q.lower()
            rows = [
                r
                for r in rows
                if needle in (r["ip"] or "").lower() or needle in (r["username"] or "").lower()
            ]
        return (
            [
                {
                    "action": "kick",
                    "action_label": "强制下线",
                    "columns": [
                        {"label": "用户"},
                        {"label": "来源 IP", "w": 150},
                        {"label": "设备"},
                        {"label": "登录时间", "w": 165},
                        {"label": "到期", "w": 165},
                        {"label": "剩余", "w": 90},
                    ],
                    "rows": [
                        {
                            "key": r["key"],
                            "cells": [
                                _cell(r["username"], "用户"),
                                _cell(r["ip"] or "—", "来源 IP", mono=True),
                                _cell(r["device"], "设备"),
                                _cell(r["login_at"].replace("T", " ")[:16] or "—", "登录时间"),
                                _cell(timezone.localtime(r["expire_date"]).strftime("%Y-%m-%d %H:%M"), "到期"),
                                _cell(r["left"], "剩余"),
                            ],
                        }
                        for r in rows
                    ],
                    "empty": "当前没有在线用户。",
                }
            ],
            "★ 这是 Django 自己的 session 表 —— 谁现在登录着，以它为准。"
            "★ 上面的框可以按用户名或 IP 筛。"
            "⚠ 会话标识只显示前 8 位（完整 key 等于对方的登录凭证）。"
            + (f"　⚠ 另有 {orphans} 个无效会话（用户已删除），可在本页清理。" if orphans else ""),
        )

    if tab == "session":
        def one(title: str, rows, total: int):
            return {
                "caption": f"{title} · 共 {total} 次",
                "half": True,
                "columns": [
                    {"label": "IP"},
                    {"label": "用户"},
                    {"label": "次数", "w": 70},
                ],
                "rows": [
                    {
                        "key": f"{r['ip']}-{r['who']}",
                        "cells": [
                            _cell(r["ip"], "IP", mono=True),
                            _cell(r["who"], "用户"),
                            _cell(r["count"], "次数", num=True),
                        ],
                    }
                    for r in rows[:20]
                ],
                "empty": "无",
            }

        return (
            [
                one("登录成功", keep(bk["login_ok"]), totals["login_ok"]),
                one("登出", keep(bk["logout"]), totals["logout"]),
            ],
            "登录多、登出也多 ⇒ 反复掉线；只有登出没有登录 ⇒ 会话被踢或过期。",
        )

    # tab == "ban"
    return (
        [
            {
                "action": "unban",
                "action_label": "解封所选 IP",
                "columns": [
                    {"label": "IP"},
                    {"label": "操作人"},
                    {"label": "到期", "w": 110},
                ],
                "rows": [
                    {
                        "key": r["ip"],
                        "cells": [
                            _cell(r["ip"], "IP", mono=True),
                            _cell(r["by"] or "—", "操作人"),
                            _cell(r["until"] or "永久", "到期"),
                        ],
                    }
                    for r in banned
                ],
                "empty": "（空）",
            }
        ],
        "被封的 IP 在请求入口直接 403。⚠ 回环与容器网段不可封（防自锁）。",
    )


# ---------------------------------------------------------------------------
# 视图
# ---------------------------------------------------------------------------


def access_audit_view(request, tab: str = "device"):
    """★ 单个分类（左栏由 unfold 提供，本视图只管右侧内容）⚠"""
    if tab not in _TAB_KEYS:
        tab = "device"

    if request.method == "POST":
        # ★ 批量：勾选多个 `ips`（与 changelist 的「勾选 + 动作栏」同一套交互）⚠
        action = (request.POST.get("action") or "").strip()
        ips = [ip.strip() for ip in request.POST.getlist("ips") if ip.strip()]
        single = (request.POST.get("ip") or "").strip()
        if single and single not in ips:
            ips.append(single)

        # ★★ 清空本类记录（* 所有者：「这些数据如何删除呢？那不能一直堆着」）⚠
        if action == "clear":
            kinds = TAB_KINDS.get(tab) or ()
            if not kinds:
                messages.warning(request, "这个分类没有可清空的审计记录。")
            else:
                n = access_audit.clear(kinds)
                from core.models import AuditLog

                AuditLog.objects.create(
                    actor=request.user,
                    action="audit.clear",
                    target_kind="audit",
                    target_id=",".join(kinds),
                    detail={"deleted": n, "by": request.user.get_username()},
                )
                messages.success(request, f"已清空本类记录（{n} 条）")
            return HttpResponseRedirect(request.path)

        # ★★ 清理无效会话（过期 + 用户已删除的孤儿）⚠
        if action == "purge":
            from core import admin_sessions

            expired, orphans = admin_sessions.purge_dead()
            messages.success(request, f"已清理：过期 {expired} 个、孤儿 {orphans} 个")
            return HttpResponseRedirect(request.path)

        # ★★ 强制下线（* 所有者：「我在上面地方查看那些用户在线呢？」）⚠
        if action == "kick" and ips:
            from core import admin_sessions

            n = admin_sessions.kick(ips)
            from core.models import AuditLog

            AuditLog.objects.create(
                actor=request.user,
                action="session.kick",
                target_kind="session",
                target_id=",".join(k[:8] for k in ips[:10]),
                detail={"count": n, "by": request.user.get_username()},
            )
            messages.success(request, f"已强制下线 {n} 个会话")
            return HttpResponseRedirect(request.path)

        # ★ 封禁时长（0 = 永久）⚠
        try:
            ban_seconds = max(0, int(request.POST.get("ban_seconds") or 0))
        except ValueError:
            ban_seconds = 0

        if action in ("ban", "unban") and ips:
            done, skipped = 0, []
            for ip in ips:
                if action == "ban":
                    if access_audit.ban(ip, seconds=ban_seconds, by=request.user.get_username()):
                        done += 1
                        from core.models import AuditLog  # ★ 管理动作必留痕 ⚠

                        AuditLog.objects.create(
                            actor=request.user,
                            action="ip.ban",
                            target_kind="ip",
                            target_id=ip,
                            detail={"by": request.user.get_username()},
                        )
                    else:
                        skipped.append(ip)
                else:
                    access_audit.unban(ip)
                    done += 1

            if done:
                if action == "ban" and ban_seconds:
                    span = (
                        f"{ban_seconds // 86400} 天"
                        if ban_seconds >= 86400
                        else f"{ban_seconds // 3600} 小时"
                        if ban_seconds >= 3600
                        else f"{ban_seconds // 60} 分钟"
                    )
                    messages.success(request, f"已封禁 {done} 个地址（{span}）")
                else:
                    # ★ 措辞统一以「已封禁」开头（* 便于阅读，也便于断言）⚠
                    suffix = "（永久）" if action == "ban" else ""
                    messages.success(
                        request,
                        f"已{'封禁' if action == 'ban' else '解封'} {done} 个地址{suffix}",
                    )
            if skipped:
                messages.error(
                    request,
                    f"{len(skipped)} 个地址被拒绝（回环 / 内网，封了会把自己锁在门外）："
                    + "、".join(skipped[:5]),
                )
        else:
            messages.warning(request, "没有勾选任何地址，或未选择动作。")
        return HttpResponseRedirect(request.path)

    q = (request.GET.get("q") or "").strip()
    # ★ 分页（* 所有者：「要有翻页按钮呀，不然列表一长要下滑很久」）⚠
    try:
        page = max(1, int(request.GET.get("page") or 1))
    except ValueError:
        page = 1
    per_page = 20
    data = access_audit.summary(days=2)
    banned = access_audit.banned_list()
    tables, lead = _build_tables(tab, data, banned, q)

    # ★ colspan / 总行数 / 行是否可封，在这里算好，模板里不再做判断 ⚠
    for t in tables:
        t["colspan"] = len(t["columns"]) + (1 if t.get("action") else 0)
        t["total"] = len(t["rows"])
        # ★ 每张表独立分页（* 登录/登出页有两张表，各自翻）⚠
        total = len(t["rows"])
        t["pages"] = max(1, math.ceil(total / per_page))
        t["page"] = min(page, t["pages"])
        start = (t["page"] - 1) * per_page
        t["rows"] = t["rows"][start : start + per_page]
        for row in t["rows"]:
            row["bannable"] = access_audit.is_bannable(row["key"])
        # ★ 动作下拉的选项（* 除主动作外，再给一个「清空本类记录」）⚠
        if t.get("action"):
            t["actions"] = [{"value": t["action"], "label": t["action_label"]}]
            if TAB_KINDS.get(tab):
                t["actions"].append({"value": "clear", "label": "清空本类记录（不可恢复）"})
            if tab == "online":
                t["actions"].append({"value": "purge", "label": "清理无效会话（过期 / 用户已删）"})
        # ★ 一行都封不了 ⇒ 给用户一句人话（* 别让人对着灰按钮猜）⚠
        t["all_blocked"] = (
            bool(t["rows"]) and not any(r["bannable"] for r in t["rows"])
        )

    context = {
        **admin.site.each_context(request),
        "title": "访问审计",
        "tab": tab,
        "lead": lead,
        "tables": tables,
        "days": data["days"],
        "q": q,
        # ★ 在线会话 / 封禁名单不是 Redis 计数 ⇒ 不显示「统计窗口」那行 ⚠
        "show_window": tab in ("device", "login_fail", "session", "limited"),
    }
    return TemplateResponse(request, "admin/access_audit.html", context)


def register_access_url() -> None:
    """★ 挂 6 个入口：总入口 + 五个分类（每个都要独立 URL，侧栏才能高亮）⚠"""
    original = admin.site.get_urls

    def get_urls():
        custom = [
            path("access/", admin.site.admin_view(access_audit_view), name="access-audit"),
        ]
        for key, _label, name in TABS:
            custom.append(
                path(
                    f"access/{key.replace('_', '-')}/",
                    admin.site.admin_view(partial(access_audit_view, tab=key)),
                    name=name,
                )
            )
        return custom + original()

    admin.site.get_urls = get_urls
