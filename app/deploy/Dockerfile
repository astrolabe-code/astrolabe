# syntax=docker/dockerfile:1
#
# Astrolabe · 多版本构建
# ---------------------------------------------------------------------------
# ★ 构建目标（三个版本中的两个；个人版不在此文件内）
#
#   base        —— 公共基础（系统包 + Python 依赖）
#   public      —— ★ 公开版（部署到互联网，由我运营）
#   enterprise  —— ★ 企业版（＝ 公开版 + 企业功能；授权客户在内网部署）
#
# ⚠ 个人版（Node + SQLite）【不在本文件内】—— 它是【独立技术栈】，
#    见 deploy/PERSONAL-NOTE.md（待其栈定稿后再立项）
#
# 构建示例：
#   docker build -t astrolabe:public     --target public     -f deploy/Dockerfile .
#   docker build -t astrolabe:enterprise --target enterprise -f deploy/Dockerfile .
#
# ★ 镜像源可覆盖（国内默认走阿里云 / 清华，境外构建时换回官方）：
#   docker build --build-arg APT_MIRROR=deb.debian.org \
#                --build-arg PIP_INDEX=https://pypi.org/simple ...
#
# ★ 设计要点：源码【不 COPY 进镜像】—— 运行时由 compose bind mount 进来
#   （DEPLOYMENT.md D1：方便在宿主机直接查看与修改）
#   ⇒ 改代码【无需重建镜像】✅
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12

# ============================ base ============================
FROM python:${PYTHON_VERSION}-slim AS base

# ★ 镜像源（可在构建时覆盖）
ARG APT_MIRROR=mirrors.aliyun.com
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# ★ libpq5 —— psycopg 运行时依赖
# ★ curl    —— 容器 healthcheck 用
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        ca-certificates; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ★ 依赖先装（利用层缓存：改代码不会重装依赖）
COPY requirements.txt ./
RUN pip install --no-cache-dir -i "${PIP_INDEX}" -r requirements.txt

EXPOSE 8000

# ⚠ 占位命令 —— 实际由 compose 的 command 覆盖（web 用 gunicorn，worker 用 run_worker）
CMD ["python", "-c", "print('astrolabe: this image must be run via docker compose')"]

# ============================ 公开版 ============================
FROM base AS public

ENV ASTROLABE_EDITION=public

# ★ 公开版只含核心能力（PRODUCT-VERSIONS.md B1）：
#    图 / 解释 / 阅读路径 / 提问 —— 服务端解析，源码只能从 GitHub·Gitee 拉取
CMD ["gunicorn", "mysite.asgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--worker-class", "uvicorn.workers.UvicornWorker"]

# ============================ 企业版 ============================
FROM base AS enterprise

ENV ASTROLABE_EDITION=enterprise

# ★ 企业版 = 公开版 + 企业功能（多租户 / SSO / 审计报表 / 白标）
#
# ⚠ 现状：**企业功能【一期不做】**（PRODUCT-VERSIONS.md F 节）
#    因此本 target 当前与 public 等价，仅【环境变量不同】。
#
# ★ 将来在此追加企业模块（⚠ 且必须满足两条硬约束）：
#    ① 企业模块源码【不进公开仓库】（PRODUCT-VERSIONS.md C 节）
#    ② 功能必须【可开可关】地设计（PRODUCT-VERSIONS.md F 节：将来可收回进公开版付费层）
CMD ["gunicorn", "mysite.asgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--worker-class", "uvicorn.workers.UvicornWorker"]
