"""Astrolabe · ① Web 层路由

★ 契约：新后端照 `frontend-contract.md` §1–§13 实现，前端几乎零改动。

★ 分层纪律（`ARCHITECTURE.md` A3）：
   ① Web 层 ❌ **不得 import ② 的执行代码**（`run_worker` / `jobs.tasks`）；
   ✅ 只允许 `jobs/dispatch.py`（**投递**）—— 口径见 `dispatch.py` 顶部。

★★ `project_ref` 用**路由转换器**（`core/refs.py`）——
  形态不合法的 URL **直接 404**，❌ 进不到视图里。
"""

from django.urls import path, register_converter

from core.refs import ProjectRefConverter
from web.views import (
    admin,
    auth,
    collaborators,
    comments,
    curate,
    graph,
    invites,
    jobs_api,
    likes,
    me,
    moderate,
    notes,
    projects,
    publish,
    reading_path,
    review,
    user_space,
    settings,
    site_config,
)

# ⚠ 必须在 URL 解析之前注册
register_converter(ProjectRefConverter, "project_ref")

app_name = "web"

urlpatterns = [
    # ------------------------------------------------------------ 认证（U4）
    # ★★ `U4`：**本站没有用户名密码登录**（`U4.2` 四条理由）——
    #   登录 = GitHub / Gitee 授权；⭐ 契约 §12 里那个 `POST /api/auth/login/`
    #   （用户名密码）**已被 `B143` 标注为「一期不实现」**。
    # ⚠ 顺序有讲究：`<str:provider>/start/` 必须排在具体路径之后，
    #   否则未来新增 `/api/auth/tokens/` 这类固定路径会被 `<str:provider>` 吃掉。
    # ★★★ `B170`：**用户名 + 密码**（★ `U4.9`）——
    #   ⚠★ **必须排在 `<str:provider>/…` 之前**：★ 否则 `login` / `register` 会被
    #      `<str:provider>` 吃掉（★ 被当成一个 provider 名去解析）⚠（★ 同下面那条提醒）
    #   ★ 两者都 `csrf_exempt`（★ 见 `views/auth.py`：★ 此刻**还没有 token**）
    path("auth/login/", auth.login, name="auth-login"),
    path("auth/register/", auth.register, name="auth-register"),
    path("auth/providers/", auth.providers, name="auth-providers"),
    # ★★ 前台可读的站点配置（白名单 · `D120`）⚠
    path("site-config/", site_config.site_config, name="site-config"),
    path("auth/me/", auth.me, name="auth-me"),
    path("auth/logout/", auth.logout, name="auth-logout"),
    path("auth/logout-all/", auth.logout_all, name="auth-logout-all"),
    path("auth/tokens/", auth.tokens, name="auth-tokens"),
    path("auth/<str:provider>/start/", auth.start, name="auth-start"),
    # ★ 回调是**浏览器直接跳进来**的（所以是 GET，⚠ 不受 Bearer 中间件影响）
    path("auth/<str:provider>/callback/", auth.callback, name="auth-callback"),

    # ------------------------------------------------------------ 邀请（U4.7）
    # ★★ `check` **匿名可用** —— ★ `U4.8` 流程第 ② 步（没账号的人要先能校验邀请码）
    path("invites/check/", invites.check, name="invite-check"),
    path("invites/", invites.collection, name="invite-collection"),
    path("invites/<str:token>/revoke/", invites.revoke, name="invite-revoke"),

    # ------------------------------------------------------------ 我的（U3.8 / U3.9）
    path("me/upload/", me.upload, name="me-upload"),
    # ★★ 存储空间（B152）—— ★ VIP 的"空间更大"在这里看得见
    path("me/storage/", me.storage_view, name="me-storage"),
    path("me/submissions/", me.submissions, name="me-submissions"),
    path("me/overview/", me.overview, name="me-overview"),

    # ------------------------------------------------------------ 管理员：审核（U3.7）
    path("admin/reviews/", review.queue, name="admin-reviews"),
    path("admin/reviews/<int:review_id>/approve/", review.approve, name="admin-review-approve"),
    path("admin/reviews/<int:review_id>/reject/", review.reject, name="admin-review-reject"),

    # ------------------------------------------------------ 管理员：参数中心（U2.4 / U2.5）
    # ★★ `B172`：**注册 / 邀请的开关**（★ 用户要的"管理页要有打开和关闭注册以及邀请的按钮"）。
    # ⚠★ 权限分两层（★ `U2.4`）：★ 本端点只要 `staff`，★ 而【门禁类参数】的写入
    #   **由 `appsettings.set_value()` 自己拦 superuser**（★ 见 `views/admin.py` 文件头）。
    path("admin/settings/", admin.settings_view, name="admin-settings"),
    # ------------------------------------------------ 管理处置（B208：管理员唯一的权力）
    # ★★ 隐藏 = 仅作者/owner 可见（别人直链也不可访问）；
    #   ★★ 下架 = 物理删除数据（删前留痕）；
    #   ★★ 恢复 = 仅 hidden→active 且仅管理员（非管理员不可恢复）⚠
    # ⚠★ 整条 @staff_only ⇒* 协作者 / 普通用户一律 403 ✅
    path(
        "admin/projects/<project_ref:project_ref>/moderate/",
        moderate.moderate_project,
        name="admin-moderate-project",
    ),
    path(
        "admin/notes/<int:note_id>/moderate/",
        moderate.moderate_note,
        name="admin-moderate-note",
    ),
    # ★★ `B215`：**已处置列表**（staff）——* 被隐藏的项目 / 笔记，* 从这儿恢复 ⚠
    #   ⚠ `take_down`（物理删）的不在列表（* 行都没了，* 无从列出）✅
    path("admin/moderated/", moderate.moderated_list, name="admin-moderated"),

    # ------------------------------------------------------------ 项目
    path("projects/", projects.collection, name="project-collection"),
    # ★★ 发布 —— 只负责"发起授权"（★ 真正的发布在 OAuth 回调里，见 `views/publish.py`）
    # ⚠ 位置无所谓：`<project_ref>` 转换器只认 `proj_[0-9a-f]{32}`，不会被 "publish" 命中
    path("projects/publish/start/", publish.start, name="project-publish-start"),
    path(
        "projects/<project_ref:project_ref>/",
        projects.detail,
        name="project-detail",
    ),
    # ------------------------------------------------------------ 解析
    # ★ 新设计的入口（`B109`：源码只能服务端拉取 ⇒ ❌ 没有 zip 上传这条路）
    # ★★★ `B169`：**拉取代码** —— ★ 原名 `parse/`，改名是因为「parse」这个字
    #   ⚠ **正是那个错的遗迹**：★ 它暗示"可以反复解析"，★ 而这个动作的真实语义是「**拉取**」⚠
    # ⚠★ 注意语义：★ 本端点**只负责发起授权**（★ 真正的"拉取 + 解析"在 OAuth 回调里，
    #   见 `views/auth.py::_run_fetch()`）—— ★ 与 `publish/start/` 同构 ✅
    path(
        "projects/<project_ref:project_ref>/fetch/",
        projects.start_fetch,
        name="project-fetch",
    ),
    path(
        "projects/<project_ref:project_ref>/progress/",
        projects.progress,
        name="project-progress",
    ),
    path(
        "projects/<project_ref:project_ref>/jobs/",
        jobs_api.project_jobs,
        name="project-jobs",
    ),
    # ★★ `B230`：**图修补元数据**（* 公开只读；* 前端表单的唯一来源）⚠
    path(
        "graph/meta/",
        graph.meta,
        name="graph-meta",
    ),
    # ------------------------------------------------------------ 图谱
    path(
        "projects/<project_ref:project_ref>/graph/summary/",
        graph.summary,
        name="graph-summary",
    ),
    path(
        "projects/<project_ref:project_ref>/graph/nodes/",
        graph.nodes,
        name="graph-nodes",
    ),
    # ⚠ 契约原文是 `<path:uid>` —— ★ 我们改为 `<int:vid>`（B117：uid 允许重复）
    path(
        "projects/<project_ref:project_ref>/graph/nodes/<int:vid>/",
        graph.node_detail,
        name="graph-node-detail",
    ),
    path(
        "projects/<project_ref:project_ref>/graph/edges/",
        graph.edges,
        name="graph-edges",
    ),
    # ------------------------ ★★★ 修改（**第二份数据** —— `B179` / `B180`）
    # ★★★ 所有者原话：「**基图与用户修改存在不同模型里，请求时，直接请求这两份数据，
    #   前端负责整合**」⚠
    # ⇒ ★★ 上面 `nodes` / `edges` 发的是【基图那一份】；
    #   ★ 本路由发的是【修改那一份】—— ★★ **服务端【不做】合并** ⚠
    path(
        "projects/<project_ref:project_ref>/graph/patches/",
        graph.patches,
        name="graph-patches",
    ),
    # ------------------------------------------------------ ★★ 图修补（写，§2.3.12 通道 ②）
    # ★★★ **维护者手工修补** —— 路径照 `frontend-contract.md` §2 的既定口径
    #   （`POST …/graph/edit/` + `{base_graph_rev?, reason, changes:[…]}`），❌ 不另起一套。
    # ⚠★ **谁能用**：★ **项目创建者自己**（★ 不是管理员代劳，`B157`）——
    #   判定在 `graph/curate.py::can_curate()`，★ 越权**统一 404**（与"不存在"不可区分）。
    path(
        "projects/<project_ref:project_ref>/graph/edit/",
        curate.edit,
        name="graph-edit",
    ),
    # ★ 看一眼"哪些是人补的"（`origin=manual`）—— ★ 支撑 `§2.3.12` 规则 2 的**视觉标记**
    path(
        "projects/<project_ref:project_ref>/graph/manual/",
        curate.manual,
        name="graph-manual",
    ),
    # ★★ 多跳邻域 —— 本平台的立身之本
    path(
        "projects/<project_ref:project_ref>/graph/neighbors/",
        graph.neighbors,
        name="graph-neighbors",
    ),
    path(
        "projects/<project_ref:project_ref>/graph-rev/",
        graph.rev,
        name="graph-rev",
    ),
    # ★★ `B234`：**学习路径**（* 作者指定的节点展示顺序）⚠
    path(
        "projects/<project_ref:project_ref>/reading-path/",
        reading_path.collection,
        name="reading-path",
    ),
    # ★★ `B231`：**导出所选笔记**（* 打包成带签名的 `.astrolobe-backup`）⚠
    path(
        "me/deleted/export/",
        notes.export_deleted,
        name="deleted-export",
    ),
    # ---------------------------------------------------------- 笔记（B187）
    # ⚠★ 列表 / 新建挂在【项目】下（* 一篇笔记属于一个项目 ✅）
    path(
        "projects/<project_ref:project_ref>/notes/",
        notes.collection,
        name="note-list",
    ),
    # ★★ 关键词联想（* 只提示关键词，⛔ 不直接进详情）⚠
    path("search/suggest/", notes.suggest, name="search-suggest"),
    # ★★ 批量改公开 / 私有（* 所有者：用户排除若干篇，其余批量改）⚠
    path(
        "projects/<project_ref:project_ref>/notes/batch-visibility/",
        notes.batch_visibility,
        name="note-batch-visibility",
    ),
    # ⚠★ 单篇【不挂项目】—— ★ 笔记自己有 id，* 且权限在视图里判 ✅
    #   · · ★ 挂在项目下会逼着 URL 里带 ref ⇒ ★ 而 ref 与笔记是**多对一** ⚠
    #     （* 一篇笔记只属于一个项目，* 但 URL 不必 redundant 地再写一遍）⚠
    # ★★ `B231`：**从导出包恢复笔记**（* 先验签再解包）⚠
    path("notes/import/", notes.import_notes, name="note-import"),
    # ★★ 全局笔记搜索（* 首页搜索框：* 标题 + 正文）⚠
    path("notes/search/", notes.search, name="note-search"),
    path("notes/<str:note_ref>/", notes.detail, name="note-detail"),
    # ------------------------------------------------------------ 评论（B201/B203）
    # ★★ 章评 + 段评【同表】；* `anchor_kind` **创建时定死**（* B203④）⚠
    # ★★ 楼中楼：* 默认只给顶层，* `?parent=<id>` 拉某条的回复（* B201②）⚠
    path(
        "notes/<str:note_ref>/comments/",
        comments.collection,
        name="note-comments",
    ),
    # ⚠★ 单条【不挂笔记】—— ★ 与 `notes/<id>/` 同构：* id 自己唯一 ✅
    # ★★ **只有 DELETE**（* 评论只删不改，* B201③）—— * 且是**软删** ⚠
    path("comments/<int:comment_id>/", comments.detail, name="comment-detail"),
    # ★★ 评论赞（* 每条评论旁边的赞按钮）⚠
    path("comments/<int:comment_id>/like/", comments.like_comment, name="comment-like"),
    # ------------------------------------------------------------ 点赞（B203⑤）
    # ★★ 幂等：* 重复点赞返回 200 且计数不变（* ❌ 不是 409）⚠
    path(
        "notes/<str:note_ref>/likes/",
        likes.collection,
        name="note-likes",
    ),
    # --------------------------------------- 回收站 / 恢复（B210：软删 + 回收站）
    # ★★ 软删的笔记进回收站（* 可恢复）；* 管理员删是物理删（* take_down）⚠
    # ⚠★ 路由挂在 `me/` 下但视图在 `notes.py` ——* URL 命名空间讲的是"给谁看"，
    #   模块归属讲的是"谁序列化"；* 回收站是**笔记列表**，* 序列化归 notes ⚠
    path("me/notes/deleted/", notes.deleted_bin, name="me-notes-deleted"),
    # ⚠★ 恢复 ⇒* 清 deleted_at / deleted_by；* 段落按 realign 重算（* D86②）✅
    path(
        "notes/<str:note_ref>/undelete/",
        notes.undelete,
        name="note-undelete",
    ),
    # ---------------------------------------------------------- 协作者（B202/B206/B207）
    # ★★ 管理页「按用户名直接加」——* ❌ 不发链接、* ❌ 不要 token（* `B206`）⚠
    path(
        "projects/<project_ref:project_ref>/collaborators/",
        collaborators.collection,
        name="project-collaborators",
    ),
    # ⚠★ 用户名走 `<str:...>` ——* Django 用户名允许 `@ . + - _`，* ❌ 不含 `/` ✅
    # ★★ 移除是**幂等**的：* 移一个不是成员的用户 ⇒ * 200 `removed:false` ⚠
    path(
        "projects/<project_ref:project_ref>/collaborators/<str:username>/",
        collaborators.remove,
        name="project-collaborator-remove",
    ),
    # ------------------------------------------------------------ 设置（B190）
    # ★★ 用户档 / 项目档（* 三级继承，* 见 core/settings_table.py）⚠
    path("me/settings/", settings.user_settings, name="user-settings"),

    # ------------------------------------------------------------ 用户空间（2026-10-24）
    # ★ 参考 B 站个人空间：头部资料 → Tab → 内容流 ⚠
    # ⚠ `/api/u/<username>/` 是**公开**的（游客可看，只给公开内容）✅
    path("u/<str:username>/", user_space.detail, name="user-space"),
    path("u/<str:username>/notes/", user_space.notes, name="user-space-notes"),
    path("u/<str:username>/projects/", user_space.projects, name="user-space-projects"),
    path("u/<str:username>/activity/", user_space.activity, name="user-space-activity"),
    path("me/profile/", user_space.my_profile, name="me-profile"),
    path(
        "projects/<project_ref:project_ref>/settings/",
        settings.project_settings,
        name="project-settings",
    ),

    # ------------------------------------------------------------ 作业（全局）
    path("jobs/<int:job_id>/", jobs_api.job_detail, name="job-detail"),
    path("jobs/<int:job_id>/cancel/", jobs_api.job_cancel, name="job-cancel"),
    ]
