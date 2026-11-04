#!/usr/bin/env python3
"""Astrolabe · 解锁被锁定的登录用户名（P1a · 2026-11-04）

## 为什么需要它（所有者原话）

> 「用户名被锁后，只能硬等到时间到，除非我（管理员）手动给他打开。
>  也就是说，admin 账号不能被反复登陆锁死，可以整个脚本解锁。」

⚠ **admin 自己也会被锁**（有意为之：不给最值钱的账号开"免锁"白名单）。
  攻击者反复锁 admin 时，SSH 上来跑这条命令即可。

## 用法（容器内）

```bash
python /app/scripts/unlock_login.py <username>   # 解一个
python /app/scripts/unlock_login.py --all        # 全解（极端情况）
python /app/scripts/unlock_login.py --list       # 看谁被锁、还剩多久
```

宿主机等价命令见 `deploy/unlock-login.sh`（它只是把上面的命令包了一层）。

## 留痕

每次解锁写一条 `AuditLog`（action=`login.unlock`）—— 管理员操作必须可追溯。
"""

from __future__ import annotations

import os
import sys


def main(argv: list[str]) -> int:
    # ⚠ 用 `python /app/scripts/xxx.py` 跑时，sys.path[0] 是 /app/scripts（不是 /app）
    #   ⇒ 必须把项目根加进来，否则 `import mysite` 会失败
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
    import django

    django.setup()

    from core import login_guard

    args = [a for a in argv if a.strip()]
    if not args:
        print("用法: unlock_login.py <username> | --all | --list")
        return 2

    def audit(target: str, detail: dict) -> None:
        try:
            from core.models import AuditLog

            AuditLog.objects.create(
                actor=None,
                action="login.unlock",
                target_kind="username",
                target_id=target,
                detail=detail,
            )
        except Exception:  # pragma: no cover —— 留痕失败不该挡住解锁
            pass

    if args[0] == "--list":
        rows = login_guard.locked_list()
        if not rows:
            print("当前没有被锁定的用户名。")
            return 0
        print("被锁定的用户名（失败满 %d 次、锁 %d 分钟）：" % (
            login_guard.MAX_FAILS, login_guard.LOCK // 60
        ))
        for r in rows:
            print("  %-20s 失败 %-3d 剩余 %s" % (
                r["username"], r["count"], login_guard.human_ttl(r["ttl"])
            ))
        return 0

    if args[0] == "--all":
        rows = login_guard.locked_list(limit=500)
        if not rows:
            print("没有需要解锁的用户名。")
            return 0
        for r in rows:
            login_guard.clear(r["username"])
            audit(r["username"], {"by": "cli", "count": r["count"]})
            print("  已解锁：%s" % r["username"])
        print("共解锁 %d 个。" % len(rows))
        return 0

    username = args[0]
    n = login_guard.fail_count(username)
    removed = login_guard.clear(username)
    audit(username, {"by": "cli", "count": n})
    if removed:
        print("已解锁：%s（原失败 %d 次，计数已清空）" % (login_guard.normalize(username), n))
    else:
        print("没有找到计数记录：%s（本来就未被锁）" % login_guard.normalize(username))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
