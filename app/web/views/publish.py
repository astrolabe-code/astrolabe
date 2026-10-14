"""Astrolabe · ① Web 层：**发布**（★ `B176` ① 之后 —— **一步到底**）

★ 依据 `USERS-AND-AUTH.md` `U3.1` · `B149`（发布编排）· ★★ `B176` ①（**归属验证退役**）。

---

# ★★★ 为什么现在是【一个 POST 搞定】（★ 这一段是本模块的存在理由）

⚠★ `B176` ① 之前，发布是**两步** —— 原因只有一个：
  ★ 平台要拿 `access_token` 去**当场校验仓库归属**，★ 而那要求用户**先去第三方授权一次** ⚠
  ⇒ ★ 于是「发布」这个动作**被迫搬进了 OAuth 回调**里（★ 因为只有那一刻才有 token）。

★★★ **所有者裁定**（原话）：

> 「**我以前说用 github 验证库是不是属于本人，我觉得不行，删掉这个，有风险。
> 现在改为，只拉下来解析，解析之后就删掉**」

★ 归属校验一退役 ⇒ ★ **发布不再需要任何第三方授权** ⇒
  ★★ 这一个 `POST` 就能**建项目 + 投递解析作业** ✅

```
POST /api/projects/publish/start/     ← 就是本模块
   ⇒ 建 Project（含许可核验流水）+ 投递 parse 作业
   ⇒ ★ 就地返回 { project_ref, job_id, job_state }
   ⚠★ 不再有 `authorize_url` —— 也就不再有"整页跳第三方"这一步 ✅
```

⚠★ **命名说明**：路由仍叫 `publish/start/`（★ 前端在用，⚠ 改路径是 `2b` 批次的事）——
  ★★ 但**语义已经变了**：★ 它是「**建项目并开始拉取**」，❌ 不是「发起授权」⚠

★ 为什么退役反而更安全（★ 论证在 `docs/backend-decisions.md` 的 `B176` ⑥）：
  ★★ 旧方案付出了「**承认知道风险**」的代价，★ **却没换来真正的防护** ⚠
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from core import invites, oauth
from core import publish as publish_core
from web import permissions
from web.http import fail, ok, read_json


def validate_repo(raw: str) -> tuple[str, str]:
    """★ 校验 `owner/repo` —— 返回 `(仓库全名, 错误信息)`（⚠ 错误信息为空表示通过）。"""
    full = (raw or "").strip().strip("/")
    if not full:
        return "", "请填写要发布的仓库（格式 owner/repo）"
    if full.count("/") != 1 or any(seg in ("", ".", "..") for seg in full.split("/")):
        return "", "仓库格式应为 owner/repo，请检查后重试"
    return full, ""


@require_http_methods(["POST"])
def start(request: HttpRequest) -> JsonResponse:
    """★★ **建项目 + 投递解析作业**（★ `B176` ①：**不再要求任何第三方授权**）。

    ⚠★ 与 `B176` ① 之前相比，删掉的是中间那一跳：
      ★ 以前要 `oauth.start(action=ACTION_PUBLISH)` ⇒ 返回授权 URL ⇒ 用户跳走 ⇒
        ★ 回调里才真正建项目 ⚠
      ★★ 现在**直接建** ✅
    """
    user = permissions.current_user(request)
    if user is None:
        return fail("请先登录", 401, code="unauthenticated")

    gate = invites.registration_gate()
    if gate.paused:
        return fail(gate.message or "站点正在维护", 503, code="paused")

    body = read_json(request)
    provider = str(body.get("provider") or "").strip().lower()
    if provider not in oauth.PROVIDERS:
        return fail("provider 必须是 github 或 gitee", 400, code="invalid_provider")

    repo, err = validate_repo(str(body.get("repo") or ""))
    if err:
        return fail(err, 400, code="bad_repo")

    # ⚠★★ 2026-10-14（`B184`）：**不再收 `source_path`** ⚠
    #   ★ 它曾是「staff 指一个容器里的目录」的调试口子（`B152`）——
    #   ★★ 而它让「基图的身份」变得**不可验证** ⇒ ★ 那是**攻击缺口** ⚠

    # ⚠★ 到这一步**已经没有"授权跳转"了**（★ `B176` ①）——
    #   ★ 直接走编排：★ 建项目 → 建许可核验流水 → 投递作业 ✅
    pub = publish_core.publish_project(
        user,
        provider=provider,
        repo_full_name=repo,
        name=str(body.get("name") or ""),
        desc=str(body.get("desc") or ""),
        # ⚠★★ `B182`：**前端已经算好的 commit sha** ⚠
        #   ★★ 所有者原话：「**这个过程应该发生在前端，不是用我服务器的IP地址查询的，
        #     只有拉源码，才是我服务器做的吧？**」
        #   · ★ 有它 ⇒ ★★ 服务端【一次 GitHub API 都不发】✅
        #     （★ 未认证配额是每 IP 每小时 60 次，★ 由服务端扛 ⇒ 所有人一起被挡）⚠
        #   · ★ 没有 ⇒ ★ 服务端自己解析（★ 兜底，★ 老客户端 / 前端失败时不坏）✅
        #   ⚠★ 形态校验在 `core/publish.py::dispatch_parse` 里做（★ 不像就当没给）⚠
        sha=str(body.get("sha") or ""),
        # ⚠★ 2026-10-13：「新建项目」改走本端点之后，这两个字段也要能落下来 ⚠
        #   · ★ `ref`      —— ★ 前端那个「commit（可选）」输入框（★ 分支 / tag）⚠
        #   · ★ `is_public` —— ★ 前端那个「创建后立即公开」勾选框 ⚠
        #   ★★ 不收它们 ⇒ ★ 那两个输入框就变成**摆设**了 ⚠
        ref=str(body.get("ref") or ""),
        # ★ 缺省 True = 保持原来的政策（★ 发布即公开页面，U2.1）✅
        is_public=bool(body.get("is_public", True)),
    )
    if not pub.ok:
        # ★★ 失败一律**如实返回原因**（★ `U3.9`：说清为什么 + 该怎么办）
        return fail(
            pub.message or "发布失败", 400, code=pub.reason_code or "publish_failed"
        )

    job = pub.job
    # ⚠★ `B179`：**复用了现成基图**时 `job` 是 `None` —— ★ 而这是**成功** ⚠
    #   ★★ 所以必须把 `reused` 一并告诉前端，★ 否则它看到 `job_id: null` 会以为失败了 ⚠
    #   ★（★ 所有者原话：「**有同样的，就直接返回，不拉取，不解析，还快**」）
    return ok(
        {
            "project_ref": pub.project_ref,
            "job_id": job.pk if job is not None else None,
            "job_state": job.state if job is not None else ("reused" if pub.reused else ""),
            # ★★ `B179`：两种"结局"的分界 —— ★ 前端据此给不同文案 ⚠
            "reused": pub.reused,
            # ★ 复用了哪一版（★ 前端可显示"对应 commit ea42736…"）✅
            "sha": pub.reused_sha or (job.payload.get("sha", "") if job is not None else ""),
            "message": pub.message,
            "steps": pub.steps,
        }
    )
