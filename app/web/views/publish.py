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

    # ★★ **`source_path` 只对 staff 生效**（`B152`）——
    #   ⚠★ 它能被用来**读容器里的任何目录**（★ 这台机器上还跑着数据库）⇒
    #     ★ 普通用户一律**不收**（★ 他的源码应当由作业层从 `repo_url` 拉取）。
    #   ⚠ 这里**不报错、只是忽略** —— ★ 报错会暴露"有路径检查"这件事给探测者
    #     （★ 与 `_safe_source_path()` 同一口径）。
    source_path = str(body.get("source_path") or "") if user.is_staff else ""

    # ⚠★ 到这一步**已经没有"授权跳转"了**（★ `B176` ①）——
    #   ★ 直接走编排：★ 建项目 → 建许可核验流水 → 投递作业 ✅
    pub = publish_core.publish_project(
        user,
        provider=provider,
        repo_full_name=repo,
        name=str(body.get("name") or ""),
        desc=str(body.get("desc") or ""),
        source_path=source_path,
    )
    if not pub.ok:
        # ★★ 失败一律**如实返回原因**（★ `U3.9`：说清为什么 + 该怎么办）
        return fail(
            pub.message or "发布失败", 400, code=pub.reason_code or "publish_failed"
        )

    job = pub.job
    return ok(
        {
            "project_ref": pub.project_ref,
            "job_id": job.pk if job is not None else None,
            "job_state": job.state if job is not None else "",
            "message": pub.message,
            "steps": pub.steps,
        }
    )
