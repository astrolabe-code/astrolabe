"""Astrolabe · `manage.py purge_expired_states` —— 清理过期的 OAuth `state`（`B161`）

★ 依据：`core/oauth.py::purge_expired_states()` —— ★★ `B148` 就已实现，
  且当轮实测「**过期被拒 · 清理接口可用**」✅

⚠★ **那个函数的 docstring 自己写着**：

> ★ 由**定时作业**调用（★ 同 `heat_flush` 的思路）

⇒ ★★ **口径本就指向"命令形态"** ⇒ ★ **本条只是给它一个【命令入口】**，
   ❌ **不改它的任何逻辑**（★ 逻辑已在 `oauth.py` 里，⚠ 不复制到命令里
   —— ★ 同 `B157` 抓出的教训：**同一件事写两遍，早晚有一处会漏**）。

## ⚠ 为什么要清

★ `OAuthState` 是**一次性**的（★ `consumed_at` 标记 + `select_for_update` 防重放）
⇒ ★★ **每个登录 / 每次发布都会落一行** ⇒ ⚠ **不清就会无限增长**。

★ 而它的 `Meta.indexes` 里已有 `["expires_at"]`，★ **注释写着「清理用」**
⇒ ★★ 说明这一步**当初就设计好了** ✅

用法：
    python manage.py purge_expired_states                    # ★ 清一次，跑完退出
    python manage.py purge_expired_states --dry-run          # ⚠ 只看会清多少
    python manage.py purge_expired_states --loop --interval 3600   # ★ 常驻
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from core import oauth
from core.models import OAuthState


class Command(BaseCommand):
    help = "清理过期的 OAuthState（★ 否则这张表会无限增长）"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="⚠ 只统计，不删")
        parser.add_argument("--loop", action="store_true", help="★ 常驻：周期性清理（可选）")
        parser.add_argument(
            "--interval",
            type=int,
            default=3600,
            help="常驻模式的间隔秒数（默认 3600 = 1 小时）",
        )

    def handle(self, *args, **opts):
        if opts["loop"]:
            return self._loop(max(int(opts["interval"]), 60), dry_run=opts["dry_run"])

        if opts["dry_run"]:
            n = OAuthState.objects.filter(expires_at__lt=timezone.now()).count()
            self.stdout.write(f"[dry-run] 将清理 {n} 条过期 state")
            return

        n = oauth.purge_expired_states()
        if n == 0:
            self.stdout.write("（没有过期 state —— 正常）")
        else:
            self.stdout.write(f"已清理 {n} 条过期 state")

    def _loop(self, interval: int, *, dry_run: bool) -> None:
        """★ 常驻模式（可选）—— ★ 同 `heat_flush --loop`：单次失败不退出。"""
        mode = "（dry-run，不删）" if dry_run else ""
        self.stdout.write(f"★ state 清理调度启动：每 {interval}s 一次{mode}（Ctrl+C 退出）")
        while True:
            try:
                stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
                if dry_run:
                    n = OAuthState.objects.filter(expires_at__lt=timezone.now()).count()
                    self.stdout.write(f"[{stamp}] 待清理 {n} 条")
                else:
                    n = oauth.purge_expired_states()
                    self.stdout.write(
                        f"[{stamp}] 清理 {n} 条" if n else f"[{stamp}] 无过期 state"
                    )
            except Exception as exc:  # noqa: BLE001 —— ★ 一轮失败不能终止整个调度
                self.stderr.write(self.style.ERROR(f"state 清理失败（将在下一轮重试）：{exc}"))
            time.sleep(interval)
