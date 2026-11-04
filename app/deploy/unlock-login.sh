#!/usr/bin/env bash
# Astrolabe · 解锁被锁定的登录用户名（P1a · 2026-11-04）
#
# ## 为什么需要它（所有者原话）
#
# > 「用户名被锁后，只能硬等到时间到，除非我（管理员）手动给他打开。
# >  也就是说，admin 账号不能被反复登陆锁死，可以整个脚本解锁。」
#
# ## 用法（SSH 上执行，永远最高优先级）
#
# ```bash
# sudo app/deploy/unlock-login.sh --list          # 看谁被锁、还剩多久
# sudo app/deploy/unlock-login.sh admin           # 解一个
# sudo app/deploy/unlock-login.sh --all           # 全解（极端情况）
# ```
#
# ⚠ **admin 自己也会被锁**（有意为之：不给最值钱的账号开"免锁"白名单）。
#   攻击者反复锁 admin ⇒ 跑这条命令即可，不需要重启、不影响其他人的会话。
#
# ⚠ 后台也有同样的按钮：「访问审计 → ⑥ 登录锁定」（需要登录才能点）。
#   登不进去的时候，就是这条脚本的用武之地。

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/home/ma/astrolabe/app/deploy}"

if [ $# -lt 1 ]; then
    echo "用法: $0 <username> | --all | --list" >&2
    exit 2
fi

cd "$COMPOSE_DIR"

# 参数原样传给容器内的脚本（--list / --all / 用户名）
exec docker compose exec -T web python /app/scripts/unlock_login.py "$@"
