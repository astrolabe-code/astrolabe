"""Astrolabe · 项目标识（`project_ref`）

★ 依据 `frontend-contract.md` §2 ⑥：形态**严格** `^proj_[0-9a-f]{32}$`（固定 **37** 字符）。

⚠ 四条纪律（都写进了契约，实现必须照做）：

| # | 纪律 | 为什么 |
|---|---|---|
| **1** | ★ **形态校验在【路由转换器 + 视图层】**，❌ 不在模型层 | 模型层做会变成"到处都在校验、口径还不一致" |
| **2** | ★ **`project_ref` 不得作为授权凭证** | 它会进 URL / 日志 / 分享链接 ⇒ 泄露即越权 |
| **3** | ★ **`project_ref` 不可变**（改名**不换** ref） | 图 / 锚点 / 邻域缓存 / 公开链接全挂在它上面 |
| **4** | ★ **不承载归属信息**（不嵌用户名） | 否则泄露归属，且改名即失效 |

★ 生成方式：`proj_` + `uuid4().hex`（32 位小写 hex）
  ⇒ ✅ **天然落在纯 hex 字符集内**，不用做任何转义就满足上面的正则。

⚠ **无存量数据** ⇒ ❌ 不需要「旧格式兼容 / 宽松放行」（契约 §2 ⑥ 明确）。
"""

from __future__ import annotations

import re
import uuid

#: ★ 契约规定的唯一形态（固定 37 字符）
PROJECT_REF_RE = re.compile(r"^proj_[0-9a-f]{32}$")


def new_project_ref() -> str:
    """生成一个新的 `project_ref`。"""
    return "proj_" + uuid.uuid4().hex


def is_valid_project_ref(value: object) -> bool:
    """形态校验 —— ★ 视图层用它做二次校验（路由转换器已挡一层）。"""
    return isinstance(value, str) and bool(PROJECT_REF_RE.match(value))


# ---------------------------------------------------------------------------
# ★ 路由转换器：让「形态不对」在**路由层**就 404
# ---------------------------------------------------------------------------

class ProjectRefConverter:
    """`path("projects/<project_ref:project_ref>/…")`

    ★ 好处：形态不合法的 URL **直接 404**，❌ 不会进到视图里变成 400。
    ⚠ 与契约 §2 ⑥ 一致：**404 只表示「项目不存在 / 无权」** ——
      形态不对也走 404，**不给攻击者任何"格式对不对"的反馈**。
    """

    regex = r"proj_[0-9a-f]{32}"

    def to_python(self, value: str) -> str:
        return value

    def to_url(self, value: str) -> str:
        return value
