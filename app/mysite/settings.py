"""Astrolabe · Django 配置

★ 分层纪律（ARCHITECTURE.md A3）：本文件**只做配置**，不放业务逻辑。
★ 配置一律从环境变量读（deploy/.env），❌ 不在代码里硬编码密码。
"""

import os
from pathlib import Path

from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key: str, default: str | None = None, *, required: bool = False) -> str | None:
    value = os.environ.get(key, default)
    if required and not value:
        raise RuntimeError(f"缺少必需的环境变量：{key}")
    return value


def env_bool(key: str, default: bool = False) -> bool:
    return str(os.environ.get(key, str(default))).lower() in ("1", "true", "yes", "on")


# ============================================================ 基础

DEBUG = env_bool("DEBUG", False)

# ★ 生产 fail-closed：DEBUG=False 时 SECRET_KEY 缺失 ⇒ 拒绝启动
SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise RuntimeError("生产环境必须设置 SECRET_KEY（见 deploy/.env）")

# ============================================================================
# ★★ 登录会话与 CSRF（B245 / B246 / B247 · 2026-10-25）⚠
# ============================================================================
# ⚠ 换回 Django session 后，**HttpOnly 由框架保证**（⛔ JS 读不到 sessionid）——
#   ★ 这正是本次替换的核心收益：旧方案把令牌放 localStorage，XSS 一读就走 ⚠

#: ★★ 会话有效期**默认 7 天**（B246，所有者：「一周就差不多了，而且后台应该可调」）
#:   · · 实际值在登录时按 `auth.session_ttl_days` 动态 `set_expiry()`
#:   · · ⚠ 这里只是兜底：配置被删 / 读到 None 时用它 ⚠
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7

#: ★ HttpOnly —— ⛔ 绝不允许 JS 读 sessionid（XSS 的最后一道闸）
SESSION_COOKIE_HTTPONLY = True

#: ★ 后台与前台**同源同端口** ⇒ SameSite=Lax 足够，且不影响登录跳转
SESSION_COOKIE_SAMESITE = "Lax"

#: ★★ CSRF Cookie **必须可被 JS 读取**（否则前端拿不到 token 发 X-CSRFToken）⚠
#:   · · 它保护的正是 sessionid，⛔ 千万不能顺手设成 True（B247② 踩过这个念头）⚠
CSRF_COOKIE_HTTPONLY = False

#: ★ 前端统一读这个名字（见 frontend/src/api/client.ts）
CSRF_COOKIE_NAME = "csrftoken"

ALLOWED_HOSTS = [h.strip() for h in (env("ALLOWED_HOSTS", "") or "").split(",") if h.strip()]
if not ALLOWED_HOSTS and not DEBUG:
    raise RuntimeError("生产环境必须设置 ALLOWED_HOSTS（见 deploy/.env）")

# ★ 部署版本：public / enterprise（PRODUCT-VERSIONS.md）
ASTROLABE_EDITION = env("ASTROLABE_EDITION", "public")

# ============================================================ 应用
#
# ★ 按 ARCHITECTURE.md 的分层组织：
#     core  —— 共享内核（模型 / 常量 / 健康检查）
#     web   —— ① Web 层（API / 权限 / UGC）
#     jobs  —— ② 作业层（作业表 / 队列 / worker）
#     graph —— 图（模型与查询，被 ① ② 共用）

INSTALLED_APPS = [
    # ★★★ 管理后台主题（django-unfold 0.110.0 · MIT · 2026-10-24）⚠
    #   · · ⚠ **必须排在 `django.contrib.admin` 之前**（* 它会覆盖 admin 模板）⚠
    #   · · 所有者要求「用现成的、经过时间检验的」，* 不自建后台 ✅
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # ★★ `B220`：* ArrayField / GinIndex 需要（* 数组列 + GIN 索引）⚠
    "django.contrib.postgres",
    # ---- Astrolabe ----
    "core",
    "graph",
    "jobs",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # ★★★ 2026-10-25（B245）：**BearerAuthMiddleware 已删除** —— 公网改用 Django session。
    #   · · 原话：「我的天呐，你把django设计好的维持登陆状态和身份识别的令牌系统给了后台了吗？」
    #   · · ⇒ 认证回到 `AuthenticationMiddleware`（Django 默认次序即可，⛔ 不再需要上移）⚠
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # ★★ B247②：GET 时种 csrftoken Cookie（* 否则前端第一个 POST 就 403）⚠
    #   ⚠ 必须在 CsrfViewMiddleware **之前**（* 它靠 META 里的值在 process_response 种 Cookie）⚠
    "web.middleware.CsrfCookieMiddleware",
    # ★★ 设备令牌（* 给游客发一个签名 Cookie，* 用于限流身份识别）⚠
    "web.middleware.DeviceTokenMiddleware",
    # ★★ 搜索限流（* 任何带 q 的 GET 统一判一次）⚠
    "web.middleware.SearchRateLimitMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mysite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # ★★ 后台模板覆盖目录（2026-10-24）⚠
        #   · · unfold 的 admin 模板在 INSTALLED_APPS 里排在前头，
        #     * 放 templates/admin/ 会被它的同名文件盖掉 ⇒ 必须走 DIRS（优先级更高）✅
        "DIRS": [BASE_DIR / "core" / "templates_override"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "mysite.wsgi.application"
ASGI_APPLICATION = "mysite.asgi.application"

# ============================================================ 数据库

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "astrolabe"),
        "USER": env("POSTGRES_USER", "astrolabe"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        # ★ 连接复用（DEPLOYMENT.md：提高并发）
        "CONN_MAX_AGE": 60,
    }
}

# ============================================================ 缓存 / 队列
#
# ★ Redis 双重职责（JOB-MODEL.md J9）：
#     ① 作业队列中介（① Web 写、② worker 读）
#     ② 邻域查询缓存（GRAPH-STORAGE.md G5）

REDIS_URL = env("REDIS_URL", "redis://redis:6379/0")

# ============================================================ 图查询
#
# ★ 依据 GRAPH-STORAGE.md G6：「将来可换图数据库」的**唯一预留点**。
#   ⚠ 现在只定「接口 + 一个实现」—— ★ 换图库只需改下面这一行字符串，
#     ① Web 层的调用代码**一行都不用改**。

ASTROLABE_GRAPH_READER = env(
    "ASTROLABE_GRAPH_READER", "graph.traversal.PostgresAdjacencyReader"
)

# ★★ 防爆炸（GRAPH-STORAGE.md G4）—— 「深度硬上限 + 结果上限」**两个都必须有**：
#   ⚠ 高中心度节点 2 跳就能牵扯出上万节点（G4-2）
#   ★★ statement_timeout = 「不卡死系统」的**最后一道保险**（由数据库强制中断，
#      而不是靠应用自我克制）
ASTROLABE_NEIGHBORHOOD = {
    "default_depth": int(env("NEIGH_DEFAULT_DEPTH", "1")),
    "max_depth": int(env("NEIGH_MAX_DEPTH", "10")),
    "max_nodes": int(env("NEIGH_MAX_NODES", "3000")),
    "max_edges": int(env("NEIGH_MAX_EDGES", "8000")),
    "max_seconds": float(env("NEIGH_MAX_SECONDS", "3")),
    "statement_timeout_ms": int(env("NEIGH_STMT_TIMEOUT_MS", "5000")),
}

# ★ 邻域缓存 + 节点访问热度（GRAPH-STORAGE.md G5）
#
#   ⚠ 失效**不靠 TTL**，靠 `GraphRevision.rev` 换命名空间（图一变即失效，O(1)）；
#     TTL 只负责把旧代际的 key 清掉，别无限占内存。
#   ★★ `socket_timeout` / `breaker_*` 是「**不卡死系统**」的保险 ——
#      Redis 慢或挂时，读路径必须**毫秒级失败并降级**，而不是挂在那里。
#   ★ 热度按 `uid` 记（跨重新解析稳定），见 graph/cache.py。
ASTROLABE_NEIGHBORHOOD_CACHE = {
    "enabled": env_bool("NEIGH_CACHE", True),
    "hot_enabled": env_bool("NEIGH_HOT", True),
    "ttl": int(env("NEIGH_CACHE_TTL", str(30 * 86400))),
    # ★ 超过这个大小不缓存（常查的是"难懂的那几个函数"，结果很小）
    "max_bytes": int(env("NEIGH_CACHE_MAX_BYTES", str(256 * 1024))),
    "socket_timeout": float(env("REDIS_SOCKET_TIMEOUT", "1.0")),
    "socket_connect_timeout": float(env("REDIS_CONNECT_TIMEOUT", "0.5")),
    "breaker_threshold": int(env("REDIS_BREAKER_THRESHOLD", "3")),
    "breaker_cooldown": float(env("REDIS_BREAKER_COOLDOWN", "10")),
}

# ★ 热度合并（Redis 热数据 → 数据库权威值，B128）
#   ⚠ 这是**维护作业**，不在请求路径上 —— 由 cron / systemd timer 调 `manage.py heat_flush`
#   ★ 用 Redis 锁保证同一批次只被一个进程处理（lock_ttl 应大于单次合并耗时）
ASTROLABE_HEAT = {
    "metrics": tuple(m.strip() for m in env("HEAT_METRICS", "visit").split(",") if m.strip()),
    "lock_ttl": int(env("HEAT_LOCK_TTL", "120")),
}

# ============================================================ OAuth（U4 · U4.8）
#
# ★★ **`client_secret` 是机密 ⇒ 必须走环境变量，❌ 绝不进 `AppSetting`** ——
#    ⚠ 后者会落进数据库，**并且要在后台页面上明文显示**。
#
# ★ **只申请 `read:user` / `user_info`**（`U3.3`：★ 权限越少，越多人敢点）
#   ⇒ ⚠★ **不申请任何读私有仓库的权限**（`PRODUCT-VERSIONS` B1：禁止私有源码上行）
#
# ★ 没配好的 provider **不会出现在登录页上**（见 `oauth.enabled_providers()`）——
#   ⚠ 否则用户点了一定报错。

ASTROLABE_BASE_URL = env("ASTROLABE_BASE_URL", "http://localhost:8000")

# ★★ **OAuth 回调后要把浏览器送回哪里** —— ⚠★ 这是**安全配置，不是普通配置**：
#
#   ⚠★★ `next_url` 是**用户可控**的（前端可以传）⇒ ★★ **必须做白名单校验**，
#     否则就是一个 **open redirect**：★ 攻击者构造
#       `/api/auth/github/start/?next_url=https://evil.com`
#     ⇒ 回调后我们把**带着 token 的 fragment** 重定向到 evil.com
#     ⇒ ★★★ **token 直接泄露给攻击者**。
#
#   ★ 所以：★ 只允许「**同源**」或「**站内相对路径**」（见 `web/views/auth.py::safe_next_url`）。
ASTROLABE_SPA_URL = env("ASTROLABE_SPA_URL", "http://localhost:8080")

# ============================================================ 用户存储空间（B152）
#
# ★★ 每个项目的源码落在 `{ROOT}/{project_ref}/` 下。
#
# ⚠★ **为什么用 `project_ref` 分目录，而不是 `user_id`**：
#   ★ `project_ref` 的形态是 `proj_[0-9a-f]{32}` ⇒ **天然不含 `/` 与 `..`**
#     ⇒ ★★ **路径穿越在结构上就不可能**（★ 比"每次小心校验"可靠得多）。
#   ⚠★ 而**绝不能**用用户提供的路径 —— ⚠ 那等于让他读容器里的**任何**目录。
#
# ⚠ 生产必须挂到**独立的数据卷**上（❌ 不要放在容器可写层 —— 那会随容器重建丢失）。
ASTROLABE_STORAGE_ROOT = env("ASTROLABE_STORAGE_ROOT", "/data/astrolabe/projects")

# ★ 允许的 `next_url` 来源（**逗号分隔的 origin**，★ 例如前端有多个域名时）
ASTROLABE_ALLOWED_ORIGINS = tuple(
    o.strip().rstrip("/")
    for o in env("ASTROLABE_ALLOWED_ORIGINS", ASTROLABE_SPA_URL).split(",")
    if o.strip()
)

ASTROLABE_OAUTH = {
    "github": {
        "client_id": env("GITHUB_CLIENT_ID", ""),
        "client_secret": env("GITHUB_CLIENT_SECRET", ""),
    },
    "gitee": {
        "client_id": env("GITEE_CLIENT_ID", ""),
        "client_secret": env("GITEE_CLIENT_SECRET", ""),
    },
}

# ============================================================ 国际化 / 静态

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = env("TZ", "Asia/Shanghai")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ============================================================================
# ★★★ 管理后台外观（django-unfold · 2026-10-24）⚠
# ============================================================================
# ⚠ 侧栏分组与「先看什么」的顺序，* 按运维习惯排：内容 → 用户 → 系统 ⚠
UNFOLD = {
    "SITE_TITLE": "Astrolabe 后台",
    "SITE_HEADER": "Astrolabe 后台",
    "SITE_SUBHEADER": "内容处置 · 用户与邀请 · 运行状态",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    # ★ 侧栏按运维习惯分组（* 不按 app 自动排）⚠
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "内容",
                "items": [
                    {"title": "笔记", "link": reverse_lazy("admin:core_note_changelist")},
                    {"title": "段评 / 章评", "link": reverse_lazy("admin:core_notecomment_changelist")},
                    {"title": "项目", "link": reverse_lazy("admin:core_project_changelist")},
                    # ⚠ 「项目协作者」**不进侧栏**（2026-10-24 所有者：「完全没用」）⚠
                    #   · · 前台在「项目设置 → 协作者」就能管；后台这个只是全局镜像，
                    #     只有排查"某人怎么会被加进这个项目"时才用得上
                    #   · · 仍然注册着 ⇒ 直接访问 /admin/core/collaborator/ 可用 ✅
                ],
            },
            {
                "title": "用户与邀请",
                "items": [
                    {"title": "用户", "link": reverse_lazy("admin:auth_user_changelist")},
                    {"title": "用户档案", "link": reverse_lazy("admin:core_userprofile_changelist")},
                    {"title": "邀请码", "link": reverse_lazy("admin:core_invite_changelist")},
                ],
            },
            {
                "title": "系统",
                "items": [
                    {"title": "运维概览", "link": reverse_lazy("admin:ops-dashboard")},
                    {"title": "审计日志", "link": reverse_lazy("admin:core_auditlog_changelist")},
                    {"title": "站点参数", "link": reverse_lazy("admin:core_appsetting_changelist")},
                    {"title": "存储占用", "link": reverse_lazy("admin:core_projectstorage_changelist")},
                ],
            },
        ],
    },
}
