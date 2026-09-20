"""Astrolabe · `manage.py cleanup_api_tokens` —— API 令牌清理 / 撤销（契约 §12 · `B161`）

★ 依据：`docs/backend-design-full.md` 与 `docs/frontend-contract.md` 的既有规格（两者同一句）：

```
python manage.py cleanup_api_tokens [--days 7] [--revoke-user <username>]
```

★ 它做**两件性质不同的事**，⚠ 不要混着理解：

| 用途 | 命令 | 语义 |
|---|---|---|
| ★ **日常清理** | `cleanup_api_tokens` | ★ **删掉"失效已久"的记录** —— ⚠ 表不该无限增长 |
| ★★ **安全响应** | `cleanup_api_tokens --revoke-user alice` | ★★ **登出全部设备** —— ⚠ 是**撤销**，不是删除 |

## ⚠★ 为什么「撤销」不删行

★ "登出全部设备"是一次**安全动作** ⇒ ★★ 事后应当查得到
「**什么时候把谁挤下去的**」⚠ —— ★ 与 `B148` 的**可审计**精神同向。

## ⚠★ `--days N` 的语义（★ 契约未写明，由 `B161` 裁定并记录）

★ **删除「失效时间距现在 ≥ N 天」的记录**；

- ★ **"失效时间"** = `revoked_at`（★ 若已撤销）否则 `expires_at`
- ★★ **为什么要这个宽限期**：★ **刚失效的 token 还有排查价值**
  （"我刚才为什么登不上"）—— ⚠ 而留太久就只是垃圾。

## ★ 为什么"清理由本表自己负责"

★ `ApiToken.Meta.indexes` 里已经有 `["expires_at"]`，★ **注释就写着「清理用」**
⇒ ★★ 说明这个清理**当初就设计好了** —— ★ 本条只是补上**执行入口** ✅

用法：
    python manage.py cleanup_api_tokens                        # ★ 清理（默认 7 天宽限）
    python manage.py cleanup_api_tokens --days 30              # 更保守
    python manage.py cleanup_api_tokens --dry-run              # ⚠ 只看会删多少，不删
    python manage.py cleanup_api_tokens --revoke-user alice    # ★ 登出全部设备
    python manage.py cleanup_api_tokens --revoke-user alice --dry-run
    python manage.py cleanup_api_tokens --list                 # 看当前令牌分布

★ 定时跑（与 `heat_flush` 同思路）：

| 方式 | 命令 |
|---|---|
| **手动 / 排查** | `cleanup_api_tokens` |
| ★ **cron / systemd timer** | `cleanup_api_tokens`（跑完退出） |
| **常驻**（可选） | `cleanup_api_tokens --loop --interval 86400` |
"""

from __future__ import annotations

import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from core.models import ApiToken


class Command(BaseCommand):
    help = "清理失效的 API 令牌 / 撤销某用户全部令牌（★ 登出全部设备）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="★ 宽限期：失效已满 N 天的记录才删（默认 7）",
        )
        parser.add_argument(
            "--revoke-user",
            default="",
            help="★★ 撤销该用户【全部】令牌 = 登出全部设备（⚠ 不是删除）",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="⚠ 只统计，不删、不改",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="看当前令牌分布（有效 / 已过期 / 已撤销）",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="★ 常驻：周期性清理（可选，部署也可用 cron）",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=86400,
            help="常驻模式的间隔秒数（默认 86400 = 一天）",
        )

    def handle(self, *args, **opts):
        if opts["loop"]:
            return self._loop(max(int(opts["interval"]), 60), days=opts["days"])

        if opts["list"]:
            return self._list()

        if opts["revoke_user"]:
            return self._revoke_user(opts["revoke_user"], dry_run=opts["dry_run"])

        return self._cleanup(days=opts["days"], dry_run=opts["dry_run"])

    # ------------------------------------------------------------------

    @staticmethod
    def _dead_filter(cutoff):
        """★ 构造「失效已满宽限期」的查询 —— ★ 与 `Meta` 里 `expires_at` 索引对齐。

        ⚠ 两种情况要分开表达，否则会漏：

        - ★ **过期失效**（`revoked_at` 为空）：看 `expires_at`
        - ★★ **主动撤销**（`revoked_at` 不为空）：看 `revoked_at`
          ⚠★ **注意**：已撤销的 token **可能还没到 expires_at** ——
             ★ 若只按 `expires_at` 过滤，这些行**永远删不掉** ⚠
        """
        expired = Q(revoked_at__isnull=True, expires_at__lt=cutoff)
        revoked = Q(revoked_at__isnull=False, revoked_at__lt=cutoff)
        return expired | revoked

    def _cleanup(self, *, days: int, dry_run: bool) -> None:
        if days < 0:
            raise CommandError("--days 不能为负数")

        now = timezone.now()
        cutoff = now - timedelta(days=days)
        qs = ApiToken.objects.filter(self._dead_filter(cutoff))
        n = qs.count()

        if n == 0:
            self.stdout.write(f"（没有失效已满 {days} 天的令牌 —— 正常）")
            return

        if dry_run:
            self.stdout.write(
                f"[dry-run] 将删除 {n} 条令牌（失效已满 {days} 天，截止 {cutoff:%Y-%m-%d %H:%M}）"
            )
            return

        deleted, _ = qs.delete()
        self.stdout.write(
            f"已删除 {deleted} 条令牌（失效已满 {days} 天，截止 {cutoff:%Y-%m-%d %H:%M}）"
        )

    def _revoke_user(self, username: str, *, dry_run: bool) -> None:
        User = get_user_model()
        u = User.objects.filter(username=username).first()
        if u is None:
            # ★ 找不到用户 ⇒ 报错退出（❌ 不静默"当成功" —— ⚠ 那会让人以为已经登出）
            raise CommandError(f"找不到用户：{username}")

        now = timezone.now()
        # ★★ 只撤销**还有效**的（⚠ 已撤销的重复置时间会污染"何时撤销"这个事实）
        qs = ApiToken.objects.filter(user=u, revoked_at__isnull=True)
        n = qs.count()

        if n == 0:
            self.stdout.write(f"{username} 当前没有有效令牌（无需操作）")
            return

        if dry_run:
            self.stdout.write(f"[dry-run] 将撤销 {username} 的 {n} 个令牌")
            return

        updated = qs.update(revoked_at=now)
        self.stdout.write(
            self.style.WARNING(
                f"已撤销 {username} 的 {updated} 个令牌 —— 全部设备已登出"
                f"（★ 撤销时间已记录，便于事后查证）"
            )
        )

    def _list(self) -> None:
        now = timezone.now()
        rows = [
            ("★ 有效", ApiToken.objects.filter(revoked_at__isnull=True, expires_at__gt=now).count()),
            ("⚠ 已过期（未撤销）", ApiToken.objects.filter(revoked_at__isnull=True, expires_at__lte=now).count()),
            ("★ 已撤销", ApiToken.objects.filter(revoked_at__isnull=False).count()),
        ]
        total = ApiToken.objects.count()
        self.stdout.write(f"{'状态':<20} {'数量':>8}")
        self.stdout.write("-" * 32)
        for label, n in rows:
            self.stdout.write(f"{label:<20} {n:>8}")
        self.stdout.write("-" * 32)
        self.stdout.write(f"{'合计':<20} {total:>8}")

    def _loop(self, interval: int, *, days: int) -> None:
        """★ 常驻模式（可选）—— ★ 与 `heat_flush --loop` 同一套路。

        ⚠ 单次失败**不退出**（继续下一轮）；错误写 stderr。
        """
        self.stdout.write(f"★ 令牌清理调度启动：每 {interval}s 一次（Ctrl+C 退出）")
        while True:
            try:
                cutoff = timezone.now() - timedelta(days=days)
                n = ApiToken.objects.filter(self._dead_filter(cutoff)).count()
                if n:
                    deleted, _ = ApiToken.objects.filter(self._dead_filter(cutoff)).delete()
                    stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
                    self.stdout.write(f"[{stamp}] 删除 {deleted} 条失效令牌")
                else:
                    stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
                    self.stdout.write(f"[{stamp}] 无失效令牌")
            except Exception as exc:  # noqa: BLE001 —— ★ 一轮失败不能终止整个调度
                self.stderr.write(self.style.ERROR(f"令牌清理失败（将在下一轮重试）：{exc}"))
            time.sleep(interval)
