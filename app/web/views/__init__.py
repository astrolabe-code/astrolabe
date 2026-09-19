"""Astrolabe · ① Web 层：视图包

★ 分层（`ARCHITECTURE.md` A3）：
   视图只做【解析请求 → 调服务 / 共享内核 → 返回 envelope】，
   ❌ **不写业务逻辑**（❌ 不解析代码、❌ 不做全图遍历、❌ 不 import ② 的执行代码）。

⚠★ 下面这份清单**曾经过时**（只列了 3 个模块，而实际有 10 个）——
  ★ 现已对齐；★ 新增视图模块时**请顺手加进来**（⚠ 这份清单是"这一层有什么"的唯一索引）。

| 模块 | 职责 | 谁在用 |
|---|---|---|
| `auth` | OAuth 登录 / 注册（`U4.8` 的**唯一守门处**） | 所有人 |
| `me` | 我的资料 / 我的提交（★ 含**被驳回的原因**，`U3.8`） | 登录用户 |
| `projects` | 项目 CRUD + 解析触发 + 进度 | 项目 owner |
| `graph` | 图谱**读**接口（summary / nodes / edges / **neighbors** / graph-rev） | 任何人（公开项目） |
| ★ `curate` | ★★ 图谱**写**接口（`graph/edit/`）—— **维护者修补**（`§2.3.12`） | ★ **项目创建者自己**（`B157`） |
| `jobs_api` | 全局作业接口（列表 / 详情 / 取消） | 登录用户 |
| `publish` | 发布 / 请求建立快照 | 登录用户 |
| `review` | 审核队列（放行 / 驳回，★ **驳回必填理由**） | `is_staff` |
| `invites` | 邀请码（生成 / 核销 / 列表） | 登录用户 / `is_staff` |

⚠ **读 / 写分开是有意的**：★ `graph.py` 只管**读**（任何人可读），
  ★★ `curate.py` 只管**写**（★ 只有维护者）—— ⚠ 混在一个文件里，
  权限边界就**看不见了**，★ 而这条边界正是本平台最要紧的一条（`§2.3.11` 四通道）。
"""

from web.views import (  # noqa: F401
    auth,
    curate,
    graph,
    invites,
    jobs_api,
    me,
    projects,
    publish,
    review,
)

__all__ = [
    "auth",
    "curate",
    "graph",
    "invites",
    "jobs_api",
    "me",
    "projects",
    "publish",
    "review",
]
