"""Astrolabe · `manage.py storage_usage` —— 存储空间用量 / 对账（`B152`）

★ 两个用途：

```bash
# ★ 看某人用了多少（+ 他名下每个项目各占多少）
python manage.py storage_usage --user alice

# ★★ 对账：把"记账"与"磁盘实测"比一遍（⚠ 分叉了就 --fix）
python manage.py storage_usage --audit [--fix]
```

⚠★ 为什么必须有 `--audit`：★ 记账是**应用层**写的 ——
⚠ 进程被杀 / `OSError` / 有人手工删目录，都会让两边**悄悄分叉**。
★ 而分叉的后果是「**用户空间虚满**」或「**磁盘悄悄泄漏**」——
★★ 两种都不会报错，只会**慢慢地变得不对劲**。
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core import storage


def _human(n: int) -> str:
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} TB"


class Command(BaseCommand):
    help = "查看 / 对账用户存储空间占用（B152）"

    def add_arguments(self, parser):
        parser.add_argument("--user", help="只看某个用户")
        parser.add_argument("--audit", action="store_true", help="对账记账与磁盘实测")
        parser.add_argument("--fix", action="store_true", help="对账时顺带修正（⚠ 会用实测值覆盖记账）")
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **opts):
        self.stdout.write(f"存储根目录：{storage.root()}")
        self.stdout.write("")

        if opts["audit"]:
            return self._audit(fix=opts["fix"])
        return self._usage(user=opts["user"], limit=opts["limit"])

    # ------------------------------------------------------------------

    def _usage(self, *, user: str | None, limit: int) -> None:
        User = get_user_model()
        if user:
            u = User.objects.filter(username=user).first()
            if u is None:
                self.stderr.write(f"找不到用户：{user}")
                return
            cap = storage.check_capacity(u)
            self.stdout.write(
                f"{u.username}（{cap.source}）"
                f"  已用 {_human(cap.used_bytes)} / {_human(cap.limit_bytes)}"
                f"  ({cap.used_ratio:.1%})   文件 {cap.used_files} / {cap.limit_files}"
            )
            self.stdout.write("")
            self.stdout.write(f"{'字节':>12}  {'文件':>7}  project_ref")
            self.stdout.write("-" * 60)
            from core.models import ProjectStorage

            for r in ProjectStorage.objects.filter(owner=u).order_by("-bytes_used"):
                self.stdout.write(
                    f"{r.bytes_used:>12}  {r.files_used:>7}  {r.project_ref}"
                )
            return

        # ★ 全体排行（★ 便于发现"谁快满了"）
        self.stdout.write(f"{'用户':<24} {'已用':>10} {'上限':>10} {'占比':>7}")
        self.stdout.write("-" * 60)
        for u in User.objects.filter(project_storages__isnull=False).distinct()[:limit]:
            cap = storage.check_capacity(u)
            self.stdout.write(
                f"{u.username:<24} {_human(cap.used_bytes):>10} "
                f"{_human(cap.limit_bytes):>10} {cap.used_ratio:>6.1%}"
            )

    def _audit(self, *, fix: bool) -> None:
        rows = storage.audit(fix=fix)
        if not rows:
            self.stdout.write("✅ 记账与磁盘实测一致")
            return
        self.stdout.write(f"{'project_ref':<40} {'记账(字节,文件)':>22} {'实测':>22}")
        self.stdout.write("-" * 90)
        for r in rows:
            self.stdout.write(f"{r['project_ref']:<40} {str(r['recorded']):>22} {str(r['actual']):>22}")
        self.stdout.write("")
        self.stdout.write(
            f"⚠ 共 {len(rows)} 个不一致"
            + ("（★ 已按实测修正）" if fix else "（★ 加 --fix 修正）")
        )
