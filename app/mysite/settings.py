"""Astrolabe · Django 配置

★ 分层纪律（ARCHITECTURE.md A3）：本文件**只做配置**，不放业务逻辑。
★ 配置一律从环境变量读（deploy/.env），❌ 不在代码里硬编码密码。
"""

import os
from pathlib import Path

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
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # ---- Astrolabe ----
    "core",
    "graph",
    "jobs",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # ⚠★ **`AuthenticationMiddleware` 被【上移】了**（Django 默认把它放在 CsrfView 之后）——
    #   原因见 `web/middleware.py` 顶部的三条硬要求：
    #   ★ 契约 §7 要求「BearerAuthMiddleware 必须在 CSRF 之前、且在 AuthenticationMiddleware 之后」。
    #   ★ Django 默认次序**同时满足不了这两条** ⇒ 必须把 Authentication 提前。
    #   ⚠ 上移是安全的：`CsrfViewMiddleware` 不读 `request.user`，两者无耦合。
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # ★★ Bearer 三态判定（`U4.4` / 契约 §7）—— 位置是硬要求，见 `web/middleware.py`
    "web.middleware.BearerAuthMiddleware",
    "django.middleware.common.CommonMiddleware",
    # ★ 到这里 `_dont_enforce_csrf_checks` 已经被 Bearer 中间件设好了 ✅
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mysite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
